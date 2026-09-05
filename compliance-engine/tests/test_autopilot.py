"""Every path that used to stop and ask a human now resolves itself.

The through-line of these tests: after each scenario, ``leads_by_status("needs_human")``
is empty and there is a notice on the record explaining what was done instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import autopilot, schemas
from engine.db import Database
from engine.deals.checkout import mark_paid, open_or_create_deal
from engine.inbox.handle import process_inbound
from engine.inbox.provider import ConsoleProvider
from engine.llm import FakeLLM, LLMCapacityError, LLMRefusal
from engine.models import Package
from engine.outreach.compose import compose_initial
from engine.outreach.sequence import deliver_queued
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site
from tests.test_pipeline import MONDAY_NOON_UTC


@pytest.fixture
def lead_ready(bad_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url,
                                business_name="Springfield Family Dental", category="dentist",
                                city="Springfield", region="IL", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    assert classify_after_scan(db, settings, lead_id, scan_id) == "scanned"
    return db, lead_id


def nobody_waiting(db) -> bool:
    return not db.leads_by_status("needs_human")


def _reply(provider, db, lead_id, text):
    token = db.thread_for_lead(lead_id)[0]["thread_token"]
    provider.simulate_reply(thread_token=token, from_addr=db.get_lead(lead_id)["contact_email"], text=text)


# --------------------------------------------------------------------- drafting

class RefusingLLM(FakeLLM):
    def structured(self, **kw):
        if kw["schema"] is schemas.OutreachDraft:
            raise LLMRefusal("declined")
        return super().structured(**kw)


class BadDraftLLM(FakeLLM):
    """Produces a draft that can never pass the lint, however many times it is asked."""

    def __init__(self):
        super().__init__()
        self.draft_calls = 0

    def structured(self, **kw):
        if kw["schema"] is schemas.OutreachDraft:
            self.draft_calls += 1
            return schemas.OutreachDraft(
                subject="URGENT legal notice about your site",
                opening="You are violating the ADA.",
                findings_paragraph="You will be sued for $75,000.",
                exposure_paragraph="We guarantee you will be fully compliant and certified.",
                offer_paragraph="Act now.", call_to_action="Reply immediately.",
            )
        return super().structured(**kw)


def test_a_refused_draft_falls_back_to_the_safe_template(lead_ready, settings):
    db, lead_id = lead_ready
    msg_id = compose_initial(db, settings, RefusingLLM(), lead_id)
    msg = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
    assert msg["status"] == "queued", msg["lint"]
    assert db.get_lead(lead_id)["status"] == "queued"
    assert nobody_waiting(db)


def test_an_unfixable_draft_is_retried_then_replaced_by_the_template(lead_ready, settings):
    db, lead_id = lead_ready
    llm = BadDraftLLM()
    msg_id = compose_initial(db, settings, llm, lead_id)

    # Tried the model, fed the lint back, then gave up on it and used the template.
    assert llm.draft_calls == settings.autopilot.lint_repair_attempts + 1
    msg = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
    assert msg["status"] == "queued", msg["lint"]
    body = msg["body_text"].lower()
    for banned in ("urgent", "guarantee", "certified", "violating", "$75,000", "act now"):
        assert banned not in body, banned
    assert "estimate" in body and "unsubscribe" in body
    assert nobody_waiting(db)
    assert any("standard template" in n["detail"]["headline"] for n in db.notices())


def test_no_model_capacity_defers_instead_of_escalating(lead_ready, settings):
    db, lead_id = lead_ready

    class OutOfCapacity(FakeLLM):
        def structured(self, **kw):
            raise LLMCapacityError("usage limit reached")

    assert compose_initial(db, settings, OutOfCapacity(), lead_id) is None
    lead = db.get_lead(lead_id)
    assert lead["status"] == "scanned"          # still a perfectly good lead
    assert lead["next_action_at"] is not None   # just parked
    assert nobody_waiting(db)
    assert db.query("SELECT 1 FROM events WHERE kind='deferred'")


# --------------------------------------------------------------------- replies

def test_unclear_reply_gets_one_question_then_a_polite_close(lead_ready, settings):
    db, lead_id = lead_ready
    llm, provider = FakeLLM(), ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)

    _reply(provider, db, lead_id, "hm")
    process_inbound(db, settings, llm, provider)
    out = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    assert "clarifying" not in out[-1]["body_text"]
    assert "would you like me" in out[-1]["body_text"].lower()
    assert db.get_lead(lead_id)["clarify_count"] == 1
    assert nobody_waiting(db)

    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC + timedelta(hours=1))
    _reply(provider, db, lead_id, "mmm")
    process_inbound(db, settings, llm, provider)
    lead = db.get_lead(lead_id)
    assert lead["status"] == "archived"
    assert db.is_suppressed(lead["contact_email"])
    out = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    assert "close the file" in out[-1]["body_text"].lower()
    assert nobody_waiting(db)

    # Never a third attempt.
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC + timedelta(hours=2))
    _reply(provider, db, lead_id, "still lost")
    process_inbound(db, settings, llm, provider)
    assert not db.query("SELECT 1 FROM messages WHERE direction='out' AND status IN ('queued','draft','held')")


def test_out_of_scope_request_is_declined_not_escalated(lead_ready, settings):
    db, lead_id = lead_ready
    provider = ConsoleProvider(settings.workdir)

    class EscalatingLLM(FakeLLM):
        def structured(self, **kw):
            if kw["schema"] is schemas.NegotiationReply:
                return schemas.NegotiationReply(
                    body_text="", package="bundle", proposed_price_cents=199000, ready_to_close=False,
                    escalate=True, escalate_reason="they want a full site redesign",
                )
            return super().structured(**kw)

    llm = EscalatingLLM()
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    _reply(provider, db, lead_id, "Could you also rebuild our whole website and run our ads?")
    process_inbound(db, settings, llm, provider)

    lead = db.get_lead(lead_id)
    assert lead["status"] == "engaged"
    out = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"][-1]
    assert out["status"] == "queued" and "only do the two things" in out["body_text"]
    assert nobody_waiting(db)


def test_wrong_person_without_a_forwarding_address_closes_quietly(lead_ready, settings):
    db, lead_id = lead_ready
    llm, provider = FakeLLM(), ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    _reply(provider, db, lead_id, "You have the wrong person, I don't handle the website.")
    process_inbound(db, settings, llm, provider)
    assert db.get_lead(lead_id)["status"] == "archived"
    assert nobody_waiting(db)


def test_a_deletion_request_is_honoured_immediately(lead_ready, settings):
    db, lead_id = lead_ready
    llm, provider = FakeLLM(), ConsoleProvider(settings.workdir)
    compose_initial(db, settings, llm, lead_id)
    deliver_queued(db, settings, provider, now=MONDAY_NOON_UTC)
    snap_dir = settings.workdir / "snapshots" / "springfielddental.example"
    assert snap_dir.exists()

    _reply(provider, db, lead_id, "Please delete my data and never contact me again.")
    process_inbound(db, settings, llm, provider)

    lead = db.get_lead(lead_id)
    assert lead["status"] == "unsubscribed"
    assert db.is_suppressed("frontdesk@springfielddental.example")
    assert not snap_dir.exists()
    assert not db.query("SELECT 1 FROM findings")
    assert all(m["body_text"] == "[erased at recipient request]"
               for m in db.thread_for_lead(lead_id) if m["direction"] == "out")
    assert nobody_waiting(db)


# --------------------------------------------------------------------- money back

def test_undeliverable_work_is_refunded_automatically(lead_ready, settings, monkeypatch):
    db, lead_id = lead_ready
    db.insert("messages", {"lead_id": lead_id, "thread_token": "tok9", "direction": "out", "kind": "initial",
                           "subject": "x", "body_text": "x", "to_addr": "a@b.c", "from_addr": "x@y.z",
                           "message_id": "<tok9.1@x>", "status": "sent", "created_at": "2026-01-01T00:00:00+00:00"})
    deal = open_or_create_deal(db, lead_id, Package.BUNDLE, settings.pricing.bundle_cents, "usd")
    mark_paid(db, settings, deal["id"], payment_intent="pi_x")

    from engine.fixing import verify as verify_mod

    def boom(*a, **kw):
        raise RuntimeError("snapshot files are gone")

    monkeypatch.setattr(verify_mod, "build_bundle", boom)
    verify_mod.start_fix(db, settings, FakeLLM(), deal["id"])

    assert db.one("SELECT status FROM deals WHERE id=?", (deal["id"],))["status"] == "refunded"
    assert db.get_lead(lead_id)["status"] == "refunded"
    refunds = db.query("SELECT * FROM ledger WHERE kind='refund'")
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == -settings.pricing.bundle_cents
    note = db.one("SELECT * FROM messages WHERE kind='delivery' ORDER BY id DESC LIMIT 1")
    assert "refunded" in note["body_text"].lower()
    assert nobody_waiting(db)


def test_auto_refund_records_a_notice_and_closes_the_file(settings):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="x.example", url="https://x.example/", source="t")
    deal = open_or_create_deal(db, lead_id, Package.ADA, 149000, "usd")
    mark_paid(db, settings, deal["id"], payment_intent="pi_y")

    out = autopilot.auto_refund(db, settings, deal["id"], "never went live")
    assert out["refunded"] and out["amount_cents"] == 149000
    assert db.get_lead(lead_id)["status"] == "refunded"
    assert any("Refunded" in n["detail"]["headline"] for n in db.notices())
    assert nobody_waiting(db)


def test_escalation_closes_the_file_when_autopilot_is_on(settings):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="x.example", url="https://x.example/", source="t")
    autopilot.escalate(db, settings, lead_id, "something odd")
    assert db.get_lead(lead_id)["status"] == "archived"
    assert nobody_waiting(db)

    settings.autopilot.enabled = False
    lead2, _ = db.upsert_lead(domain="y.example", url="https://y.example/", source="t")
    autopilot.escalate(db, settings, lead2, "something odd")
    assert db.get_lead(lead2)["status"] == "needs_human"
