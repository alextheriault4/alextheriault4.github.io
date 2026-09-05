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


def compute_exposure(*, ada_score: int, aiseo_score: int, region: str | None, category: str | None,
                     critical_count: int) -> dict[str, Any]:
    ada = ada_exposure(ada_score, region, critical_count)
    seo = aiseo_exposure(aiseo_score, category)
    out = {**ada, **seo}
    out["assumptions"] = ada["assumptions"] + seo["assumptions"]
    out["sources"] = ada["sources"] + seo["sources"]  # ADA sources first; the footer shows the first few
    return out


def money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.0f}"
