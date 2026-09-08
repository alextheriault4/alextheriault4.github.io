"""We only pitch a site we could genuinely change once they say yes."""
from __future__ import annotations

from engine.db import Database
from engine.fixability import (Fixability, assess, detect_host, eligible_to_pitch,
                               guess_github_repo, wordpress_rest_available)
from engine.models import LeadStatus
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site


def test_github_pages_is_recognised_from_headers():
    assert detect_host({"Server": "GitHub.com"}) == "github_pages"
    assert detect_host({"x-github-request-id": "abc"}) == "github_pages"
    assert detect_host({"server": "nginx"}) is None
    assert detect_host(None) is None


def test_user_page_repo_is_implied_by_the_domain():
    assert guess_github_repo("alex.github.io", "") == "alex/alex.github.io"
    assert guess_github_repo("www.alex.github.io", "") == "alex/alex.github.io"
    # A custom domain hides the repo, but sites very often link to it.
    assert guess_github_repo("dental.example",
                             '<a href="https://github.com/acme/site.git">source</a>') == "acme/site"
    # GitHub's own marketing links are not somebody's repository.
    assert guess_github_repo("dental.example", '<a href="https://github.com/pricing/x">') is None
    assert guess_github_repo("dental.example", "<p>no link here</p>") is None


def test_wordpress_rest_probe_only_accepts_a_real_api():
    assert wordpress_rest_available(lambda u: (True, '{"namespaces":["wp/v2"]}'), "https://x.example")
    assert not wordpress_rest_available(lambda u: (True, "<html>404</html>"), "https://x.example")
    assert not wordpress_rest_available(lambda u: (False, None), "https://x.example")
    assert not wordpress_rest_available(lambda u: (True, '{"other":1}'), "https://x.example")

    def boom(url):
        raise RuntimeError("network")

    assert not wordpress_rest_available(boom, "https://x.example")  # a probe never breaks a scan


def test_each_host_lands_in_the_right_tier():
    gh = assess(domain="alex.github.io", url="https://alex.github.io/", platform="static",
                headers={"server": "GitHub.com"}, home_html="")
    assert (gh.tier, gh.channel, gh.repo) == ("direct", "github_pr", "alex/alex.github.io")
    assert gh.can_apply

    wp = assess(domain="d.example", url="https://d.example/", platform="wordpress",
                headers={"server": "nginx"}, home_html="", wp_rest=True)
    assert (wp.tier, wp.channel) == ("direct", "wordpress_rest")

    wp_closed = assess(domain="d.example", url="https://d.example/", platform="wordpress",
                       headers={"server": "nginx"}, home_html="", wp_rest=False)
    assert (wp_closed.tier, wp_closed.channel) == ("assisted", "header_snippet")

    wix = assess(domain="d.example", url="https://d.example/", platform="wix",
                 headers={"server": "Pepyaka"}, home_html="")
    assert wix.tier == "assisted" and not wix.can_apply

    nothing = assess(domain="d.example", url="https://d.example/", platform="",
                     headers={"server": "nginx"}, home_html="")
    assert nothing.tier == "unknown" and nothing.channel == "none"


def test_a_cdn_is_not_a_host_we_can_edit():
    """Most of the web sits behind Cloudflare, Wix and Squarespace sites included. Reading
    ``cf-ray`` as "this is Cloudflare Pages" would have us promise changes we cannot make."""
    cdn_headers = {"server": "cloudflare", "cf-ray": "8b2f00000000-EWR"}
    assert detect_host(cdn_headers) is None

    wix = assess(domain="d.example", url="https://d.example/", platform="wix",
                 headers=cdn_headers, home_html="")
    assert wix.tier == "assisted" and not wix.can_apply

    plain = assess(domain="d.example", url="https://d.example/", platform="static_or_custom",
                   headers=cdn_headers, home_html="")
    assert plain.tier == "unknown", "behind a CDN with no other signal, we have no way in"

    # A real Cloudflare Pages site announces itself in the hostname.
    real = assess(domain="shop.pages.dev", url="https://shop.pages.dev/", platform="static_or_custom",
                  headers=cdn_headers, home_html="")
    assert real.tier == "direct" and real.channel == "github_pr"


def test_the_gate_states_why_it_refused():
    direct = Fixability("direct", "github_pr", "pull request")
    assisted = Fixability("assisted", "header_snippet", "Wix exposes no editing API")

    assert eligible_to_pitch(direct, require_direct=True)[0]
    ok, why = eligible_to_pitch(assisted, require_direct=True)
    assert not ok and "Wix exposes no editing API" in why
    ok, why = eligible_to_pitch(None, require_direct=True)
    assert not ok and "never assessed" in why
    # With the gate off - for a sales channel we drive by hand - everything is eligible.
    assert eligible_to_pitch(assisted, require_direct=False)[0]
    assert eligible_to_pitch(None, require_direct=False)[0]


def test_a_scan_records_how_we_would_apply_the_fix(bad_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url,
                                business_name="Springfield Family Dental", source="test")
    result = scan_site(bad_site.url, settings, browser)
    assert result.fixability is not None and result.fixability.can_apply

    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    lead = db.get_lead(lead_id)
    assert lead["fixability"] == "direct" and lead["fix_channel"] == "github_pr"
    assert lead["fix_detail"]
    assert classify_after_scan(db, settings, lead_id, scan_id) == LeadStatus.SCANNED


def test_a_site_we_cannot_change_is_never_emailed(unhostable_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="nohost.example", url=unhostable_site.url,
                                business_name="No Way In Ltd", source="test")
    result = scan_site(unhostable_site.url, settings, browser)
    assert result.fixability.tier == "unknown"

    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    assert classify_after_scan(db, settings, lead_id, scan_id) == LeadStatus.NOT_FIXABLE

    lead = db.get_lead(lead_id)
    assert lead["status"] == LeadStatus.NOT_FIXABLE
    assert "could not change" in (lead["needs_human_reason"] or "")
    kinds = [e["kind"] for e in db.query("SELECT kind FROM events WHERE lead_id=?", (lead_id,))]
    assert "not_fixable" in kinds
    # And nothing was drafted for them.
    assert db.query("SELECT id FROM messages WHERE lead_id=?", (lead_id,)) == []
