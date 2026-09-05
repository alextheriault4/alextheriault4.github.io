"""The master loop.

One ``tick`` runs every stage once, in pipeline order, each stage isolated so a failure
in one lead never stalls the others. ``run_forever`` repeats it on a timer. Every tick
writes a heartbeat the dashboard shows, so you can tell at a glance that it's alive.
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from . import autopilot
from .config import Settings, get_settings
from .db import Database, utcnow
from .fixing.verify import start_fix, verify_deal
from .inbox.handle import process_inbound
from .inbox.provider import EmailProvider, build_provider
from .legal import check_lead
from .llm import LLM, LLMCapacityError, build_llm
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
        """Add leads we are allowed to contact. Ineligible ones are dropped here, before
        we spend a scan on them, and recorded so the exclusion is auditable."""
        n = 0
        for p in dedupe(prospects):
            if p.email and self.db.is_suppressed(p.email):
                continue
            row = p.as_lead_row()
            eligible = check_lead(row, self.settings)
            if not eligible.ok:
                lead_id, created = self.db.upsert_lead(**row)
                if created:
                    self.db.set_lead_status(lead_id, LeadStatus.EXCLUDED, eligible.reason)
                    self.db.log_event("excluded", lead_id, reason=eligible.reason, stage="prospect")
                continue
            _, created = self.db.upsert_lead(**row)
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
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        leads = [l for l in self.db.leads_by_status(LeadStatus.NEW, limit=limit)
                 if not l.get("next_action_at") or l["next_action_at"] <= now]
        if not leads:
            return 0
        n = 0
        with open_browser(self.settings.scanning) as browser:
            for lead in leads:
                try:
                    result = scan_site(lead["url"], self.settings, browser)
                    scan_id = persist_scan(self.db, self.settings, lead, result)
                    classify_after_scan(self.db, self.settings, lead["id"], scan_id,
                                        page_text=result.aiseo_facts.get("text_sample", ""))
                    n += 1
                except Exception as e:  # noqa: BLE001
                    self._fail(lead["id"], "scan", e)
                    tries = int(lead.get("retry_count") or 0) + 1
                    self.db.update("leads", lead["id"], retry_count=tries)
                    if tries > self.settings.autopilot.scan_retry_attempts:
                        self.db.set_lead_status(lead["id"], LeadStatus.ARCHIVED, f"scan failed {tries}x: {e}")
        return n

    def stage_draft(self, limit: int = 20) -> int:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        n = 0
        for lead in self.db.leads_by_status(LeadStatus.SCANNED, limit=limit):
            if lead.get("next_action_at") and lead["next_action_at"] > now:
                continue  # deferred waiting for model capacity
            try:
                if compose_initial(self.db, self.settings, self.llm, lead["id"]):
                    n += 1
            except LLMCapacityError as e:
                autopilot.defer(self.db, self.settings, lead["id"], "draft", e)
            except Exception as e:  # noqa: BLE001
                self._fail(lead["id"], "draft", e)
        return n

    def stage_maintenance(self) -> dict[str, int]:
        """Housekeeping that limits what we are holding: old snapshots of other people's
        sites, and credentials for work that is already finished."""
        import shutil

        out = {"snapshots_purged": 0, "credentials_purged": 0}
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.legal.snapshot_retention_days)
        snap_root = self.settings.workdir / "snapshots"
        if snap_root.exists():
            for d in snap_root.iterdir():
                if not d.is_dir():
                    continue
                try:
                    mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    out["snapshots_purged"] += 1
        if self.settings.legal.delete_credentials_after_delivery:
            done = self.db.query(
                "SELECT DISTINCT lead_id FROM deals WHERE status IN ('verified','refunded','cancelled')")
            for row in done:
                out["credentials_purged"] += self.db.purge_lead_credentials(row["lead_id"])
        return out

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
        blocked = self.settings.live_blocked_reason()
        if blocked:
            # Configured live but not ready to be live. Keep running harmlessly (scans and
            # drafts still happen) while every outbound gate stays shut.
            report["live_blocked"] = blocked
            if self.db.get_kv("preflight_warned") != blocked:
                self.db.set_kv("preflight_warned", blocked)
                self.db.add_notice(None, "Live mode is held until preflight passes", reason=blocked)
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
            report["maintenance"] = self.stage_maintenance()
        report["open_escalations"] = len(self.db.leads_by_status(LeadStatus.NEEDS_HUMAN))
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
