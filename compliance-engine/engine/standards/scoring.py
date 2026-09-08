"""Turning check results into percentages that mean something.

The score is **earned weight over applicable weight**:

    score = sum(weight of checks that passed) / sum(weight of checks that passed or failed)

Three deliberate decisions behind that formula:

* **Checks that don't apply don't count.** A site with no video is not marked down for
  missing captions. Otherwise every small site would be capped at an arbitrary ceiling and
  the number would be meaningless.
* **Manual checks are reported but never scored.** We cannot decide them from a crawl, so
  folding a guess into the percentage would be dishonest. They appear in the report as
  "needs a person to check".
* **Checks we couldn't decide are excluded too.** axe's "incomplete" results mean exactly
  that; counting them either way would be a coin flip presented as a measurement.

So the headline number is *automated conformance against the checks that apply to this
site*. That is a real, reproducible measurement. It is not the same as "compliant", and
the report never says it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .checks import ALL_CHECKS, BY_ID, CATEGORY_TITLES, Area, Check

Status = Literal["pass", "fail", "not_applicable", "needs_review"]

# Statuses that count toward the denominator.
SCORED = ("pass", "fail")


@dataclass
class CheckResult:
    """The outcome of one check across the pages we looked at."""

    check_id: str
    status: Status
    count: int = 0                              # how many elements/pages are affected
    detail: str = ""                            # one line for the report
    pages: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @property
    def check(self) -> Check:
        return BY_ID[self.check_id]

    def as_dict(self) -> dict[str, Any]:
        c = self.check
        return {
            "id": self.check_id, "title": c.title, "area": c.area, "category": c.category,
            "status": self.status, "weight": c.weight, "detection": c.detection, "standard": c.standard,
            "why": c.why, "fix": c.fix, "auto_fixable": c.auto_fixable, "level": c.level,
            "failure_phrase": c.failure_phrase,
            "count": self.count, "detail": self.detail, "pages": self.pages[:5],
            "evidence": self.evidence[:5],
        }


@dataclass
class CategoryScore:
    category: str
    title: str
    percent: int
    passed: int
    failed: int
    weight_earned: int
    weight_applicable: int


@dataclass
class Scorecard:
    area: Area
    percent: int
    passed: int
    failed: int
    not_applicable: int
    needs_review: int
    weight_earned: int
    weight_applicable: int
    categories: list[CategoryScore]
    failures: list[CheckResult]
    manual: list[CheckResult]

    @property
    def band(self) -> str:
        return band_for(self.percent)

    @property
    def fixable_failures(self) -> list[CheckResult]:
        return [r for r in self.failures if r.check.auto_fixable]

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [r for r in self.failures if r.check.weight >= 8]

    def as_dict(self) -> dict[str, Any]:
        return {
            "area": self.area, "percent": self.percent, "band": self.band,
            "passed": self.passed, "failed": self.failed,
            "not_applicable": self.not_applicable, "needs_review": self.needs_review,
            "weight_earned": self.weight_earned, "weight_applicable": self.weight_applicable,
            "checks_applicable": self.passed + self.failed,
            "categories": [c.__dict__ for c in self.categories],
            "failures": [r.as_dict() for r in self.failures],
            "manual": [r.as_dict() for r in self.manual],
            "fixable_count": len(self.fixable_failures),
            "critical_count": len(self.critical_failures),
        }


def band_for(percent: int) -> str:
    """A word for the number, so the report doesn't lean on the number alone."""
    if percent >= 95:
        return "excellent"
    if percent >= 85:
        return "good"
    if percent >= 70:
        return "fair"
    if percent >= 50:
        return "poor"
    return "critical"


def score(results: list[CheckResult], area: Area) -> Scorecard:
    """Build the scorecard for one area from that area's check results."""
    mine = [r for r in results if r.check.area == area]
    seen = {r.check_id for r in mine}
    # Any check we never produced a result for is treated as not applicable rather than
    # silently dropped, so the counts always add up to the registry.
    for c in ALL_CHECKS:
        if c.area == area and c.id not in seen:
            mine.append(CheckResult(c.id, "not_applicable", detail="not evaluated"))

    # Manual checks are excluded here rather than trusting every detector to emit the right
    # status for them. The guarantee that a percentage never contains a guess belongs in the
    # scorer, not in a convention the callers have to remember.
    scored = [r for r in mine if r.status in SCORED and r.check.detection != "manual"]
    earned = sum(r.check.weight for r in scored if r.status == "pass")
    applicable = sum(r.check.weight for r in scored)
    percent = int(round(100 * earned / applicable)) if applicable else 100

    categories: list[CategoryScore] = []
    for cat in dict.fromkeys(c.category for c in ALL_CHECKS if c.area == area):
        rows = [r for r in scored if r.check.category == cat]
        if not rows:
            continue
        cat_earned = sum(r.check.weight for r in rows if r.status == "pass")
        cat_applicable = sum(r.check.weight for r in rows)
        categories.append(CategoryScore(
            category=cat, title=CATEGORY_TITLES.get(cat, cat),
            percent=int(round(100 * cat_earned / cat_applicable)) if cat_applicable else 100,
            passed=sum(1 for r in rows if r.status == "pass"),
            failed=sum(1 for r in rows if r.status == "fail"),
            weight_earned=cat_earned, weight_applicable=cat_applicable,
        ))

    # A check appears in exactly one of these lists. Anything needing a person is reported
    # under "needs a person to check", never as a failure we are claiming to have measured.
    failures = sorted((r for r in mine if r.status == "fail" and r.check.detection != "manual"),
                      key=lambda r: (-r.check.weight, r.check.category, r.check_id))
    manual = sorted((r for r in mine if r.status != "not_applicable" and
                     (r.status == "needs_review" or r.check.detection == "manual")),
                    key=lambda r: -r.check.weight)
    return Scorecard(
        area=area, percent=percent,
        passed=sum(1 for r in scored if r.status == "pass"),
        failed=sum(1 for r in scored if r.status == "fail"),
        not_applicable=sum(1 for r in mine if r.status == "not_applicable"),
        needs_review=sum(1 for r in mine if r.status == "needs_review"),
        weight_earned=earned, weight_applicable=applicable,
        categories=categories, failures=failures, manual=manual,
    )


def headline(ada: Scorecard, seo: Scorecard) -> dict[str, Any]:
    """The two numbers and the one-line summary the outreach email is allowed to use."""
    return {
        "ada_percent": ada.percent, "ada_band": ada.band,
        "seo_percent": seo.percent, "seo_band": seo.band,
        "ada_passed": ada.passed, "ada_applicable": ada.passed + ada.failed,
        "seo_passed": seo.passed, "seo_applicable": seo.passed + seo.failed,
        "fixable": len(ada.fixable_failures) + len(seo.fixable_failures),
        "total_failures": ada.failed + seo.failed,
        "needs_human_review": ada.needs_review + seo.needs_review,
    }
