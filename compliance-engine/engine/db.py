"""SQLite persistence.

One file, WAL mode, dict rows. Every table has an integer primary key and ISO timestamps.
Kept intentionally plain so the dashboard and the CLI can query it directly.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY,
  domain TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  business_name TEXT,
  category TEXT,
  city TEXT, region TEXT, country TEXT DEFAULT 'US',
  contact_email TEXT,
  contact_source TEXT,
  platform TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  source TEXT,
  needs_human_reason TEXT,
  next_action_at TEXT,
  followups_sent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);

CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES leads(id),
  kind TEXT NOT NULL DEFAULT 'baseline',       -- baseline | verification
  status TEXT NOT NULL,                          -- ok | failed
  ada_score INTEGER, aiseo_score INTEGER,
  ada_summary TEXT, aiseo_summary TEXT,          -- JSON
  pages TEXT,                                    -- JSON list of urls scanned
  exposure TEXT,                                 -- JSON
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_lead ON scans(lead_id);

CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY,
  scan_id INTEGER NOT NULL REFERENCES scans(id),
  kind TEXT NOT NULL,            -- ada | aiseo
  rule_id TEXT NOT NULL,
  impact TEXT,                   -- critical | serious | moderate | minor
  description TEXT,
  help_url TEXT,
  page_url TEXT,
  count INTEGER NOT NULL DEFAULT 1,
  sample TEXT                    -- JSON: selectors / html snippets
);
CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES leads(id),
  thread_token TEXT NOT NULL,
  direction TEXT NOT NULL,       -- out | in
  kind TEXT NOT NULL,            -- initial | followup | reply | checkout | delivery | system
  subject TEXT, body_text TEXT, body_html TEXT,
  to_addr TEXT, from_addr TEXT,
  message_id TEXT, in_reply_to TEXT,
  status TEXT NOT NULL,          -- draft | queued | sent | failed | suppressed | received | held
  intent TEXT,                   -- classification for inbound
  lint TEXT,                     -- JSON lint result for outbound
  provider_id TEXT,
  approved INTEGER NOT NULL DEFAULT 0,
  hold_reason TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_lead ON messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_token);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);

CREATE TABLE IF NOT EXISTS deals (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER NOT NULL REFERENCES leads(id),
  package TEXT NOT NULL,
  price_cents INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'usd',
  status TEXT NOT NULL,
  checkout_url TEXT,
  stripe_session_id TEXT,
  stripe_payment_intent TEXT,
  tax_cents INTEGER,
  created_at TEXT NOT NULL,
  paid_at TEXT, delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_deals_lead ON deals(lead_id);

CREATE TABLE IF NOT EXISTS fixes (
  id INTEGER PRIMARY KEY,
  deal_id INTEGER NOT NULL REFERENCES deals(id),
  status TEXT NOT NULL,          -- planned | built | applied | delivered | verified | failed
  strategy TEXT,
  bundle_path TEXT,
  summary TEXT,                  -- JSON
  before_ada INTEGER, after_ada INTEGER,
  before_aiseo INTEGER, after_aiseo INTEGER,
  error TEXT,
  created_at TEXT NOT NULL,
  applied_at TEXT, verified_at TEXT
);

CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY,
  deal_id INTEGER REFERENCES deals(id),
  kind TEXT NOT NULL,            -- charge | refund | processing_fee | sales_tax
  amount_cents INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'usd',
  stripe_id TEXT,
  memo TEXT,
  occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suppression (
  id INTEGER PRIMARY KEY,
  address TEXT NOT NULL UNIQUE,  -- email or @domain
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  lead_id INTEGER,
  kind TEXT NOT NULL,
  detail TEXT,                   -- JSON
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);

CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = _dict_factory
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    # -- low level ---------------------------------------------------------
    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        return self._conn.execute(sql, params).fetchone()

    def insert(self, table: str, row: dict[str, Any]) -> int:
        row = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        cur = self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
        return int(cur.lastrowid)

    def update(self, table: str, row_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in fields.items()}
        if table in ("leads",):
            fields["updated_at"] = utcnow()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*fields.values(), row_id))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN")
        try:
            yield
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self._conn.close()

    # -- kv / control switches ------------------------------------------------
    def get_kv(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM kv WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_kv(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def is_paused(self) -> bool:
        return self.get_kv("paused", "0") == "1"

    # -- events ----------------------------------------------------------------
    def log_event(self, event: str, lead_id: int | None = None, **detail: Any) -> int:
        return self.insert(
            "events", {"lead_id": lead_id, "kind": str(event), "detail": detail, "created_at": utcnow()}
        )

    # -- leads -----------------------------------------------------------------
    def upsert_lead(self, **lead: Any) -> tuple[int, bool]:
        """Insert a lead by domain; returns (id, created)."""
        existing = self.one("SELECT id FROM leads WHERE domain = ?", (lead["domain"],))
        if existing:
            return existing["id"], False
        now = utcnow()
        lead.setdefault("status", "new")
        lead.setdefault("created_at", now)
        lead.setdefault("updated_at", now)
        lead_id = self.insert("leads", lead)
        self.log_event("lead_created", lead_id, domain=lead["domain"], source=lead.get("source"))
        return lead_id, True

    def get_lead(self, lead_id: int) -> dict[str, Any] | None:
        return self.one("SELECT * FROM leads WHERE id = ?", (lead_id,))

    def set_lead_status(self, lead_id: int, status: str, reason: str | None = None) -> None:
        lead = self.get_lead(lead_id)
        if lead and lead["status"] != status:
            self.update("leads", lead_id, status=status, needs_human_reason=reason)
            self.log_event("status_changed", lead_id, **{"from": lead["status"], "to": status, "reason": reason})

    def leads_by_status(self, *statuses: str, limit: int = 1000) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in statuses)
        return self.query(
            f"SELECT * FROM leads WHERE status IN ({marks}) ORDER BY id LIMIT ?", (*statuses, limit)
        )

    def latest_scan(self, lead_id: int, kind: str = "baseline") -> dict[str, Any] | None:
        row = self.one(
            "SELECT * FROM scans WHERE lead_id = ? AND kind = ? AND status = 'ok' ORDER BY id DESC LIMIT 1",
            (lead_id, kind),
        )
        if row:
            for k in ("ada_summary", "aiseo_summary", "pages", "exposure"):
                if row.get(k):
                    row[k] = json.loads(row[k])
        return row

    def findings_for_scan(self, scan_id: int) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM findings WHERE scan_id = ? ORDER BY kind, impact, rule_id", (scan_id,))
        for r in rows:
            if r.get("sample"):
                r["sample"] = json.loads(r["sample"])
        return rows

    # -- suppression --------------------------------------------------------------
    def suppress(self, address: str, reason: str, lead_id: int | None = None) -> None:
        address = address.strip().lower()
        self._conn.execute(
            "INSERT OR IGNORE INTO suppression (address, reason, created_at) VALUES (?, ?, ?)",
            (address, reason, utcnow()),
        )
        self.log_event("suppressed", lead_id, address=address, reason=reason)

    def is_suppressed(self, email: str) -> bool:
        email = email.strip().lower()
        domain = "@" + email.split("@", 1)[-1]
        row = self.one("SELECT 1 FROM suppression WHERE address IN (?, ?)", (email, domain))
        return row is not None

    # -- messages / threads -------------------------------------------------------
    def thread(self, thread_token: str) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM messages WHERE thread_token = ? ORDER BY id", (thread_token,))

    def thread_for_lead(self, lead_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM messages WHERE lead_id = ? ORDER BY id", (lead_id,))

    def sent_today_count(self, day_prefix: str) -> int:
        row = self.one(
            "SELECT COUNT(*) AS n FROM messages WHERE direction='out' AND status='sent' AND sent_at LIKE ?",
            (day_prefix + "%",),
        )
        return int(row["n"]) if row else 0

    # -- deals ----------------------------------------------------------------------
    def open_deal(self, lead_id: int) -> dict[str, Any] | None:
        return self.one(
            "SELECT * FROM deals WHERE lead_id = ? AND status NOT IN ('cancelled','refunded') ORDER BY id DESC LIMIT 1",
            (lead_id,),
        )

    # -- stats for dashboard ------------------------------------------------------
    def counts_by_status(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self.query("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}
