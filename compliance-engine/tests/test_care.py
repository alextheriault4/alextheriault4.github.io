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

def test_only_two_plans_and_the_monitored_one_leads(settings):
    """The fix costs the same either way, so the only question is whether it stays fixed."""
    cat = plans.catalogue(settings)
    assert set(cat) == {"care", "fix_only"}
    for ada, seo in ((30, 30), (95, 40), (40, 95), (70, 70)):
        assert plans.recommend(settings, ada, seo).id == "care"
    assert plans.alternatives(settings, cat["care"]) == [cat["fix_only"]]


def test_the_fix_costs_the_same_either_way(settings):
    """The monthly buys monitoring, not the fix. Charging more for the same work would be
    the kind of thing a customer notices later and resents."""
    cat = plans.catalogue(settings)
    assert cat["fix_only"].setup_cents == cat["care"].setup_cents == settings.pricing.care_setup_cents
    assert not cat["fix_only"].is_recurring
    # A year of monitoring costs less than a quarter of the fix.
    assert cat["care"].monthly_cents * 12 < cat["care"].setup_cents / 4


def test_prices_render_exactly_never_rounded(settings):
    """$9.99 shown as "$10" next to a checkout that charges $9.99 is a small lie."""
    from engine.exposure import money

    cat = plans.catalogue(settings)
    assert cat["care"].price_summary() == "$499 to fix it, then $9.99/month"
    assert cat["fix_only"].price_summary() == "$499 once"
    assert money(999) == "$9.99" and money(49900) == "$499" and money(0) == "$0"
    assert cat["care"].first_year_cents() == 49900 + 999 * 12


def test_the_monthly_price_cannot_be_discounted(settings):
    """There is no room to haggle over ten dollars; only the up-front fee can move."""
    care_plan = plans.catalogue(settings)["care"]
    setup, monthly = plans.floor_for(settings, care_plan)
    assert setup < care_plan.setup_cents
    assert monthly == care_plan.monthly_cents
    assert setup >= min(settings.pricing.floor_setup_cents, care_plan.setup_cents)
    assert plans.floor_for(settings, plans.catalogue(settings)["fix_only"])[1] == 0


def test_the_package_promises_to_keep_the_checklist_current(settings):
    """A monthly fee for a static checklist would be hard to justify; say what it buys."""
    care_plan = plans.catalogue(settings)["care"]
    joined = " ".join(care_plan.includes).lower()
    assert "new checks are added" in joined and "no extra cost" in joined
    assert "cancel any time" in joined
    # And the one-off is explicit that it does not include that.
    assert "new rules are not covered" in " ".join(plans.catalogue(settings)["fix_only"].includes)


def test_unknown_plan_ids_fall_back_instead_of_crashing(settings):
    """Deals written against older catalogues still resolve."""
    assert plans.get(settings, "bundle").id == "fix_only"
    assert plans.get(settings, "care_ada").id == "care"
    assert plans.get(settings, "ada").id == "care"
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
    assert "$499" in body and "$9.99 a month" in body
    assert "cancel it any time in one click" in body


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


# --------------------------------------------------------------------------------------
# The checklist is versioned, because "we keep up with the rules" is a promise we sell.


def test_new_rules_reach_a_client_who_was_last_measured_on_an_older_edition(monkeypatch):
    from engine.standards import checks as check_registry

    older = check_registry.Check(
        id="image-alt", title="Images have text alternatives", area="ada", category="perceivable",
        weight=10, detection="auto", standard="WCAG 1.1.1 (A)", why="w", fix="f",
        auto_fixable=True, since="2026.09")
    brand_new = check_registry.Check(
        id="ai-answer-block", title="Pages answer the question up front", area="seo",
        category="ai_readiness", weight=6, detection="heuristic", standard="new guidance",
        why="w", fix="f", auto_fixable=True, since="2026.12")
    monkeypatch.setattr(check_registry, "ALL_CHECKS", [older, brand_new])
    monkeypatch.setattr(check_registry, "VERSION_NOTES",
                        {"2026.09": "first published checklist",
                         "2026.12": "added the answer-up-front check that assistants now reward"})
    monkeypatch.setattr(care, "BY_ID", {c.id: c for c in (older, brand_new)})

    previous = {"ada_score": 96, "aiseo_score": 92, "checklist_version": "2026.09",
                "ada_summary": {"failures": []}, "aiseo_summary": {"failures": []}}
    current = {"ada_score": 96, "aiseo_score": 88, "checklist_version": "2026.12",
               "ada_summary": {"failures": []},
               "aiseo_summary": {"failures": [{"id": "ai-answer-block"}]}}
    delta = care.compare(previous, current)

    assert delta["new_checks"] == ["ai-answer-block"]
    assert delta["new_check_failures"] == ["ai-answer-block"]
    assert delta["fixable_new_checks"] == ["ai-answer-block"]
    assert delta["checklist_before"] == "2026.09" and delta["checklist_now"] == "2026.12"
    assert delta["checklist_notes"] == [("2026.12", "added the answer-up-front check that assistants now reward")]
    # And it is reported as a new rule, not as something the client let slip.
    assert delta["regressions"] == []


def test_the_monthly_report_says_what_changed_in_the_rules(care_client, settings):
    db, lead_id, deal_id = care_client
    delta = {"regressions": [], "resolved": [], "regression_titles": [], "fixable_regressions": [],
             "before": {"ada": 96, "seo": 92}, "after": {"ada": 96, "seo": 92},
             "checklist_before": "2026.09", "checklist_now": "2026.12",
             "new_checks": ["ai-answer-block"], "new_check_titles": ["Pages answer the question up front"],
             "new_check_failures": [], "fixable_new_checks": [],
             "checklist_notes": [("2026.12", "added the answer-up-front check")]}
    care.queue_care_report(db, settings, deal_id, delta, [], cycle=4)
    body = db.query("SELECT body_text FROM messages WHERE lead_id=? ORDER BY id DESC",
                    (lead_id,))[0]["body_text"]
    assert "standards moved" in body
    assert "added the answer-up-front check" in body
    assert "Pages answer the question up front" in body
    assert "already met all of them" in body
    assert "no extra charge" in body


def test_a_scan_records_which_edition_of_the_checklist_it_used(bad_site, settings, browser):
    from engine.db import Database
    from engine.scanning.runner import persist_scan, scan_site
    from engine.standards import CHECKLIST_VERSION

    db = Database(settings.database_path)
    lead_id, _ = db.upsert_lead(domain="x.example", url=bad_site.url, source="t")
    result = scan_site(bad_site.url, settings, browser)
    persist_scan(db, settings, db.get_lead(lead_id), result)
    scan = db.latest_scan(lead_id)
    assert scan["checklist_version"] == CHECKLIST_VERSION
    # An older client compared against today's scan sees exactly what is new.
    assert care.compare({"checklist_version": "2000.01", "ada_summary": {}, "aiseo_summary": {}},
                        scan)["new_checks"]
