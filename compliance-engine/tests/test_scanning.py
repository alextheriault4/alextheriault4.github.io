from __future__ import annotations

from engine.db import Database
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site


def test_bad_site_scores_low_and_finds_contact(bad_site, settings, browser):
    result = scan_site(bad_site.url, settings, browser)
    assert result.error is None
    rules = {f.rule_id for f in result.findings}
    assert {"image-alt", "html-has-lang", "color-contrast", "skip-link", "focus-visible", "generic-link-text"} <= rules
    assert {"robots-missing", "structured-data-missing", "meta-description-missing", "title-weak", "h1-missing", "llms-txt-missing"} <= rules
    assert result.ada_score < 50
    assert result.aiseo_score < 40
    assert result.contact_email == "frontdesk@springfielddental.example"
    assert "bookings@gmail.com" in result.all_emails
    assert len(result.pages) >= 3  # home + contact + about (priority paths first)

    db = Database(":memory:")
    lead_id, _ = db.upsert_lead(domain=result.domain, url=bad_site.url, category="dentist", region="CA", source="test")
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    scan = db.latest_scan(lead_id)
    assert scan["exposure"]["ada_low_cents"] > 0 and scan["exposure"]["unruh_applies"] is True
    assert db.get_lead(lead_id)["contact_email"] == "frontdesk@springfielddental.example"
    assert db.get_lead(lead_id)["business_name"]  # guessed from title/domain
    assert classify_after_scan(db, settings, lead_id, scan_id) == "scanned"
    assert len(db.findings_for_scan(scan_id)) == len(result.findings)
    assert (settings.workdir / "snapshots" / result.domain).exists()  # lead domain == scanned host here


def test_good_site_is_clean(good_site, settings, browser):
    result = scan_site(good_site.url, settings, browser)
    assert result.error is None, result.error
    rules = {f.rule_id for f in result.findings}
    assert "image-alt" not in rules and "structured-data-missing" not in rules and "robots-missing" not in rules
    assert result.ada_score >= 90, (result.ada_score, sorted(rules))
    assert result.aiseo_score >= 85, (result.aiseo_score, sorted(rules))
    assert result.contact_email == "office@riversideplumbing.example"
    db = Database(":memory:")
    lead_id, _ = db.upsert_lead(domain=result.domain, url=good_site.url, source="test")
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    assert classify_after_scan(db, settings, lead_id, scan_id) == "clean"
