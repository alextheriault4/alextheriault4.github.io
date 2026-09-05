"""The controls that exist to keep the operator out of court."""
from __future__ import annotations

import pytest

from engine.config import Settings
from engine.db import Database
from engine.legal import CrawlPolicy, SecretBox, check_email_body, check_lead, safe_to_fetch
from engine.outreach.compliance import lint_email

FOOTER = "\n\nReply unsubscribe to stop.\nTest Co LLC, 1 Test St, Testville, TS 00000"


def lead(**kw):
    base = {"domain": "example.com", "url": "https://example.com/", "country": "US", "region": "IL",
            "category": "dentist", "business_name": "Bright Smiles"}
    return {**base, **kw}


# --------------------------------------------------------------------------- contact policy

@pytest.mark.parametrize("overrides, expect", [
    ({}, True),
    ({"domain": "example.ca"}, False),                          # CASL territory
    ({"domain": "example.co.uk"}, False),
    ({"country": "CA"}, False),
    ({"region": "ON"}, False),                                  # not a US state
    ({"domain": "city.gov"}, False),
    ({"domain": "school.edu"}, False),
    ({"category": "lawyer"}, False),                            # most likely to sue over spam
    ({"category": "personal injury attorney"}, False),
    ({"business_name": "Smith & Sons Law Offices"}, False),
    ({"category": "cannabis dispensary"}, False),
    ({"category": "gun store"}, False),
    ({"contact_email": "legal@example.com"}, False),
    ({"contact_email": "info@example.com"}, True),
])
def test_contact_policy(overrides, expect, settings):
    assert bool(check_lead(lead(**overrides), settings)) is expect


def test_non_us_markers_in_page_text_are_refused(settings):
    text = "Acme Widgets Ltd, registered in England and Wales. VAT number 123456789."
    assert not check_lead(lead(), settings, page_text=text)
    assert check_lead(lead(), settings, page_text="Serving Springfield, Illinois since 1998.")


def test_policy_can_be_widened_deliberately(settings):
    """The gate is policy, not a hard-coded moral: turning it off is an explicit choice."""
    settings.legal.us_only = False
    settings.legal.excluded_categories = []
    assert check_lead(lead(domain="example.ca", country="CA", region="ON", category="lawyer"), settings)


# --------------------------------------------------------------------------- what we may say

@pytest.mark.parametrize("body", [
    "Your site violates the ADA and you are required by law to fix it.",
    "This is illegal and you are non-compliant with federal law.",
    "Our service makes you immune from accessibility lawsuits.",
    "You will be fined if you do not act.",
])
def test_legal_claims_are_refused(body):
    assert check_email_body(body), body


def test_lint_catches_legal_claims_end_to_end():
    r = lint_email(subject="A note about your site",
                   body_text="Your site violates the ADA. Estimate $1,490." + FOOTER,
                   allowed_cents=[149000], postal_address="1 Test St, Testville, TS 00000",
                   legal_name="Test Co LLC")
    assert not r.ok
    assert any("legal claim" in p for p in r.problems)


def test_honest_phrasing_passes():
    r = lint_email(subject="A few fixable issues on example.com",
                   body_text="An automated scan flagged 12 images with no alt text. Estimate $1,490." + FOOTER,
                   allowed_cents=[149000], postal_address="1 Test St, Testville, TS 00000",
                   legal_name="Test Co LLC")
    assert r.ok, r.problems


# --------------------------------------------------------------------------- crawling

def test_robots_txt_is_obeyed_including_crawl_delay(settings):
    policy = CrawlPolicy(settings)
    policy.load_robots("https://x.example", "User-agent: ComplianceEngineBot\nDisallow: /private\nCrawl-delay: 7\n")
    assert policy.allowed("https://x.example/about")
    assert not policy.allowed("https://x.example/private/page")
    assert policy._delays["https://x.example"] == 7.0


def test_blanket_disallow_blocks_us(settings):
    policy = CrawlPolicy(settings)
    policy.load_robots("https://x.example", "User-agent: *\nDisallow: /\n")
    assert not policy.allowed("https://x.example/")


def test_no_robots_txt_means_no_restriction(settings):
    policy = CrawlPolicy(settings)
    policy.load_robots("https://x.example", None)
    assert policy.allowed("https://x.example/anything")


def test_malformed_robots_txt_does_not_break_the_scan(settings):
    policy = CrawlPolicy(settings)
    policy.load_robots("https://x.example", "\x00 not really \n Disallow Disallow ::: \n")
    assert policy.allowed("https://x.example/")


@pytest.mark.parametrize("path, ok", [
    ("/about", True), ("/services/dental", True),
    ("/wp-login.php", False), ("/wp-admin/", False), ("/admin", False), ("/login", False),
    ("/checkout", False), ("/account/settings", False), ("/.env", False), ("/.git/config", False),
    ("/api/users", False),
])
def test_never_requests_sensitive_paths(path, ok):
    assert safe_to_fetch("https://x.example" + path) is ok


def test_user_agent_identifies_us_and_points_at_an_explanation(settings):
    ua = settings.scanning.user_agent_for("https://testco.example", "/bot")
    assert "ComplianceEngineBot" in ua and "https://testco.example/bot" in ua


# --------------------------------------------------------------------------- credentials

def test_credentials_are_encrypted_at_rest():
    from cryptography.fernet import Fernet

    db = Database(":memory:")
    box = SecretBox(Fernet.generate_key().decode())
    db.set_secret("lead:1:wp_app_password", "hunter2 hunter2", box)

    stored = db.get_kv("lead:1:wp_app_password")
    assert "hunter2" not in stored and stored.startswith("enc:v1:")
    assert db.get_secret("lead:1:wp_app_password", box) == "hunter2 hunter2"


def test_storing_a_credential_without_a_key_is_refused():
    db = Database(":memory:")
    with pytest.raises(RuntimeError, match="unencrypted"):
        db.set_secret("lead:1:wp_app_password", "hunter2", SecretBox(""))


def test_credentials_are_purged_after_the_job():
    from cryptography.fernet import Fernet

    db = Database(":memory:")
    box = SecretBox(Fernet.generate_key().decode())
    db.upsert_lead(domain="x.example", url="https://x.example/", source="t")
    db.set_secret("lead:1:wp_app_password", "hunter2", box)
    db.set_kv("lead:1:wp_user", "admin")

    assert db.purge_lead_credentials(1) == 1
    assert db.get_kv("lead:1:wp_app_password") is None
    assert db.get_kv("lead:1:wp_user") == "admin"  # non-secret context is kept


# --------------------------------------------------------------------------- go-live gate

def test_preflight_blocks_live_mode_until_the_basics_are_true(tmp_path):
    s = Settings(_env_file=None, mode="live", database_path=tmp_path / "e.db", workdir=tmp_path)
    problems = " ".join(s.preflight())
    assert "postal_address" in problems and "entity" in problems and "lawyer" in problems and "insurance" in problems
    # Every outbound gate is shut while preflight fails, even though mode is live.
    assert s.can_charge()[0] is False and "preflight" in s.can_charge()[1]
    assert s.can_apply_fixes()[0] is False

    s.company.postal_address = "1 Real St, Springfield, IL 62701"
    s.company.website = "https://realco.example"
    s.company.legal_name = "Real Co LLC"
    s.company.from_email = "alex@outreach.realco.example"
    s.legal.business_entity_formed = True
    s.legal.agreement_reviewed_by_lawyer = True
    s.legal.liability_insurance = True
    s.secrets_key = "x" * 44
    assert s.preflight() == []
    assert s.live_blocked_reason() is None
