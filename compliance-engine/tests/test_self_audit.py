"""Our own pages have to pass the bar we sell.

A company that emails small businesses about their inaccessible websites, from an
inaccessible website, is the easiest target in this industry. So the public pages get
scanned by our own scanner, and the same standard applies.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.dashboard.app import create_app
from engine.db import Database
from engine.deals.checkout import open_or_create_deal
from engine.llm import FakeLLM
from engine.models import Package
from engine.outreach.compose import compose_initial
from engine.scanning.ada import ada_score, run_axe
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site
from tests.conftest import SiteServer

PUBLIC_PAGES = ("/bot", "/privacy", "/terms")


def test_our_public_pages_are_accessible(bad_site, settings, browser, tmp_path):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url,
                                business_name="Springfield Family Dental", category="dentist",
                                city="Springfield", region="IL", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    classify_after_scan(db, settings, lead_id, scan_id)
    compose_initial(db, settings, FakeLLM(), lead_id)
    token = db.thread_for_lead(lead_id)[0]["thread_token"]
    deal = open_or_create_deal(db, lead_id, Package.BUNDLE, settings.pricing.bundle_cents, "usd")

    client = TestClient(create_app(settings, db))
    site = tmp_path / "ourpages"
    site.mkdir()
    paths = [*PUBLIC_PAGES, f"/agreement/{deal['id']}", f"/r/{token}", f"/u/{token}"]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code)
        (site / (path.strip("/").replace("/", "_") + ".html")).write_text(r.text, encoding="utf-8")

    server = SiteServer(site)
    try:
        page = browser.new_page()
        for html_file in sorted(site.glob("*.html")):
            page.goto(f"http://127.0.0.1:{server.port}/{html_file.name}")
            findings = run_axe(page, html_file.name)
            blocking = [f for f in findings if f.impact in ("critical", "serious")]
            assert not blocking, f"{html_file.name}: " + "; ".join(f"{f.rule_id} ({f.impact})" for f in blocking)
            assert ada_score(findings) >= 90, f"{html_file.name} scored {ada_score(findings)}"
        page.close()
    finally:
        server.stop()


def test_public_pages_say_the_things_that_keep_us_honest(settings):
    db = Database(settings.database_path)
    client = TestClient(create_app(settings, db))

    bot = client.get("/bot").text
    assert "robots.txt" in bot and "ComplianceEngineBot" in bot
    assert "Disallow: /" in bot                      # tells people how to block us
    assert "never attempts to log in" in bot.lower()

    terms = client.get("/terms").text.lower()
    assert "not a law firm" in terms and "no legal advice" in terms
    assert "no one can guarantee" in terms           # the claim that gets this industry fined
    assert "overlay" in terms                        # we say plainly that we are not one

    privacy = client.get("/privacy").text.lower()
    assert "unsubscribe" in privacy and "delete" in privacy
    assert "we do not sell" in privacy and "train models" in privacy


def test_the_agreement_carries_the_clauses_that_cap_exposure(settings):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="x.example", url="https://x.example/", source="t")
    deal = open_or_create_deal(db, lead_id, Package.ADA, 149000, "usd")
    text = TestClient(create_app(settings, db)).get(f"/agreement/{deal['id']}").text.lower()

    for clause in (
        "do not represent, warrant, or guarantee",   # no compliance guarantee
        "not a law firm",                            # no legal advice
        "sole and exclusive remedy",                 # refund is the cap
        "limited to the fee you paid",               # liability cap
        "indemnify",
        "binding individual arbitration",
        "waive any right to a jury trial",
        "class or\nrepresentative action",           # class action waiver (wrapped in source)
        "governed by the laws",
    ):
        assert clause.replace("\n", " ") in text.replace("\n", " "), clause
