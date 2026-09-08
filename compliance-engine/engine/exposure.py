"""Turn scan scores into honest, sourced dollar ranges.

The email is only allowed to quote numbers produced here, and every number carries
the assumption it came from so the footer can disclose them. Nothing here claims a
lawsuit *will* happen; it says what comparable businesses have paid when one did.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ASSUMPTIONS_PATH = Path(__file__).parent / "data" / "assumptions.json"


@lru_cache
def load_assumptions() -> dict[str, Any]:
    return json.loads(ASSUMPTIONS_PATH.read_text())


def _lookup(table: dict[str, Any], category: str | None) -> Any:
    cat = (category or "").lower()
    for key, value in table.items():
        if key != "default" and key in cat:
            return value
    return table["default"]


def ada_exposure(ada_score: int, region: str | None, critical_count: int) -> dict[str, Any]:
    a = load_assumptions()["ada"]
    mult = a["state_multipliers"].get((region or "").upper(), a["state_multipliers"]["default"])
    # Worse sites sit higher in the range; a near-perfect site still has some exposure.
    severity = max(0.0, min(1.0, (100 - ada_score) / 100))
    low = int(a["settlement_low_cents"] * mult)
    high = int((a["settlement_high_cents"] + a["defense_fees_high_cents"]) * mult)
    typical = int((a["settlement_low_cents"] + (a["settlement_high_cents"] - a["settlement_low_cents"]) * severity
                   + a["defense_fees_low_cents"] * severity) * mult)
    return {
        "ada_low_cents": low,
        "ada_typical_cents": typical,
        "ada_high_cents": high,
        "state_multiplier": mult,
        "lawsuits_per_year": a["lawsuits_per_year"],
        "unruh_applies": (region or "").upper() == "CA",
        "unruh_statutory_min_cents": a["unruh_statutory_min_cents"],
        "critical_issue_count": critical_count,
        "assumptions": [a["settlement_note"], a["defense_fees_note"], a["lawsuits_note"]],
        "sources": a["sources"],
    }


def aiseo_exposure(aiseo_score: int, category: str | None) -> dict[str, Any]:
    s = load_assumptions()["aiseo"]
    visits = _lookup(s["default_monthly_visits"], category)
    ticket = _lookup(s["default_ticket_cents"], category)
    conv = s["default_conversion_rate"]
    share = s["ai_discovery_share"]
    # Fraction of the AI-driven share the site is currently forfeiting, from its score.
    forfeit = max(0.0, min(1.0, (100 - aiseo_score) / 100))
    annual_at_risk = int(visits * 12 * share * conv * ticket * forfeit)
    return {
        "aiseo_annual_low_cents": int(annual_at_risk * 0.5),
        "aiseo_annual_high_cents": int(annual_at_risk * 1.5),
        "aiseo_annual_typical_cents": annual_at_risk,
        "assumed_monthly_visits": visits,
        "assumed_ticket_cents": ticket,
        "assumed_conversion_rate": conv,
        "assumed_ai_discovery_share": share,
        "forfeit_fraction": round(forfeit, 2),
        "assumptions": [s["ai_discovery_share_note"], s["traditional_search_drop_note"]],
        "sources": s["sources"],
    }


def value_case(exposure: dict[str, Any], first_year_cents: int, monthly_cents: int = 0) -> dict[str, Any]:
    """What they stand to gain or avoid, set against what it costs.

    Everything here is arithmetic over figures already in ``exposure`` - nothing new is
    invented, and each number keeps the estimate label it arrived with. The point of
    stating it is that at this price the comparison does most of the persuading, so the
    email never needs to reach for pressure.
    """
    revenue = int(exposure.get("aiseo_annual_typical_cents") or 0)
    settlement_low = int(exposure.get("ada_low_cents") or 0)
    settlement_typical = int(exposure.get("ada_typical_cents") or 0)
    cost = max(first_year_cents, 1)

    # How many months of search revenue it takes to cover the first year's cost.
    months_to_payback = None
    if revenue > 0:
        monthly_gain = revenue / 12
        months_to_payback = max(1, int(round(cost / monthly_gain))) if monthly_gain else None

    return {
        "first_year_cents": first_year_cents,
        "first_year": money(first_year_cents),
        "monthly": money(monthly_cents) if monthly_cents else None,
        # Recovered search revenue against the price.
        "recoverable_annual_cents": revenue,
        "recoverable_annual": money(revenue),
        "revenue_multiple": round(revenue / cost, 1) if revenue else None,
        "months_to_payback": months_to_payback,
        # The cheapest realistic claim against the price.
        "settlement_low_cents": settlement_low,
        "settlement_low": money(settlement_low),
        "settlement_multiple": round(settlement_low / cost, 1) if settlement_low else None,
        "settlement_typical": money(settlement_typical),
        "cost_vs_settlement_pct": round(100 * cost / settlement_low, 1) if settlement_low else None,
    }


def compute_exposure(*, ada_score: int, aiseo_score: int, region: str | None, category: str | None,
                     critical_count: int) -> dict[str, Any]:
    ada = ada_exposure(ada_score, region, critical_count)
    seo = aiseo_exposure(aiseo_score, category)
    out = {**ada, **seo}
    out["assumptions"] = ada["assumptions"] + seo["assumptions"]
    out["sources"] = ada["sources"] + seo["sources"]  # ADA sources first; the footer shows the first few
    return out


def money(cents: int | None) -> str:
    """Whole dollars where the cents are zero, exact cents where they are not.

    A $9.99 price rendered as "$10" is a small lie that appears in an email next to a
    checkout that charges $9.99, so the formatting has to be exact.
    """
    cents = cents or 0
    return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"
