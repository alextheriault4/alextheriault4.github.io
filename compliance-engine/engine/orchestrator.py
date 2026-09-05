"""The master loop.

One ``tick`` runs every stage once, in pipeline order, each stage isolated so a failure
in one lead never stalls the others. ``run_forever`` repeats it on a timer. Every tick
writes a heartbeat the dashboard shows, so you can tell at a glance that it's alive.
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from .config import Settings, get_settings
from .db import Database, utcnow
from .fixing.verify import start_fix, verify_deal
from .inbox.handle import process_inbound
from .inbox.provider import EmailProvider, build_provider
from .llm import LLM, build_llm
from .models import LeadStatus
from .outreach.compose import compose_initial
from .outreach.sequence import deliver_queued, schedule_followups
from .prospecting.sources import CsvSource, GooglePlacesSource, OverpassSource, Prospect, dedupe
from .scanning.browser import open_browser
from .scanning.runner import classify_after_scan, persist_scan, scan_site

log = logging.getLogger("engine")


class Orchestrator:
    def __init__(self, settings: Settings | None = None, db: Database | None = None, llm: LLM | None = None,
                 provider: EmailProvider | None = None):
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings.database_path)
        self.llm = llm or build_llm(self.settings.llm)
        self.provider = provider or build_provider(self.settings)

    # -- prospecting -----------------------------------------------------------
    def add_prospects(self, prospects: list[Prospect]) -> int:
        n = 0
        for p in dedupe(prospects):
            if p.email and self.db.is_suppressed(p.email):
                continue
            _, created = self.db.upsert_lead(**p.as_lead_row())
            n += int(created)
        return n

    def prospect(self, *, category: str, city: str, region: str | None, limit: int = 50, source: str = "auto") -> int:
        s = self.settings.prospecting
        sources = []
        if source in ("auto", "google") and s.google_places_key:
            sources.append(GooglePlacesSource(s.google_places_key, timeout=s.request_timeout))
        if source in ("auto", "overpass") and (not sources or source == "overpass"):
            sources.append(OverpassSource(s.overpass_url, timeout=max(s.request_timeout, 60)))
        found: list[Prospect] = []
        for src in sources:
            try:
                found += list(src.search(category=category, city=city, region=region, limit=limit))
            except Exception as e:  # noqa: BLE001
                self.db.log_event("error", None, stage=f"prospect:{src.name}", error=str(e)[:500])
            if len(found) >= limit:
                break
        return self.add_prospects(found[:limit])

    def import_csv(self, path: str) -> int:
        return self.add_prospects(list(CsvSource(path).iter_all()))

    # -- stages ---------------------------------------------------------------------
    def stage_scan(self, limit: int = 10) -> int:
        leads = self.db.leads_by_status(LeadStatus.NEW, limit=limit)
        if not leads:
            return 0
        n = 0
        with open_browser(self.settings.scanning) as browser:
            for lead in leads:
                try:
                    result = scan_site(lead["url"], self.settings, browser)
                    scan_id = persist_scan(self.db, self.settings, lead, result)
                    classify_after_scan(self.db, self.settings, lead["id"], scan_id)
                    n += 1
                except Exception as e:  # noqa: BLE001
                    self._fail(lead["id"], "scan", e)
                    self.db.set_lead_status(lead["id"], LeadStatus.ARCHIVED, f"scan crashed: {e}")
        return n

    def stage_draft(self, limit: int = 20) -> int:
        n = 0
        for lead in self.db.leads_by_status(LeadStatus.SCANNED, limit=limit):
            try:
                if compose_initial(self.db, self.settings, self.llm, lead["id"]):
                    n += 1
            except Exception as e:  # noqa: BLE001
                self._fail(lead["id"], "draft", e)
        return n

    def stage_inbound(self) -> dict[str, int]:
        try:
            return process_inbound(self.db, self.settings, self.llm, self.provider)
        except Exception as e:  # noqa: BLE001
            self._fail(None, "inbound", e)
            return {"error": 1}

    def stage_followups(self, now: datetime | None = None) -> int:
        return schedule_followups(self.db, self.settings, now)

    def stage_send(self, now: datetime | None = None) -> dict[str, int]:
        return deliver_queued(self.db, self.settings, self.provider, now)

    def stage_fix(self) -> int:
        n = 0
        rows = self.db.query(
            "SELECT d.id FROM deals d WHERE d.status='paid' AND NOT EXISTS (SELECT 1 FROM fixes f WHERE f.deal_id=d.id) ORDER BY d.id"
        )
        for r in rows:
            try:
                start_fix(self.db, self.settings, self.llm, r["id"])
                n += 1
            except Exception as e:  # noqa: BLE001
                deal = self.db.one("SELECT lead_id FROM deals WHERE id=?", (r["id"],))
                self._fail(deal["lead_id"] if deal else None, "fix", e)
        return n

    def stage_verify(self, now: datetime | None = None) -> int:
        now_iso = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        due = self.db.query("SELECT * FROM leads WHERE status='delivered' AND next_action_at IS NOT NULL AND next_action_at <= ?", (now_iso,))
        if not due:
            return 0
        n = 0
        with open_browser(self.settings.scanning) as browser:
            for lead in due:
                deal = self.db.open_deal(lead["id"])
                if not deal:
                    continue
                try:
                    verify_deal(self.db, self.settings, browser, deal["id"])
                    n += 1
                except Exception as e:  # noqa: BLE001
                    self._fail(lead["id"], "verify", e)
        return n

    # -- loop -----------------------------------------------------------------------------
    def tick(self, now: datetime | None = None) -> dict[str, Any]:
        t0 = time.monotonic()
        report: dict[str, Any] = {"started_at": utcnow()}
        if self.db.is_paused():
            report["paused"] = True
        else:
            report["scanned"] = self.stage_scan()
            report["drafted"] = self.stage_draft()
        report["inbound"] = self.stage_inbound()
        if not self.db.is_paused():
            report["followups_queued"] = self.stage_followups(now)
            report["send"] = self.stage_send(now)
            report["fixes_started"] = self.stage_fix()
            report["verified"] = self.stage_verify(now)
        report["seconds"] = round(time.monotonic() - t0, 1)
        self.db.set_kv("last_tick", utcnow())
        self.db.set_kv("last_tick_report", __import__("json").dumps(report))
        return report

    def run_forever(self) -> None:
        log.info("engine loop starting: mode=%s tick=%ss", self.settings.mode, self.settings.tick_seconds)
        while True:
            try:
                rep = self.tick()
                log.info("tick %s", rep)
            except Exception as e:  # noqa: BLE001
                log.exception("tick crashed: %s", e)
                self.db.log_event("error", None, stage="tick", error=str(e)[:500], trace=traceback.format_exc()[-1500:])
            time.sleep(self.settings.tick_seconds)

    def _fail(self, lead_id: int | None, stage: str, e: Exception) -> None:
        log.exception("%s failed for lead %s: %s", stage, lead_id, e)
        self.db.log_event("error", lead_id, stage=stage, error=str(e)[:500], trace=traceback.format_exc()[-1500:])
