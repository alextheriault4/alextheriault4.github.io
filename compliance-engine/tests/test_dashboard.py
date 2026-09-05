from __future__ import annotations

from fastapi.testclient import TestClient

from engine.dashboard.app import create_app
from engine.db import Database
from engine.deals.checkout import open_or_create_deal
from engine.inbox.provider import ConsoleProvider
from engine.llm import FakeLLM
from engine.models import Package
from engine.orchestrator import Orchestrator
from engine.outreach.compose import compose_initial
from engine.outreach.sequence import deliver_queued
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site
from tests.test_pipeline import MONDAY_NOON_UTC


def test_dashboard_pages_and_public_routes(bad_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url, business_name="Springfield Family Dental",
                                category="dentist", city="Springfield", region="IL", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    classify_after_scan(db, settings, lead_id, scan_id)
    compose_initial(db, settings, FakeLLM(), lead_id)
    deliver_queued(db, settings, ConsoleProvider(settings.workdir), now=MONDAY_NOON_UTC)
    token = db.thread_for_lead(lead_id)[0]["thread_token"]
    deal = open_or_create_deal(db, lead_id, Package.BUNDLE, settings.pricing.bundle_cents, "usd")

    app = create_app(settings, db)
    c = TestClient(app, follow_redirects=False)
    assert c.get("/").status_code == 303                       # not signed in
    assert c.get("/health").json()["ok"] is True
    assert c.post("/login", data={"token": "wrong"}).status_code == 403
    r = c.post("/login", data={"token": settings.dashboard.admin_token})
    assert r.status_code == 303 and "ce_admin" in r.cookies
    for path in ("/", "/leads", "/leads?status=contacted", f"/leads/{lead_id}", "/outbox", "/finance"):
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    assert "springfielddental.example" in c.get("/leads").text
    assert c.get("/finance/export.csv").text.startswith("date,kind")

    # public pages need no auth
    anon = TestClient(app, follow_redirects=False)
    r = anon.get(f"/r/{token}")
    assert r.status_code == 200 and "Estimates, not predictions" in r.text and "unsubscribe" in r.text
    assert anon.get(f"/agreement/{deal['id']}").status_code == 200
    assert anon.get(f"/pay/{deal['id']}").status_code == 200
    assert anon.get("/r/nope").status_code == 404

    # simulate reply + payment from the dashboard
    r = c.post(f"/leads/{lead_id}/simulate-reply", data={"text": "Sounds good, go ahead and send the link"})
    assert r.status_code == 303
    deal = db.open_deal(lead_id)
    assert deal["status"] == "checkout_sent"
    assert c.post(f"/deals/{deal['id']}/simulate-payment").status_code == 303
    assert db.get_lead(lead_id)["status"] == "paid"

    # controls
    assert c.post("/controls/pause").status_code == 303 and db.is_paused()
    assert c.post("/controls/resume").status_code == 303 and not db.is_paused()

    # unsubscribe link is one click and immediate
    r = anon.get(f"/u/{token}")
    assert r.status_code == 200 and db.is_suppressed("frontdesk@springfielddental.example")
    assert db.get_lead(lead_id)["status"] == "unsubscribed"


def _in_thread(fn, *args, **kwargs):
    """The session-scoped Playwright fixture owns this thread's loop; the orchestrator opens its own browser,
    so run it the way the service does: on its own thread."""
    import threading

    out: dict = {}

    def run():
        try:
            out["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            out["error"] = e

    t = threading.Thread(target=run)
    t.start()
    t.join()
    if "error" in out:
        raise out["error"]
    return out["value"]


def test_orchestrator_tick_runs_every_stage(bad_site, settings):
    db = Database(settings.database_path)
    o = Orchestrator(settings, db=db, llm=FakeLLM(), provider=ConsoleProvider(settings.workdir))
    db.upsert_lead(domain="springfielddental.example", url=bad_site.url, category="dentist", city="Springfield", region="IL", source="test")
    rep = _in_thread(o.tick, now=MONDAY_NOON_UTC)
    assert rep["scanned"] == 1 and rep["drafted"] == 1 and rep["send"]["sent"] == 1, rep
    assert db.get_lead(1)["status"] == "contacted"
    assert db.get_kv("last_tick")
    rep2 = _in_thread(o.tick, now=MONDAY_NOON_UTC)
    assert rep2["scanned"] == 0 and rep2["send"]["sent"] == 0
