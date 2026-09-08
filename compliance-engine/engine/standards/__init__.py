"""The checklist, the scoring, and the standards document generated from them."""

from .checks import (
    ADA_CHECKS,
    ALL_CHECKS,
    AXE_RULE_TO_CHECK,
    BY_ID,
    CATEGORY_TITLES,
    SEO_CHECKS,
    Check,
    auto_fixable_ids,
    checks_for,
)
from .scoring import CheckResult, Scorecard, band_for, headline, score

__all__ = [
    "ADA_CHECKS", "ALL_CHECKS", "AXE_RULE_TO_CHECK", "BY_ID", "CATEGORY_TITLES", "SEO_CHECKS",
    "Check", "CheckResult", "Scorecard", "auto_fixable_ids", "band_for", "checks_for", "headline", "score",
]
