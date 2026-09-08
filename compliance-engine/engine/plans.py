"""What you sell.

**Why a retainer is the main offer.** A one-off fix is a bad match for the actual problem
in three ways, and each one costs you money or credibility:

1. *Accessibility does not stay fixed.* The client adds a page, uploads an image without
   alt text, or their theme updates. Within a few months the site has drifted back and the
   money you took bought them a snapshot, not a state.
2. *The verification promise is already ongoing work.* You rescan, you re-report, you fix
   what regressed for 30 days. That is a service, so charge for it as one.
3. *One-off revenue makes the business fragile.* Every month starts at zero and you have to
   cold-email your way back to break-even. Recurring revenue compounds and makes the cost
   of acquiring a client worth much more.

So the default is **remediation fee + monthly care**, with the one-off kept available for
prospects who genuinely only want the fix. The one-off is priced *higher* than the
remediation half of the retainer, because without the recurring relationship it has to
carry its own acquisition cost.

Every plan is a row here. Prices come from settings so you can change them without code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import PricingSettings, Settings

Billing = Literal["one_time", "subscription", "hybrid"]


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    billing: Billing
    setup_cents: int              # charged once, up front
    monthly_cents: int            # charged every month (0 for one-off plans)
    covers: tuple[str, ...]       # which checklist areas: "ada", "seo"
    blurb: str                    # one sentence for the email
    includes: tuple[str, ...]     # bullet points for the agreement and the report
    recommended: bool = False
    minimum_months: int = 0       # stated commitment, informational only

    @property
    def is_recurring(self) -> bool:
        return self.monthly_cents > 0

    def first_payment_cents(self) -> int:
        return self.setup_cents + (self.monthly_cents if self.billing == "subscription" and not self.setup_cents else 0)

    def price_summary(self) -> str:
        if not self.is_recurring:
            return f"${self.setup_cents / 100:,.0f} one-off"
        if self.setup_cents:
            return f"${self.setup_cents / 100:,.0f} to fix it, then ${self.monthly_cents / 100:,.0f}/month"
        return f"${self.monthly_cents / 100:,.0f}/month"

    def annual_value_cents(self) -> int:
        return self.setup_cents + self.monthly_cents * 12


def catalogue(settings: Settings | PricingSettings) -> dict[str, Plan]:
    """The plans on offer, built from your configured prices."""
    p = settings.pricing if isinstance(settings, Settings) else settings
    return {
        "care": Plan(
            id="care", name="Accessibility & AI-search care",
            billing="subscription", setup_cents=p.care_setup_cents, monthly_cents=p.care_monthly_cents,
            covers=("ada", "seo"), recommended=True, minimum_months=p.minimum_months,
            blurb="we fix everything in the report now, then keep it fixed with a monthly rescan",
            includes=(
                "every issue in the report fixed, usually within 10 business days",
                "an automatic rescan every month against the full checklist",
                "anything that regresses fixed the same week, at no extra cost",
                "new pages you publish checked and corrected as they appear",
                "a short monthly report showing both scores and what changed",
                "an accessibility statement page kept current on your site",
            ),
        ),
        "care_ada": Plan(
            id="care_ada", name="Accessibility care",
            billing="subscription", setup_cents=p.care_ada_setup_cents, monthly_cents=p.care_ada_monthly_cents,
            covers=("ada",), minimum_months=p.minimum_months,
            blurb="the accessibility half only, fixed now and monitored monthly",
            includes=(
                "every accessibility issue in the report fixed",
                "monthly rescan against WCAG 2.2 AA automated checks",
                "regressions fixed the same week",
                "a short monthly report",
            ),
        ),
        "care_seo": Plan(
            id="care_seo", name="AI-search care",
            billing="subscription", setup_cents=p.care_seo_setup_cents, monthly_cents=p.care_seo_monthly_cents,
            covers=("seo",), minimum_months=p.minimum_months,
            blurb="the AI and search half only, fixed now and monitored monthly",
            includes=(
                "structured data, llms.txt, sitemap, metadata and crawler access fixed",
                "monthly rescan for regressions and new pages",
                "a short monthly report",
            ),
        ),
        "fix_only": Plan(
            id="fix_only", name="One-off remediation",
            billing="one_time", setup_cents=p.fix_only_cents, monthly_cents=0,
            covers=("ada", "seo"),
            blurb="a single fix of everything in the report, with no ongoing cover",
            includes=(
                "every issue in the report fixed",
                "a verification rescan and a before/after report",
                "30 days of follow-up corrections",
                "no monitoring afterwards - new content is not covered",
            ),
        ),
    }


def recommend(settings: Settings, ada_percent: int, seo_percent: int) -> Plan:
    """Which plan to lead with, given what the scan found.

    Always a care plan: the narrow ones only when a site is already strong in the other
    half, so the pitch stays honest about what the business actually needs.
    """
    plans = catalogue(settings)
    ada_ok = ada_percent >= settings.pricing.strong_percent
    seo_ok = seo_percent >= settings.pricing.strong_percent
    if ada_ok and not seo_ok:
        return plans["care_seo"]
    if seo_ok and not ada_ok:
        return plans["care_ada"]
    return plans["care"]


def alternatives(settings: Settings, recommended: Plan) -> list[Plan]:
    """What else to mention, cheapest commitment last."""
    plans = catalogue(settings)
    out = [p for p in plans.values() if p.id != recommended.id and p.id in ("care", "fix_only")]
    return sorted(out, key=lambda p: (not p.is_recurring, p.annual_value_cents()))


def get(settings: Settings, plan_id: str) -> Plan:
    plans = catalogue(settings)
    if plan_id in plans:
        return plans[plan_id]
    # Deals written before the plan catalogue existed used bare package names.
    legacy = {"bundle": "fix_only", "ada": "care_ada", "aiseo": "care_seo"}
    return plans[legacy.get(plan_id, "care")]


def floor_for(settings: Settings, plan: Plan) -> tuple[int, int]:
    """The lowest setup and monthly price the negotiation agent may offer for this plan."""
    pct = (100 - settings.pricing.max_discount_pct) / 100
    setup = max(int(plan.setup_cents * pct), min(plan.setup_cents, settings.pricing.floor_setup_cents))
    monthly = max(int(plan.monthly_cents * pct),
                  min(plan.monthly_cents, settings.pricing.floor_monthly_cents)) if plan.monthly_cents else 0
    return setup, monthly
