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
prospects who genuinely only want the fix. Both cost the same up front, because it is the
same work; the monthly fee buys what happens afterwards, and charging extra for saying no
to it would just be a penalty.

**Why the price is low.** The customer's real alternative is doing nothing, or spending an
afternoon on it themselves. At $99 that comparison is not worth their time, which is the
whole point. Prices come from settings, and ``engine/pricing.py`` may move them on its own
if the market disagrees - see the price ladder there.
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

    @staticmethod
    def _money(cents: int) -> str:
        """Whole dollars where it is whole dollars; cents where the cents matter."""
        return f"${cents / 100:,.0f}" if cents % 100 == 0 else f"${cents / 100:,.2f}"

    def price_summary(self) -> str:
        if not self.is_recurring:
            return f"{self._money(self.setup_cents)} once"
        if self.setup_cents:
            return f"{self._money(self.setup_cents)} to fix it, then {self._money(self.monthly_cents)}/month"
        return f"{self._money(self.monthly_cents)}/month"

    def annual_value_cents(self) -> int:
        return self.setup_cents + self.monthly_cents * 12

    def first_year_cents(self) -> int:
        """What it costs them in the first twelve months - the number to compare against."""
        return self.setup_cents + self.monthly_cents * 12


MAINTENANCE_LINE = (
    "the checklist itself kept current - when WCAG guidance changes, or the search engines "
    "and AI assistants change what they read, the new checks are added and your site is "
    "measured against them at no extra cost"
)


def catalogue(settings: Settings | PricingSettings) -> dict[str, Plan]:
    """The plans on offer, built from your configured prices.

    Two, deliberately. The work is identical either way; the only question is whether they
    want it watched afterwards. A pricing grid would cost more in confusion than it could
    ever earn from a business this size.
    """
    p = settings.pricing if isinstance(settings, Settings) else settings
    return {
        "care": Plan(
            id="care", name="Fix and keep it fixed",
            billing="subscription", setup_cents=p.care_setup_cents, monthly_cents=p.care_monthly_cents,
            covers=("ada", "seo"), recommended=True, minimum_months=p.minimum_months,
            blurb="we fix everything in the report now, then check it every month and fix whatever slips",
            includes=(
                "every issue in the report fixed, usually within 10 business days",
                "an automatic recheck every month against the whole checklist",
                "anything that regresses fixed the same week, at no extra cost",
                "new pages you publish checked and corrected as they appear",
                MAINTENANCE_LINE,
                "a short monthly email showing both scores and what changed",
                "cancel any time, in one click, with no notice period",
            ),
        ),
        "fix_only": Plan(
            id="fix_only", name="One-off fix",
            billing="one_time", setup_cents=p.fix_only_cents, monthly_cents=0,
            covers=("ada", "seo"),
            blurb="the same fix, once, with no monthly checking afterwards",
            includes=(
                "every issue in the report fixed",
                "a verification recheck and a before/after report",
                "30 days of follow-up corrections",
                "no monitoring afterwards - new pages and new rules are not covered",
            ),
        ),
    }


def recommend(settings: Settings, ada_percent: int, seo_percent: int) -> Plan:
    """Which plan to lead with. Always the monitored one: the fix is the same price, so
    the only real question is whether it stays fixed."""
    return catalogue(settings)["care"]


def alternatives(settings: Settings, recommended: Plan) -> list[Plan]:
    """What else to mention."""
    return [p for p in catalogue(settings).values() if p.id != recommended.id]


def get(settings: Settings, plan_id: str) -> Plan:
    plans = catalogue(settings)
    if plan_id in plans:
        return plans[plan_id]
    # Deals written against older catalogues and package names still resolve.
    legacy = {"bundle": "fix_only", "ada": "care", "aiseo": "care",
              "care_ada": "care", "care_seo": "care"}
    return plans[legacy.get(plan_id, "care")]


def _up_to_whole_dollars(cents: int) -> int:
    """Round a computed floor up to a whole dollar. A floor of $79.20 is arithmetic; $80 is
    a price. Rounding up never takes the floor below what the discount policy allows."""
    return -(-cents // 100) * 100


def floor_for(settings: Settings, plan: Plan) -> tuple[int, int]:
    """The lowest setup and monthly price the negotiation agent may offer for this plan."""
    pct = (100 - settings.pricing.max_discount_pct) / 100
    setup = max(int(plan.setup_cents * pct), min(plan.setup_cents, settings.pricing.floor_setup_cents))
    setup = min(plan.setup_cents, _up_to_whole_dollars(setup))
    monthly = max(int(plan.monthly_cents * pct),
                  min(plan.monthly_cents, settings.pricing.floor_monthly_cents)) if plan.monthly_cents else 0
    return setup, monthly
