from __future__ import annotations

from engine.db import Database
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site
from engine.standards import ALL_CHECKS, BY_ID


def statuses(result) -> dict[str, str]:
    return {r.check_id: r.status for r in result.results}


def test_bad_site_scores_low_and_finds_contact(bad_site, settings, browser):
    result = scan_site(bad_site.url, settings, browser)
    assert result.error is None
    st = statuses(result)

    # The failures a real audit of this page would raise.
    for check_id in ("image-alt", "color-contrast", "page-language", "page-title", "skip-link",
                     "focus-visible", "link-purpose", "form-labels", "button-name", "frame-title",
                     "structured-data", "meta-description", "title-tag", "h1", "llms-txt",
                     "robots-exists", "sitemap", "content-depth", "accessibility-statement"):
        assert st.get(check_id) == "fail", (check_id, st.get(check_id))

    # Scores are a real fraction of applicable checks, not an arbitrary penalty.
    assert result.ada.percent < 60 and result.seo.percent < 60
    assert result.ada.weight_earned < result.ada.weight_applicable
    assert result.ada.passed + result.ada.failed == len([r for r in result.results
                                                         if r.check.area == "ada" and r.status in ("pass", "fail")])
    assert result.ada.band in ("critical", "poor")

    # Manual checks are surfaced but never scored, so the number stays honest.
    manual_ids = {c.id for c in ALL_CHECKS if c.detection == "manual"}
    scored_ids = {r.check_id for r in result.results if r.status in ("pass", "fail")}
    assert not (manual_ids & scored_ids)

    assert result.contact_email == "frontdesk@springfielddental.example"
    assert "bookings@gmail.com" in result.all_emails
    assert len(result.pages) >= 3

    db = Database(":memory:")
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url,
                                category="dentist", region="CA", source="test")
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    scan = db.latest_scan(lead_id)
    assert scan["ada_score"] == result.ada.percent
    assert scan["exposure"]["ada_low_cents"] > 0 and scan["exposure"]["unruh_applies"] is True
    assert scan["ada_summary"]["categories"] and scan["ada_summary"]["band"]
    assert db.get_lead(lead_id)["contact_email"] == "frontdesk@springfielddental.example"
    assert classify_after_scan(db, settings, lead_id, scan_id) == "scanned"
    assert len(db.findings_for_scan(scan_id)) == len(result.results)
    assert (settings.workdir / "snapshots" / "springfielddental.example").exists()


def test_reference_site_scores_full_marks(good_site, settings, browser):
    """The fixture is a worked example of the standard, so it should score 100 on both."""
    result = scan_site(good_site.url, settings, browser)
    assert result.error is None, result.error
    assert result.ada.percent == 100, [f.check_id for f in result.ada.failures]
    assert result.seo.percent == 100, [f.check_id for f in result.seo.failures]
    assert result.ada.band == "excellent"
    assert result.contact_email == "office@riversideplumbing.example"

    db = Database(":memory:")
    lead_id, _ = db.upsert_lead(domain="riversideplumbing.example", url=good_site.url, source="test")
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    assert classify_after_scan(db, settings, lead_id, scan_id) == "clean"


def test_every_check_is_well_formed():
    """The registry is the contract for the scanner, the fixer and the report."""
    seen = set()
    for c in ALL_CHECKS:
        assert c.id not in seen, f"duplicate check id {c.id}"
        seen.add(c.id)
        assert c.area in ("ada", "seo")
        assert 1 <= c.weight <= 10
        assert c.detection in ("auto", "heuristic", "manual")
        assert c.why.strip() and c.fix.strip() and c.standard.strip()
        assert 10 <= len(c.title) <= 70, c.id
        # A manual check can never be auto-fixed, by definition.
        assert not (c.detection == "manual" and c.auto_fixable), c.id
    assert len(ALL_CHECKS) >= 60
    assert BY_ID["image-alt"].level == "A" and BY_ID["color-contrast"].level == "AA"


def test_axe_rule_mapping_is_unambiguous():
    """One axe rule must not decide two different checks."""
    from engine.standards import AXE_RULE_TO_CHECK

    counts: dict[str, list[str]] = {}
    for c in ALL_CHECKS:
        for rule in c.axe_rules:
            counts.setdefault(rule, []).append(c.id)
    dupes = {r: ids for r, ids in counts.items() if len(ids) > 1}
    assert not dupes, dupes
    assert AXE_RULE_TO_CHECK["color-contrast"] == "color-contrast"
    assert AXE_RULE_TO_CHECK["input-image-alt"] == "image-alt"


def test_standards_document_matches_the_registry():
    """STANDARDS.md is generated, so it can never describe checks the code doesn't run."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "tools/generate_standards.py", "--check"],
                            cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scoring_arithmetic_is_a_real_fraction():
    from engine.standards import CheckResult, score

    results = [
        CheckResult("image-alt", "pass"),          # weight 10
        CheckResult("color-contrast", "fail"),     # weight 10
        CheckResult("page-language", "pass"),      # weight 7
        CheckResult("video-captions", "fail"),     # manual: must be ignored entirely
        CheckResult("frame-title", "not_applicable"),
        CheckResult("keyboard-access", "needs_review"),
    ]
    card = score(results, "ada")
    # 17 earned of 27 applicable; the manual and undecided checks are in neither half.
    assert card.weight_earned == 17 and card.weight_applicable == 27
    assert card.percent == round(100 * 17 / 27)
    assert card.passed == 2 and card.failed == 1
    assert "video-captions" not in {r.check_id for r in card.failures}

    # A site where everything applicable passes scores 100, not "100 minus penalties".
    perfect = score([CheckResult("image-alt", "pass")], "ada")
    assert perfect.percent == 100 and perfect.band == "excellent"
