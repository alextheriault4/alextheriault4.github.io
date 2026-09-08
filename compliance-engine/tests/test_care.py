"""Retainer plans and the monthly care cycle that has to justify them."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import care, plans
from engine.db import Database
from engine.deals.checkout import (
    CARE_CYCLE_DAYS,
    cancel_care,
    mark_paid,
    open_or_create_deal,
    queue_checkout_email,
    record_recurring_payment,
)
from engine.llm import FakeLLM
from engine.scanning.runner import classify_after_scan, persist_scan, scan_site


# --------------------------------------------------------------------- the catalogue

def test_the_recommended_plan_is_always_recurring(settings):
    """A one-off fix does not match a problem that comes back, so care leads."""
    for ada, seo in ((30, 30), (95, 40), (40, 95), (70, 70)):
        plan = plans.recommend(settings, ada, seo)
        assert plan.is_recurring, (ada, seo, plan.id)
    assert plans.recommend(settings, 30, 30).id == "care"
    # Strong in one half → sell only the half they need.
    assert plans.recommend(settings, 95, 40).id == "care_seo"
    assert plans.recommend(settings, 40, 95).id == "care_ada"


def test_the_one_off_costs_more_than_the_care_setup(settings):
    """Without the recurring relationship it has to carry its own acquisition cost."""
    cat = plans.catalogue(settings)
    assert cat["fix_only"].setup_cents > cat["care"].setup_cents
    assert not cat["fix_only"].is_recurring
    # And over a year the retainer is worth more, which is the point.
    assert cat["care"].annual_value_cents() > cat["fix_only"].annual_value_cents()


def test_price_summaries_read_like_a_human_wrote_them(settings):
    cat = plans.catalogue(settings)
    assert cat["care"].price_summary() == "$990 to fix it, then $249/month"
    assert cat["fix_only"].price_summary() == "$1,790 one-off"


def test_discount_floor_covers_both_parts(settings):
    care_plan = plans.catalogue(settings)["care"]
    setup, monthly = plans.floor_for(settings, care_plan)
    assert setup < care_plan.setup_cents and monthly < care_plan.monthly_cents
    assert setup >= min(settings.pricing.floor_setup_cents, care_plan.setup_cents)
    assert monthly >= min(settings.pricing.floor_monthly_cents, care_plan.monthly_cents)
    # A one-off plan has no monthly floor to respect.
    assert plans.floor_for(settings, plans.catalogue(settings)["fix_only"])[1] == 0


def test_unknown_plan_ids_fall_back_instead_of_crashing(settings):
    """Deals written before the catalogue existed still resolve."""
    assert plans.get(settings, "bundle").id == "fix_only"
    assert plans.get(settings, "ada").id == "care_ada"
    assert plans.get(settings, "nonsense").id == "care"


# --------------------------------------------------------------------- billing

@pytest.fixture
def care_client(bad_site, settings, browser):
    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="springfielddental.example", url=bad_site.url,
                                business_name="Springfield Family Dental", category="dentist",
                                city="Springfield", region="IL", contact_email="a@b.example", source="test")
    result = scan_site(bad_site.url, settings, browser)
    scan_id = persist_scan(db, settings, db.get_lead(lead_id), result)
    classify_after_scan(db, settings, lead_id, scan_id)
    db.insert("messages", {"lead_id": lead_id, "thread_token": "tk", "direction": "out", "kind": "initial",
                           "subject": "x", "body_text": "x", "to_addr": "a@b.example", "from_addr": "y@z.c",
                           "message_id": "<tk.1@x>", "status": "sent", "created_at": "2026-01-01T00:00:00+00:00"})
    plan = plans.catalogue(settings)["care"]
    deal = open_or_create_deal(db, lead_id, plan, plan.setup_cents, plan.monthly_cents, "usd")
    return db, lead_id, deal["id"]


def test_paying_starts_the_care_clock(care_client, settings):
    db, lead_id, deal_id = care_client
    mark_paid(db, settings, deal_id, payment_intent="pi_1", subscription_id="sub_1",
              amount_total_cents=99000, tax_cents=0)
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    assert deal["status"] == "paid"
    assert deal["stripe_subscription_id"] == "sub_1"
    assert deal["care_started_at"] and deal["next_care_at"]
    due = datetime.fromisoformat(deal["next_care_at"])
    assert (due - datetime.now(timezone.utc)).days >= CARE_CYCLE_DAYS - 1
    assert care.mrr_cents(db) == settings.pricing.care_monthly_cents


def test_monthly_invoices_are_recorded_once(care_client, settings):
    db, lead_id, deal_id = care_client
    mark_paid(db, settings, deal_id, payment_intent="pi_1", subscription_id="sub_1", amount_total_cents=99000)
    out = record_recurring_payment(db, settings, "sub_1", amount_cents=24900, tax_cents=0, invoice_id="in_1")
    assert out["handled"]
    # Stripe retries webhooks; the same invoice must not be booked twice.
    again = record_recurring_payment(db, settings, "sub_1", amount_cents=24900, tax_cents=0, invoice_id="in_1")
    assert again.get("duplicate")
    charges = db.query("SELECT * FROM ledger WHERE kind='charge'")
    assert len(charges) == 2 and sum(c["amount_cents"] for c in charges) == 99000 + 24900


def test_cancelling_stops_the_cycle_and_the_mrr(care_client, settings):
    db, lead_id, deal_id = care_client
    mark_paid(db, settings, deal_id, payment_intent="pi_1", subscription_id="sub_1", amount_total_cents=99000)
    assert care.mrr_cents(db) > 0
    cancel_care(db, settings, "sub_1")
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    assert deal["care_cancelled_at"] and deal["next_care_at"] is None
    assert care.mrr_cents(db) == 0
    assert not care.due_deals(db, datetime.now(timezone.utc) + timedelta(days=365))
    assert any("cancelled" in n["detail"]["headline"] for n in db.notices())


def test_checkout_email_explains_both_charges(care_client, settings):
    db, lead_id, deal_id = care_client
    db.update("deals", deal_id, checkout_url="https://pay.example/x")
    msg_id = queue_checkout_email(db, settings, deal_id, "tk", None)
    body = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))["body_text"]
    assert "$990" in body and "$249 a month" in body
    assert "cancel it any time" in body


# --------------------------------------------------------------------- the cycle

def test_care_cycle_rescans_reports_and_reschedules(care_client, settings, browser):
    db, lead_id, deal_id = care_client
    mark_paid(db, settings, deal_id, payment_intent="pi_1", subscription_id="sub_1", amount_total_cents=99000)
    # Make it due now.
    db.update("deals", deal_id, next_care_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    due = care.due_deals(db)
    assert len(due) == 1

    out = care.run_cycle(db, settings, FakeLLM(), browser, due[0])
    assert out["ok"] and out["cycle"] == 1

    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    assert deal["care_cycles"] == 1
    nxt = datetime.fromisoformat(deal["next_care_at"])
    assert (nxt - datetime.now(timezone.utc)).days >= CARE_CYCLE_DAYS - 1
    assert not care.due_deals(db)  # not due again until next month

    # A fresh care scan is stored, and the client is told either way.
    assert db.latest_scan(lead_id, kind="care")
    report = db.one("SELECT * FROM messages WHERE kind='delivery' ORDER BY id DESC LIMIT 1")
    assert "month 1 check" in report["subject"]
    assert "%" in report["body_text"]
    assert db.query("SELECT 1 FROM events WHERE kind='care_cycle'")


def test_a_quiet_month_still_gets_a_report(care_client, settings):
    """'Nothing changed' is what they are paying to be told, so it must still be sent."""
    db, lead_id, deal_id = care_client
    mark_paid(db, settings, deal_id, payment_intent="pi_1", subscription_id="sub_1", amount_total_cents=99000)
    delta = {"regressions": [], "resolved": [], "before": {"ada": 98, "seo": 96},
             "after": {"ada": 98, "seo": 96}, "regression_titles": [], "fixable_regressions": []}
    care.queue_care_report(db, settings, deal_id, delta, [], cycle=4)
    body = db.one("SELECT * FROM messages WHERE kind='delivery' ORDER BY id DESC LIMIT 1")["body_text"]
    assert "Nothing regressed" in body and "98%" in body
    assert "unsubscribe" in body.lower()


def test_regressions_are_detected_between_cycles():
    previous = {"ada_score": 96, "aiseo_score": 92,
                "ada_summary": {"failures": [{"id": "target-size"}]},
                "aiseo_summary": {"failures": []}}
    current = {"ada_score": 80, "aiseo_score": 92,
               "ada_summary": {"failures": [{"id": "target-size"}, {"id": "image-alt"}]},
               "aiseo_summary": {"failures": [{"id": "meta-description"}]}}
    delta = care.compare(previous, current)
    assert delta["regressions"] == ["image-alt", "meta-description"]
    assert delta["resolved"] == []
    assert "image-alt" in delta["fixable_regressions"]
    assert "Images have text alternatives" in delta["regression_titles"]

    # And the reverse: things that got fixed are reported as resolved.
    back = care.compare(current, previous)
    assert back["resolved"] == ["image-alt", "meta-description"] and back["regressions"] == []


def test_first_ever_cycle_has_no_previous_scan():
    delta = care.compare(None, {"ada_score": 90, "aiseo_score": 88,
                                "ada_summary": {"failures": []}, "aiseo_summary": {"failures": []}})
    assert delta["regressions"] == [] and delta["before"]["ada"] is None
