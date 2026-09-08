"""The price has to be able to move, and moving it must never touch anyone already quoted."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine import plans, pricing
from engine.db import Database, utcnow

NOW = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(settings):
    return Database(settings.database_path)


def _lead(db, n: object = 1) -> int:
    lead_id, _ = db.upsert_lead(url=f"https://shop{n}.example/", domain=f"shop{n}.example",
                                business_name=f"Shop {n}", contact_email=f"owner@shop{n}.example")
    return lead_id


def _emailed(db, key: str, count: int, *, sold: int = 0) -> None:
    """``count`` businesses cold-emailed at price point ``key``, of whom ``sold`` paid.

    The domains are namespaced by price point so two calls describe two different sets of
    businesses rather than quietly re-pricing the first set.
    """
    for i in range(count):
        lead_id = _lead(db, f"{key}-{i}")
        db.update("leads", lead_id, price_point=key)
        db.insert("messages", {"lead_id": lead_id, "thread_token": f"t{i}", "direction": "out",
                               "kind": "initial", "subject": "s", "body_text": "b", "status": "sent",
                               "created_at": utcnow()})
        if i < sold:
            setup, monthly = (int(x) for x in key.split("+"))
            deal_id = db.insert("deals", {"lead_id": lead_id, "package": "care", "plan": "care",
                                          "price_cents": setup, "monthly_cents": monthly, "currency": "usd",
                                          "status": "paid", "created_at": utcnow(), "paid_at": utcnow()})
            assert deal_id


def _set_current(db, settings, rung: int, *, days_ago: float = 90) -> pricing.PricePoint:
    point = pricing.set_rung(db, settings, rung, reason="test setup")
    since = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    pricing._save(db, pricing.PricePoint(point.setup_cents, point.monthly_cents, point.rung, since, point.reason))
    return pricing.current(db, settings)


# ------------------------------------------------------------------ where it starts

def test_it_starts_at_the_list_price(db, settings):
    point = pricing.current(db, settings)
    assert (point.setup_cents, point.monthly_cents) == (9_900, 999)
    assert point.label == "$99 + $9.99/mo"
    # and that is what the catalogue quotes
    assert plans.catalogue(pricing.with_point(settings, point))["care"].setup_cents == 9_900


def test_the_ladder_is_ordered_expensive_to_cheap(settings):
    rungs = pricing.ladder(settings)
    assert [r.setup_cents for r in rungs] == sorted((r.setup_cents for r in rungs), reverse=True)
    assert rungs[pricing.start_rung(settings)].setup_cents == settings.pricing.care_setup_cents


# ------------------------------------------------------------------ pinning

def test_a_quoted_price_never_moves_underneath_the_prospect(db, settings):
    lead_id = _lead(db)
    quoted = pricing.settings_for_lead(db, settings, lead_id)
    assert quoted.pricing.care_setup_cents == 9_900
    assert db.get_lead(lead_id)["price_point"] == "9900+999"

    pricing.set_rung(db, settings, 4)  # the market said $99 was too much; we are now at $49
    assert pricing.current(db, settings).setup_cents == 4_900

    again = pricing.settings_for_lead(db, settings, lead_id)
    assert again.pricing.care_setup_cents == 9_900, "an existing prospect keeps the price they were given"
    assert plans.catalogue(again)["care"].price_summary() == "$99 to fix it, then $9.99/month"
    # a lead we have never written to gets today's price
    assert pricing.settings_for_lead(db, settings, _lead(db, 2)).pricing.care_setup_cents == 4_900


def test_the_negotiation_floor_follows_the_pinned_price_down(db, settings):
    priced = pricing.with_point(settings, pricing.ladder(settings)[4])   # $49 + $4.99
    plan = plans.catalogue(priced)["care"]
    setup_floor, monthly_floor = plans.floor_for(priced, plan)
    assert setup_floor <= plan.setup_cents and monthly_floor <= plan.monthly_cents
    assert setup_floor % 100 == 0, "a floor quoted to a customer is a whole number of dollars"


def test_a_price_point_that_has_left_the_ladder_is_still_honoured(db, settings):
    lead_id = _lead(db)
    db.update("leads", lead_id, price_point="129900+2999")   # from an older ladder
    quoted = pricing.settings_for_lead(db, settings, lead_id)
    assert quoted.pricing.care_setup_cents == 129_900


def test_paid_deals_keep_their_price_when_the_ladder_moves(db, settings):
    from tests.conftest import care_deal

    lead_id = _lead(db)
    pricing.settings_for_lead(db, settings, lead_id)
    deal = care_deal(db, settings, lead_id)
    assert (deal["price_cents"], deal["monthly_cents"]) == (9_900, 999)

    pricing.set_rung(db, settings, 0)   # everything gets more expensive
    after = db.one("SELECT * FROM deals WHERE id=?", (deal["id"],))
    assert (after["price_cents"], after["monthly_cents"]) == (9_900, 999)


# ------------------------------------------------------------------ the decision

def test_it_holds_until_the_price_has_had_a_fair_trial(db, settings):
    _emailed(db, "9900+999", 10)
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is False
    assert "10 of the 60" in out["reason"]


def test_it_drops_the_price_when_a_fair_trial_sells_nothing(db, settings):
    _set_current(db, settings, 2)
    _emailed(db, "9900+999", 60, sold=0)
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is True
    assert out["new_label"] == "$79 + $9.99/mo"
    assert "sold 0 times in 60 emails" in out["reason"]
    assert pricing.current(db, settings).setup_cents == 7_900
    # and it is written down where you can see it
    assert any(e["kind"] == "pricing_changed" for e in db.query("SELECT * FROM events"))


def test_it_raises_the_price_when_the_market_is_clearly_paying(db, settings):
    _set_current(db, settings, 2)
    _emailed(db, "9900+999", 60, sold=5)     # 8.3%, far above anything cold email should do
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is True
    assert out["new_label"] == "$149 + $14.99/mo"


def test_a_normal_conversion_rate_leaves_the_price_alone(db, settings):
    _set_current(db, settings, 2)
    _emailed(db, "9900+999", 60, sold=1)     # 1.7%: healthy, not a signal to move
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is False
    assert "where it should be" in out["reason"]


def test_it_will_not_move_twice_in_the_same_fortnight(db, settings):
    _set_current(db, settings, 2, days_ago=3)
    _emailed(db, "9900+999", 60, sold=0)
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is False
    assert "only been running 3 days" in out["reason"]


def test_at_the_bottom_it_says_so_instead_of_pretending(db, settings):
    _set_current(db, settings, 4)            # cheapest rung on the ladder
    _emailed(db, "4900+499", 60, sold=0)
    out = pricing.review(db, settings, NOW)
    assert out["moved"] is False
    assert "no lower price left" in out["reason"]
    assert "the message or the market" in out["reason"]


def test_switching_it_off_freezes_the_price(db, settings):
    settings.pricing.adaptive = False
    _set_current(db, settings, 2)
    _emailed(db, "9900+999", 60, sold=0)
    assert pricing.review(db, settings, NOW)["moved"] is False
    # and nothing gets pinned to leads either
    lead_id = _lead(db, 99)
    assert pricing.settings_for_lead(db, settings, lead_id).pricing.care_setup_cents == 9_900
    assert db.get_lead(lead_id)["price_point"] is None


# ------------------------------------------------------------------ what it counts

def test_each_price_is_scored_only_on_its_own_emails_and_its_own_sales(db, settings):
    _emailed(db, "9900+999", 20, sold=2)
    _emailed(db, "4900+499", 10, sold=0)
    at_99 = pricing.performance(db, "9900+999")
    at_49 = pricing.performance(db, "4900+499")
    assert (at_99["sent"], at_99["paid"], at_99["conversion_pct"]) == (20, 2, 10.0)
    assert (at_49["sent"], at_49["paid"]) == (10, 0)
    assert at_99["revenue_cents"] == 2 * 9_900
    assert at_99["revenue_per_send_cents"] == round(2 * 9_900 / 20)


def test_a_dry_run_never_moves_the_price(db, settings):
    """Held mail is mail nobody received, so it is not evidence of anything."""
    for i in range(80):
        lead_id = _lead(db, i)
        db.update("leads", lead_id, price_point="9900+999")
        db.insert("messages", {"lead_id": lead_id, "thread_token": f"t{i}", "direction": "out",
                               "kind": "initial", "subject": "s", "body_text": "b", "status": "held",
                               "created_at": utcnow()})
    assert pricing.performance(db, "9900+999")["sent"] == 0
    assert pricing.review(db, settings, NOW)["moved"] is False


# ------------------------------------------------------------------ visibility

def test_the_dashboard_shows_the_price_and_how_it_is_doing(db, settings):
    from fastapi.testclient import TestClient

    from engine.dashboard.app import create_app

    _emailed(db, "9900+999", 5, sold=1)
    client = TestClient(create_app(settings, db))
    page = client.get("/", headers={"x-admin-token": settings.dashboard.admin_token}).text
    assert "$99 + $9.99/mo" in page
    assert "1 sold from 5 emails" in page
    assert "$49 + $4.99/mo" in page          # the whole ladder is visible, not just today's rung


def test_explain_says_what_would_move_the_price_next(db, settings):
    _set_current(db, settings, 2)
    info = pricing.explain(db, settings, NOW)
    assert info["current"]["label"] == "$99 + $9.99/mo"
    assert "60 more emails" in info["next_move"]
    _emailed(db, "9900+999", 60, sold=1)
    assert "steps down" in pricing.explain(db, settings, NOW)["next_move"]
