from __future__ import annotations

import json
import shutil
from pathlib import Path

import httpx

from engine.db import Database
from engine.deals.checkout import mark_paid, open_or_create_deal
from engine.finance import ledger
from engine.fixing.apply import apply_wordpress, patch_wp_content
from engine.fixing.build import build_bundle
from engine.fixing.verify import start_fix, verify_deal
from engine.llm import FakeLLM
from engine.models import Package
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site
from tests.conftest import SiteServer


def _paid_deal(db, settings, lead_id, package=Package.BUNDLE):
    deal = open_or_create_deal(db, lead_id, package, settings.pricing.bundle_cents, "usd")
    mark_paid(db, settings, deal["id"], payment_intent="pi_x", amount_total_cents=deal["price_cents"])
    return deal["id"]


def test_bundle_fixes_the_bad_site_and_verification_passes(bad_site, settings, browser, tmp_path):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url, business_name="Springfield Family Dental",
                                category="dentist", city="Springfield", region="IL", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    classify_after_scan(db, settings, lead_id, scan_id)
    db.insert("messages", {"lead_id": lead_id, "thread_token": "tok123", "direction": "out", "kind": "initial", "subject": "x",
                           "body_text": "x", "to_addr": "a@b.c", "from_addr": "x@y.z", "message_id": "<tok123.1@x>",
                           "status": "sent", "created_at": "2026-01-01T00:00:00+00:00"})
    deal_id = _paid_deal(db, settings, lead_id)

    llm = FakeLLM()
    fix_id = start_fix(db, settings, llm, deal_id)
    fix = db.one("SELECT * FROM fixes WHERE id=?", (fix_id,))
    assert fix["status"] == "delivered", fix["error"]
    root = Path(fix["bundle_path"])
    assert (root / "pages" / "index.html").exists() and (root / "llms.txt").exists() and (root / "robots.txt").exists()
    assert (root / "CHANGES.md").exists() and (root / "INSTRUCTIONS.md").exists()
    summary = json.loads(fix["summary"])
    rules = summary["changes_by_rule"]
    for r in ("image-alt", "html-has-lang", "structured-data-missing", "meta-description-missing", "skip-link", "frame-title", "label", "button-name"):
        assert r in rules, (r, rules)
    assert db.get_lead(lead_id)["status"] == "delivered"
    delivery = db.one("SELECT * FROM messages WHERE kind='delivery' AND lead_id=?", (lead_id,))
    assert delivery and "/bundle/tok123" in delivery["body_text"]

    # "Client deploys the bundle": serve pages/ plus the site files, then rescan.
    site = tmp_path / "deployed"
    shutil.copytree(root / "pages", site)
    for f in ("robots.txt", "llms.txt", "sitemap.xml", "accessibility.css"):
        shutil.copy(root / f, site / f)
    for p in site.glob("*.orig"):
        p.unlink()
    server = SiteServer(site)
    try:
        cmp = verify_deal(db, settings, browser, deal_id, url=server.url)
    finally:
        server.stop()
    assert cmp["after"]["ada"] >= cmp["before"]["ada"] + 15, cmp
    assert cmp["after"]["aiseo"] >= cmp["before"]["aiseo"] + 15, cmp
    assert cmp["verified"], cmp
    assert db.get_lead(lead_id)["status"] == "verified"
    assert db.one("SELECT * FROM deals WHERE id=?", (deal_id,))["status"] == "verified"
    assert db.one("SELECT 1 FROM messages WHERE kind='delivery' AND subject LIKE 'Before/after%'")

    s = ledger.summary(db)
    assert s["paid_deals"] == 1 and s["gross_cents"] == settings.pricing.bundle_cents and s["net_cents"] < s["gross_cents"]
    assert "client_domain" in ledger.export_csv(db).splitlines()[0]


def test_wordpress_content_patch_and_rest_apply(settings, tmp_path):
    html = '<p>Hi</p><img src="https://x.example/wp-content/uploads/team.jpg"><iframe src="https://maps.google.com/e"></iframe><a href="/services/">click here</a>'
    out, n = patch_wp_content(html, {"https://x.example/wp-content/uploads/team.jpg": "Our team"})
    assert n == 3 and 'alt="Our team"' in out and 'title="Embedded content"' in out and 'aria-label="click here: services"' in out

    db = Database(":memory:")
    lead_id, _ = db.upsert_lead(domain="x.example", url="https://x.example/", platform="wordpress", source="t")
    db.set_kv(f"lead:{lead_id}:wp_user", "admin")
    db.set_kv(f"lead:{lead_id}:wp_app_password", "abcd efgh")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["Authorization"].startswith("Basic ")
        if request.method == "GET" and request.url.path.endswith("/pages"):
            return httpx.Response(200, json=[{"id": 7, "content": {"raw": html}}])
        if request.method == "GET" and request.url.path.endswith("/posts"):
            return httpx.Response(200, json=[])
        if request.method == "POST":
            body = json.loads(request.content)
            assert 'alt="Our team"' in body["content"]
            return httpx.Response(200, json={"id": 7})
        return httpx.Response(404)

    from engine.fixing.build import Bundle

    root = tmp_path / "b"
    (root / "pages").mkdir(parents=True)
    (root / "pages" / "index.html").write_text('<html><body><img src="https://x.example/wp-content/uploads/team.jpg" alt="Our team"></body></html>')
    bundle = Bundle(root=root, pages=[{"url": "https://x.example/", "path": "index.html"}], strategy="wordpress_rest",
                    site_files={"llms.txt": "# X", "accessibility.css": "a{}", "robots.txt": "User-agent: *\n"}, header_snippet="<meta>")
    res = apply_wordpress(db, db.get_lead(lead_id), bundle, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert res["applied"] and res["updated"] == [{"type": "pages", "id": 7, "changes": 3}]
    assert ("POST", "/wp-json/wp/v2/pages/7") in calls
    assert (root / "mu-plugin" / "compliance-engine.php").read_text().startswith("<?php")
