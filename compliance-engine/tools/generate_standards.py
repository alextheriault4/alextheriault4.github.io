#!/usr/bin/env python3
"""Write STANDARDS.md from the check registry.

The document and the scanner cannot drift apart because the document is generated from
the same list the scanner uses. A test asserts the file on disk matches this output.

    python tools/generate_standards.py            # rewrite STANDARDS.md
    python tools/generate_standards.py --check    # fail if it is out of date
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.standards import (ALL_CHECKS, CATEGORY_TITLES, CHECKLIST_VERSION,  # noqa: E402
                              VERSION_NOTES, Check)

OUT = Path(__file__).resolve().parent.parent / "STANDARDS.md"

DETECTION_LABEL = {
    "auto": "automated",
    "heuristic": "heuristic",
    "manual": "needs a person",
}

HEADER = """# The checklist

Everything this engine checks on a website, why each item matters, and what fixing it
involves. It is generated from `engine/standards/checks.py`, which is the same list the
scanner scores against and the fixer repairs from - so this document cannot drift away
from what the code actually does.

Use it two ways:

* **As a build standard.** Work down it when you make a site and it will score close to
  100% on both halves before anyone ever scans it. The reference implementation in
  `tests/fixtures/sites/good_site/` scores 100/100 and is worth reading alongside this.
* **As the scoring model.** Percentages are earned weight over applicable weight, so a
  site is only ever judged on the checks that apply to it.

## How the percentages work

```
score = sum(weight of checks that PASSED) / sum(weight of checks that PASSED or FAILED)
```

Three rules keep that number honest:

1. **Checks that don't apply are excluded.** No video means no captions check, and no
   penalty for it. The denominator is per-site, not a fixed total.
2. **Checks needing a person are never scored.** They are listed in the report as
   "needs a person to check" and excluded from both halves of the fraction.
3. **Checks the tools couldn't decide are excluded too.** Guessing and presenting it as a
   measurement would be dishonest.

So the headline number means *automated conformance against the checks that apply to this
site*. Automated testing catches roughly a third to a half of real accessibility problems;
the rest genuinely need a human with a keyboard and a screen reader. **A percentage here is
not a statement that a site is legally compliant, and the report never claims it is.**

### Bands

| Score | Band |
|---|---|
| 95-100% | excellent |
| 85-94% | good |
| 70-84% | fair |
| 50-69% | poor |
| under 50% | critical |

### How to read the columns

* **Weight** - how much the check moves the score, 1 to 10.
* **How it's checked** - `automated` (a tool decides), `heuristic` (our rule of thumb,
  usually right), `needs a person` (listed, never scored).
* **We fix it** - yes means the remediation bundle repairs it without the client doing
  anything.

## Editions

The checklist is versioned `YYYY.MM`, because clients on the monthly plan pay for it to stay
current. When the accessibility guidelines change, or search engines and AI assistants change
what they read, a check is added here and the version is bumped; every site on a care plan is
measured against the new list at its next monthly check and told in its report what changed.
Each check records the edition that introduced it.

{editions}
"""


def editions() -> str:
    rows = ["| Edition | What changed |", "|---|---|"]
    for version, note in sorted(VERSION_NOTES.items(), reverse=True):
        n = sum(1 for c in ALL_CHECKS if c.since == version)
        current = " *(current)*" if version == CHECKLIST_VERSION else ""
        rows.append(f"| **{version}**{current} | {note} ({n} check{'s' if n != 1 else ''}) |")
    return "\n".join(rows)


def table(checks: list[Check]) -> str:
    lines = ["| # | Check | Weight | How it's checked | We fix it | Standard |",
             "|---|---|---|---|---|---|"]
    for i, c in enumerate(checks, 1):
        lines.append(f"| {i} | **{c.title}**<br><span title='{c.id}'>`{c.id}`</span> | {c.weight} | "
                     f"{DETECTION_LABEL[c.detection]} | {'yes' if c.auto_fixable else 'no'} | {c.standard} |")
    return "\n".join(lines)


def detail(checks: list[Check]) -> str:
    out = []
    for c in checks:
        out.append(f"#### `{c.id}` - {c.title}\n")
        out.append(f"*{c.standard}* &middot; weight {c.weight} &middot; {DETECTION_LABEL[c.detection]} "
                   f"&middot; applies to {c.applies} &middot; "
                   f"{'we fix this automatically' if c.auto_fixable else 'needs a decision or content from the owner'}\n")
        out.append(f"**Why it matters.** {c.why}\n")
        out.append(f"**How to fix it.** {c.fix}\n")
    return "\n".join(out)


def section(area: str, title: str, intro: str) -> str:
    checks = [c for c in ALL_CHECKS if c.area == area]
    parts = [f"## {title}\n", intro, ""]
    parts.append(f"{len(checks)} checks, {sum(c.weight for c in checks)} total weight. "
                 f"{sum(1 for c in checks if c.auto_fixable)} of them we fix automatically; "
                 f"{sum(1 for c in checks if c.detection == 'manual')} need a person.\n")
    for cat in dict.fromkeys(c.category for c in checks):
        rows = [c for c in checks if c.category == cat]
        parts.append(f"### {CATEGORY_TITLES.get(cat, cat)}\n")
        parts.append(table(rows))
        parts.append("")
        parts.append(detail(rows))
    return "\n".join(parts)


def render() -> str:
    ada_intro = (
        "Measured against **WCAG 2.2 Level A and AA**, the standard US courts and the "
        "Department of Justice's guidance point to. Organised by the four WCAG principles."
    )
    seo_intro = (
        "Whether a search engine or an AI assistant can reach the site, read it, work out "
        "what the business is, and quote it accurately. Traditional SEO and AI readiness "
        "have converged: both now depend on machine-readable facts rather than keywords."
    )
    body = [
        HEADER.format(editions=editions()),
        section("ada", "Part 1 - Accessibility", ada_intro),
        section("seo", "Part 2 - Search and AI discoverability", seo_intro),
        "## Building to this standard\n",
        "If you are making a site rather than fixing one, the short version:\n",
        "1. Real HTML: headings in order, lists as lists, buttons as `<button>`, one `<h1>`.",
        "2. Landmarks (`header`, `nav`, `main`, `footer`) and a skip link.",
        "3. Alt text on every image; empty `alt=\"\"` for decoration.",
        "4. Visible labels tied to every form field. A placeholder is not a label.",
        "5. Text contrast at least 4.5:1, and never remove the focus outline without replacing it.",
        "6. A viewport meta tag, no `user-scalable=no`, and a layout that reflows at 320px.",
        "7. `lang` on `<html>`, a descriptive `<title>` and meta description on every page.",
        "8. LocalBusiness JSON-LD with name, address, phone, hours and `sameAs`, plus FAQ markup.",
        "9. `robots.txt` that allows AI crawlers, a `sitemap.xml`, and an `llms.txt` summary.",
        "10. Server-rendered text, the trade and the town in plain words, and an accessibility statement.\n",
        "`tests/fixtures/sites/good_site/` is a complete worked example that scores 100/100.\n",
        "---\n",
        f"*Generated from `engine/standards/checks.py` - {len(ALL_CHECKS)} checks, "
        f"edition {CHECKLIST_VERSION}. "
        "Run `python tools/generate_standards.py` after changing the registry.*",
    ]
    return "\n".join(body) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print("STANDARDS.md is out of date; run python tools/generate_standards.py")
            return 1
        print("STANDARDS.md is up to date")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(ALL_CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
