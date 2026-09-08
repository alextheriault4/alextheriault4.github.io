"""After payment, getting access has to be the easiest thing the customer does all week."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import Fernet

from engine import onboarding
from engine.db import Database, utcnow
from engine.fixing.apply import apply_github
from engine.fixing.build import Bundle


def paid_lead(db, settings, **lead_fields):
    """A lead that has paid for the care plan, the way the pipeline creates one."""
    from engine import plans
    from engine.deals.checkout import mark_paid, open_or_create_deal

    fields = {"domain": "acme.example", "url": "https://acme.example/", "business_name": "Acme",
              "contact_email": "owner@acme.example", "source": "test", "fixability": "direct",
              "fix_channel": "github_pr"}
    fields.update(lead_fields)
    lead_id, _ = db.upsert_lead(**fields)
    db.insert("messages", {"lead_id": lead_id, "thread_token": "tok1", "direction": "out",
                           "kind": "outreach", "subject": "s", "body_text": "b",
                           "to_addr": "owner@acme.example", "from_addr": settings.company.from_email,
                           "message_id": "<a@b>", "status": "sent", "created_at": utcnow()})
    plan = plans.catalogue(settings)["care"]
    deal = open_or_create_deal(db, lead_id, plan, plan.setup_cents, plan.monthly_cents, "usd")
    mark_paid(db, settings, deal["id"], payment_intent="pi_1", amount_total_cents=deal["price_cents"])
    return lead_id, db.one("SELECT * FROM deals WHERE id=?", (deal["id"],))


def test_a_repository_address_is_accepted_in_any_shape():
    for raw in ("https://github.com/acme/site", "https://github.com/acme/site.git",
                "git@github.com:acme/site.git", "acme/site", "  acme/site  "):
        assert onboarding.normalise_repo(raw) == "acme/site"
    assert onboarding.normalise_repo("my website") is None
    assert onboarding.normalise_repo("") is None


def test_a_known_repository_means_nothing_to_do(settings):
    db = Database(settings.database_path)
    lead_id, deal = paid_lead(db, settings, repo="acme/site")
    db.set_kv(f"lead:{lead_id}:github_repo", "acme/site")
    state = onboarding.access_state(db, settings, db.get_lead(lead_id))
    assert state.ready and not state.needs_form and state.repo == "acme/site"

    msg = db.one("SELECT * FROM messages WHERE lead_id=? AND kind='welcome'", (lead_id,))
    assert msg is not None
    assert "Merge" in msg["body_text"]
    # The monthly promise is part of what they bought, so it is restated on day one.
    assert "no extra cost" in msg["body_text"]
    # Sending twice is a bug, not a feature.
    assert onboarding.queue_welcome(db, settings, deal["id"]) is None
    assert len(db.query("SELECT id FROM messages WHERE lead_id=? AND kind='welcome'", (lead_id,))) == 1


def test_an_unknown_repository_is_the_only_thing_we_ask_for(settings):
    db = Database(settings.database_path)
    lead_id, deal = paid_lead(db, settings)
    state = onboarding.access_state(db, settings, db.get_lead(lead_id))
    assert state.needs_form and not state.ready

    msg = db.one("SELECT * FROM messages WHERE lead_id=? AND kind='welcome'", (lead_id,))
    assert onboarding.setup_url(settings, onboarding.setup_token(db, lead_id)) in msg["body_text"]
    assert "no password" in msg["body_text"]

    ok, repo = onboarding.grant_github(db, settings, lead_id, "https://github.com/acme/site")
    assert ok and repo == "acme/site"
    lead = db.get_lead(lead_id)
    assert lead["access_granted_at"]
    assert db.get_kv(f"lead:{lead_id}:github_repo") == "acme/site"
    assert onboarding.access_state(db, settings, lead).ready

    ok, why = onboarding.grant_github(db, settings, lead_id, "not a repo")
    assert not ok and "GitHub" in why


def test_a_wordpress_password_is_four_clicks_and_stored_encrypted(settings):
    settings.secrets_key = Fernet.generate_key().decode()
    db = Database(settings.database_path)
    lead_id, _ = paid_lead(db, settings, platform="wordpress", fix_channel="wordpress_rest")
    state = onboarding.access_state(db, settings, db.get_lead(lead_id))
    assert state.needs_form and len(state.steps) == 4
    assert any("revoke" in s for s in state.steps)

    ok, _ = onboarding.grant_wordpress(db, settings, lead_id, site_url="https://acme.example/",
                                       username="admin", app_password="abcd efgh ijkl")
    assert ok
    stored = db.get_kv(f"lead:{lead_id}:wp_app_password")
    assert "abcd" not in stored                       # never at rest in the clear
    assert db.get_lead(lead_id)["access_granted_at"]
    assert onboarding.access_state(db, settings, db.get_lead(lead_id)).ready

    ok, why = onboarding.grant_wordpress(db, settings, lead_id, site_url="", username="", app_password="")
    assert not ok and "username" in why


def test_credentials_are_refused_when_they_could_not_be_encrypted(settings):
    settings.secrets_key = ""
    db = Database(settings.database_path)
    lead_id, _ = paid_lead(db, settings, platform="wordpress", fix_channel="wordpress_rest")
    ok, why = onboarding.grant_wordpress(db, settings, lead_id, site_url="https://acme.example/",
                                         username="admin", app_password="secret")
    assert not ok and "securely" in why
    assert db.get_kv(f"lead:{lead_id}:wp_app_password") is None


def test_work_starts_at_once_when_nothing_is_needed_and_waits_when_it_is(settings):
    db = Database(settings.database_path)
    ready_lead, ready_deal = paid_lead(db, settings, repo="acme/site")
    db.set_kv(f"lead:{ready_lead}:github_repo", "acme/site")
    waiting_lead, waiting_deal = paid_lead(db, settings, domain="b.example", url="https://b.example/",
                                           contact_email="o@b.example")

    ready_now = onboarding.deals_ready_to_fix(db, settings)
    assert ready_deal["id"] in ready_now and waiting_deal["id"] not in ready_now

    # But we never hold someone's work hostage to a form they didn't fill in.
    later = datetime.now(timezone.utc) + timedelta(days=onboarding.ACCESS_WAIT_DAYS, hours=1)
    assert waiting_deal["id"] in onboarding.deals_ready_to_fix(db, settings, now=later)
    assert any("no access after" in n["detail"].get("headline", "")
               for n in [{"detail": json.loads(e["detail"])} for e in
                         db.query("SELECT detail FROM events WHERE kind='notice'")])


def test_we_chase_the_missing_piece_exactly_once(settings):
    db = Database(settings.database_path)
    lead_id, _ = paid_lead(db, settings)
    now = datetime.now(timezone.utc) + timedelta(days=onboarding.REMIND_AFTER_DAYS, hours=1)
    assert onboarding.chase_access(db, settings, now) == 1
    assert onboarding.chase_access(db, settings, now) == 0   # never twice
    msg = db.one("SELECT * FROM messages WHERE lead_id=? AND kind='access_reminder'", (lead_id,))
    assert "finished files with instructions" in msg["body_text"]

    # Once they've granted it, there is nothing left to chase.
    db2 = Database(settings.database_path)
    onboarding.grant_github(db2, settings, lead_id, "acme/site")
    assert onboarding.chase_access(db2, settings, now + timedelta(days=5)) == 0


def test_the_setup_page_takes_the_repository_and_says_thank_you(settings):
    from fastapi.testclient import TestClient

    from engine.dashboard.app import create_app

    db = Database(settings.database_path)
    lead_id, _ = paid_lead(db, settings)
    token = onboarding.setup_token(db, lead_id)
    client = TestClient(create_app(settings, db))

    page = client.get(f"/setup/{token}")
    assert page.status_code == 200
    assert "repository" in page.text and 'name="repo"' in page.text

    bad = client.post(f"/setup/{token}", data={"repo": "nonsense"})
    assert "doesn&#39;t look like" in bad.text or "doesn't look like" in bad.text

    done = client.post(f"/setup/{token}", data={"repo": "https://github.com/acme/site"})
    assert done.status_code == 200 and "That's everything" in done.text.replace("&#39;", "'")
    assert db.get_kv(f"lead:{lead_id}:github_repo") == "acme/site"
    assert client.get("/setup/not-a-token").status_code == 404


def test_a_pull_request_is_opened_from_a_fork_when_we_cannot_push(settings, tmp_path):
    """The zero-credential path: fork, commit there, open the PR, they press Merge."""
    settings.secrets_key = Fernet.generate_key().decode()
    db = Database(settings.database_path)
    from engine.legal import SecretBox

    lead_id, _ = db.upsert_lead(domain="acme.example", url="https://acme.example/", source="t")
    db.set_kv(f"lead:{lead_id}:github_repo", "acme/site")
    db.set_secret("github_token", "ghp_x", SecretBox(settings.secrets_key))
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        seen.append((method, path))
        if method == "GET" and path == "/repos/acme/site":
            return httpx.Response(200, json={"default_branch": "main", "permissions": {"push": False}})
        if method == "POST" and path == "/repos/acme/site/forks":
            return httpx.Response(202, json={"full_name": "us/site"})
        if method == "GET" and path == "/repos/us/site":
            return httpx.Response(200, json={"size": 1})
        if method == "GET" and path == "/repos/us/site/branches":
            return httpx.Response(200, json=[{"name": "main"}])
        if method == "GET" and path == "/repos/us/site/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "abc123"}})
        if method == "POST" and path == "/repos/us/site/git/refs":
            return httpx.Response(201, json={})
        if method == "GET" and path.startswith("/repos/us/site/contents/"):
            return httpx.Response(404)
        if method == "PUT" and path.startswith("/repos/us/site/contents/"):
            return httpx.Response(201, json={})
        if method == "POST" and path == "/repos/acme/site/pulls":
            body = json.loads(request.content)
            assert body["head"].startswith("us:")  # the branch lives on our fork, not theirs
            assert body["base"] == "main"
            assert "until you merge" in body["body"]
            return httpx.Response(201, json={"html_url": "https://github.com/acme/site/pull/1"})
        raise AssertionError(f"unexpected call {method} {path}")

    root = tmp_path / "b"
    (root / "pages").mkdir(parents=True)
    (root / "pages" / "index.html").write_text("<html lang='en'></html>")
    (root / "CHANGES.md").write_text("# Changes")
    bundle = Bundle(root=root, pages=[{"url": "https://acme.example/", "path": "index.html"}],
                    strategy="github_pr", site_files={"llms.txt": "# Acme"}, header_snippet="")

    res = apply_github(db, settings, db.get_lead(lead_id), bundle,
                       client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert res["applied"] and res["pr_url"].endswith("/pull/1") and res["merge_needed"]
    assert ("POST", "/repos/acme/site/forks") in seen        # we never needed their permission
    assert not any(p.startswith("/repos/acme/site/contents/") for _, p in seen)  # nor wrote to their repo
    ev = db.query("SELECT detail FROM events WHERE kind='fix_applied'")
    assert json.loads(ev[0]["detail"])["via"] == "fork"
