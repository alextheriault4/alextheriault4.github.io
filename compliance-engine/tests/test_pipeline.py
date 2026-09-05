"""End-to-end dry run: scan → draft → send (console) → replies → negotiation → checkout → paid."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.db import Database
from engine.deals.checkout import mark_paid
from engine.inbox.handle import process_inbound
from engine.inbox.negotiate import min_allowed_cents
from engine.inbox.provider import ConsoleProvider
from engine.llm import FakeLLM
from engine.outreach.compose import compose_initial
from engine.outreach.sequence import deliver_queued, schedule_followups
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site

MONDAY_NOON_UTC = datetime(2026, 9, 7, 16, 0, tzinfo=timezone.utc)  # 12:00 in America/New_York


@pytest.fixture
def scanned_lead(bad_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url, business_name="Springfield Family Dental",
                                category="dentist", city="Springfield", region="IL", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    assert classify_after_scan(db, settings, lead_id, scan_id) == "scanned"
    return db, lead_id


def _reply(provider, db, lead_id, text):
    token = db.thread_for_lead(lead_id)[0]["thread_token"]
    provider.simulate_reply(thread_token=token, from_addr=db.get_lead(lead_id)["contact_email"], text=text)


def test_happy_path_to_paid(scanned_lead, settings):
    db, lead_id = scanned_lead
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)

    msg_id = compose_initial(db, settings, llm, lead_id)
    msg = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
    assert msg["status"] == "queued", msg["lint"]
    assert "unsubscribe" in msg["body_text"].lower() and settings.company.postal_address in msg["body_text"]
    assert "estimate" in msg["body_text"].lower()
    assert db.get_lead(lead_id)["status"] == "queued"

    stats = deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    assert stats["sent"] == 1, stats
    lead = db.get_lead(lead_id)
    assert lead["status"] == "contacted" and lead["next_action_at"]
    assert list((settings.workdir / "outbox").glob("*.eml"))

    # Prospect asks a question → engaged, reply queued
    _reply(provider, db, lead_id, "Interesting. What exactly would you change on the site? Do you need our login?")
    stats = process_inbound(db, settings, llm, provider)
    assert stats.get("question") == 1, stats
    assert db.get_lead(lead_id)["status"] == "engaged"
    assert db.get_lead(lead_id)["next_action_at"] is None  # follow-ups stop once they reply
    out = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    assert out[-1]["kind"] == "reply" and out[-1]["status"] == "queued", out[-1]["lint"]

    # Lowball → clamped to floor, deal proposed at floor
    _reply(provider, db, lead_id, "Can you do it for $300?")
    stats = process_inbound(db, settings, llm, provider)
    assert stats.get("objection_price") == 1
    deal = db.open_deal(lead_id)
    assert deal["status"] == "proposed"
    assert deal["price_cents"] == min_allowed_cents(settings, settings.pricing.bundle_cents)
    assert deal["price_cents"] >= settings.pricing.floor_cents

    # Acceptance → checkout link + checkout email queued
    _reply(provider, db, lead_id, "Ok, go ahead and send the link")
    stats = process_inbound(db, settings, llm, provider)
    assert stats.get("accept") == 1
    deal = db.open_deal(lead_id)
    assert deal["status"] == "checkout_sent" and deal["checkout_url"].endswith(f"/pay/{deal['id']}")
    assert db.get_lead(lead_id)["status"] == "accepted"
    kinds = [m["kind"] for m in db.thread_for_lead(lead_id) if m["direction"] == "out" and m["status"] == "queued"]
    assert "checkout" in kinds and "reply" in kinds
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC + timedelta(hours=1))
    assert not db.query("SELECT 1 FROM messages WHERE status='queued'")

    mark_paid(db, settings, deal["id"], payment_intent="pi_test", amount_total_cents=deal["price_cents"] + 5000, tax_cents=5000)
    assert db.get_lead(lead_id)["status"] == "paid"
    kinds = {r["kind"] for r in db.query("SELECT kind FROM ledger WHERE deal_id=?", (deal["id"],))}
    assert kinds == {"charge", "sales_tax", "processing_fee"}


def test_unsubscribe_and_bounce_suppress_and_stop_followups(scanned_lead, settings):
    db, lead_id = scanned_lead
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    _reply(provider, db, lead_id, "Please remove me from your list. Unsubscribe.")
    process_inbound(db, settings, llm, provider)
    lead = db.get_lead(lead_id)
    assert lead["status"] == "unsubscribed"
    assert db.is_suppressed(lead["contact_email"])
    # Nothing further ever goes out to them, even if something gets queued.
    assert compose_initial(db, settings, llm, lead_id) is None
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=30)) == 0


def test_followups_are_scheduled_then_stop(scanned_lead, settings):
    db, lead_id = scanned_lead
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=1)) == 0
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=3, minutes=1)) == 1
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC + timedelta(days=3, hours=1))
    assert db.get_lead(lead_id)["followups_sent"] == 1
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=10, hours=1)) == 1
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC + timedelta(days=10, hours=2))
    lead = db.get_lead(lead_id)
    assert lead["followups_sent"] == 2 and lead["next_action_at"] is None
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=60)) == 0
    outs = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    assert [m["kind"] for m in outs] == ["initial", "followup", "followup"]
    assert all(m["status"] == "sent" for m in outs)


def test_send_window_and_daily_cap(scanned_lead, settings):
    db, lead_id = scanned_lead
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    saturday = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    assert deliver_queued(db, settings, provider, now=saturday)["skipped"] == 1
    settings.outreach.daily_send_cap = 0
    assert deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)["skipped"] == 1
    settings.outreach.daily_send_cap = 40
    db.set_kv("paused", "1")
    assert deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)["sent"] == 0
    db.set_kv("paused", "0")
    assert deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)["sent"] == 1


def test_hostile_reply_stands_down_without_asking_a_human(scanned_lead, settings):
    """Angry or legal-sounding replies get one apology and permanent removal, not an argument."""
    db, lead_id = scanned_lead
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    _reply(provider, db, lead_id, "This is a scam and I am forwarding it to my attorney.")
    stats = process_inbound(db, settings, llm, provider)
    assert stats.get("hostile") == 1, stats

    lead = db.get_lead(lead_id)
    assert lead["status"] == "unsubscribed"
    assert db.is_suppressed(lead["contact_email"])
    # Exactly one short, non-argumentative reply, and nothing about price or lawsuits.
    out = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    stand_down = out[-1]
    assert stand_down["status"] == "queued" and "sorry" in stand_down["body_text"].lower()
    assert "$" not in stand_down["body_text"].split("\n—\n")[0]
    # Nothing is waiting on a human.
    assert not db.leads_by_status("needs_human")
    assert db.query("SELECT 1 FROM events WHERE kind='auto_resolved'")
    assert db.notices()

    # Follow-ups can never resume for this address.
    assert schedule_followups(db, settings, now=MONDAY_NOON_UTC + timedelta(days=30)) == 0
    assert compose_initial(db, settings, llm, lead_id) is None


def test_hostile_reply_escalates_when_autopilot_is_off(scanned_lead, settings):
    db, lead_id = scanned_lead
    settings.autopilot.enabled = False
    llm = FakeLLM()
    provider = ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    _reply(provider, db, lead_id, "This is a scam and I am forwarding it to my attorney.")
    process_inbound(db, settings, llm, provider)
    lead = db.get_lead(lead_id)
    assert lead["status"] == "needs_human" and lead["needs_human_reason"]
    assert not db.query("SELECT 1 FROM messages WHERE direction='out' AND status='queued'")
