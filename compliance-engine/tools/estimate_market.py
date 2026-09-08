#!/usr/bin/env python3
"""Estimate how many leads this pipeline actually finds per day, and write MARKET.md.

Every stage of the funnel is a row with a rate and a stated basis, so the estimate can be
argued with rather than believed. Where a number comes from published research it is cited;
where it is a judgement call it says so. Change a rate, re-run, get a new answer.

    python tools/estimate_market.py                     # rewrite MARKET.md
    python tools/estimate_market.py --check             # fail if it is out of date
    python tools/estimate_market.py --listings 2000     # what 2,000 listings a day yields
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import Settings  # noqa: E402
from engine.exposure import money  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "MARKET.md"

# How many business listings one category-and-city query returns before any filtering.
# Both sources are capped in code: Overpass asks for 200 and the orchestrator takes the
# first `limit` (50 by default); Places pages 20 at a time.
LISTINGS_PER_QUERY = 50


@dataclass(frozen=True)
class Stage:
    name: str
    rate: float
    basis: str


# The funnel, in the order the engine applies it. Each rate is the share of the *previous*
# stage that survives this one.
FUNNEL: list[Stage] = [
    Stage("carries a usable website URL", 0.85,
          "both sources are asked only for businesses with a website tag, so the loss here is "
          "normalisation: social pages, wixsite.com and business.site subdomains, aggregators "
          "and dead links are dropped by prospecting/sources.py"),
    Stage("inside the contact policy", 0.80,
          "US-only (CAN-SPAM is the regime this engine implements) and none of the excluded "
          "trades - law, government, schools, medical-adjacent and the rest of engine/legal.py"),
    Stage("site loads and can be scanned", 0.90,
          "parked domains, expired certificates, robots.txt exclusions and timeouts; a judgement "
          "call, and the one most worth measuring once real numbers exist"),
    Stage("a contact address we can find", 0.45,
          "the address has to be in the HTML. Small-business sites often expose only a form, "
          "and prospecting/discover.py deliberately rejects role and vendor addresses. The "
          "softest number in this table"),
    Stage("scores below the leave-it-alone bar", 0.90,
          "WebAIM's 2025 study of a million home pages found 94.8% with detected WCAG failures; "
          "our bar is a weighted score, so a little stricter than 'any failure at all'"),
    Stage("we can actually change it", 0.25,
          "the gate that decides whether we may email at all. Roughly 34% of US small-business "
          "sites are WordPress or Shopify (Clutch 2025) and the WordPress REST API answers on "
          "most of those; a few percent more sit on GitHub Pages, Netlify, Vercel or Cloudflare "
          "Pages. The 41% on Wix, Squarespace and GoDaddy are excluded on purpose: no editing "
          "API exists, so we could not deliver what the email promised"),
]

SOURCES = [
    ("WebAIM Million 2025 - 94.8% of home pages had detected WCAG failures, 51 errors per page",
     "https://webaim.org/projects/million/2025"),
    ("Clutch, State of Small Business Websites 2025 - 83% of US small businesses have a site; "
     "41% built on no-code builders, 34% on WordPress or Shopify, 12% custom-coded",
     "https://clutch.co/resources/state-of-small-business-websites-2025"),
    ("Instantly, Cold Email Benchmark Report 2026 - 3.4% average B2B reply rate",
     "https://instantly.ai/cold-email-benchmark-report-2026"),
    ("Reachoutly, cold email conversion benchmarks 2026 - 1-5% of replies convert; "
     "measured to closed deal, roughly 0.2% of emails sent",
     "https://reachoutly.com/cold-email/conversion-rate/"),
]

# Closed sales per hundred emails, from the benchmarks above. The low end is the published
# all-industry average; the high end is what a tightly targeted list with a specific,
# verifiable claim about the recipient's own website should be able to do.
CONVERSION_LOW_PCT = 0.2
CONVERSION_HIGH_PCT = 1.0


def yield_rate() -> float:
    rate = 1.0
    for s in FUNNEL:
        rate *= s.rate
    return rate


def funnel_table(listings_per_day: int) -> str:
    rows = ["| stage | survives | per day | why that number |", "|---|---:|---:|---|"]
    n = float(listings_per_day)
    rows.append(f"| business listings pulled | - | {n:,.0f} | "
                f"{listings_per_day / LISTINGS_PER_QUERY:.0f} category-and-city queries of {LISTINGS_PER_QUERY} |")
    for s in FUNNEL:
        n *= s.rate
        rows.append(f"| {s.name} | {s.rate:.0%} | {n:,.1f} | {s.basis} |")
    return "\n".join(rows)


def render(settings: Settings, listings_per_day: int) -> str:
    rate = yield_rate()
    per_day = listings_per_day * rate
    cap = settings.outreach.daily_send_cap
    listings_for_cap = cap / rate
    queries_for_cap = listings_for_cap / LISTINGS_PER_QUERY
    monthly_emails = cap * 30
    low_sales = monthly_emails * CONVERSION_LOW_PCT / 100
    high_sales = monthly_emails * CONVERSION_HIGH_PCT / 100
    setup = settings.pricing.care_setup_cents
    monthly = settings.pricing.care_monthly_cents

    def revenue(sales: float) -> str:
        return f"{money(int(sales * setup))} up front plus {money(int(sales * monthly))}/month recurring"

    return f"""# How big is this, actually

An estimate of what the pipeline finds, built from the filters it really applies. Regenerate
it with `python tools/estimate_market.py`; the rates live at the top of that file, so if you
disagree with one, change it and re-run rather than arguing with the prose.

## The short answer

About **{rate:.1%} of business listings** become a lead we are allowed to email and able to
help. At {listings_per_day:,} listings a day that is **{per_day:.0f} qualified leads a day**.

The binding constraint is not supply. The daily send cap is **{cap} emails**, which needs
about **{listings_for_cap:,.0f} listings a day** - roughly {queries_for_cap:.0f} queries, a
few minutes of Overpass traffic - to keep full. There is no shortage of
non-compliant small-business websites; there is a shortage of ones we can both reach and fix,
and a much smaller ceiling on how many strangers a new sending domain should email in a day.

## The funnel

{funnel_table(listings_per_day)}

The last two rows are the interesting ones. Nearly every site fails the checklist, so the
scan is not what filters the market - **access is**. Excluding Wix, Squarespace and GoDaddy
costs roughly two fifths of all small-business sites, and it is still the right call: those
platforms expose no editing API to a third party, so the fix could only ever be a zip file
and an instruction sheet, which is not what the email promised.

## What that turns into

At the cap, {cap} emails a day is {monthly_emails:,} a month. Published cold-email
benchmarks put closed sales somewhere between {CONVERSION_LOW_PCT}% and {CONVERSION_HIGH_PCT}%
of emails sent, which is **{low_sales:.0f} to {high_sales:.0f} sales a month**:

* low end: {revenue(low_sales)}
* high end: {revenue(high_sales)}

The recurring half compounds and the up-front half does not, so the number that matters after
month three is how many subscriptions are still alive, not how many emails went out. That is
also why the engine watches conversion per price point and moves the price on its own when a
rung stops working - see `engine/pricing.py` and the pricing card on the dashboard.

Two things would change these numbers more than anything else:

1. **The contact-address rate** (currently assumed {FUNNEL[3].rate:.0%}). Every point of it is
   a point of the whole funnel. It is also the number we will learn first, from real scans.
2. **The fixability rate** (currently {FUNNEL[5].rate:.0%}). Adding a delivery route for one
   builder platform - even a manual one - would move it further than any amount of extra
   prospecting.

## Sources

{chr(10).join(f'* [{title}]({url})' for title, url in SOURCES)}

---

*Generated by `tools/estimate_market.py` at {listings_per_day:,} listings a day, priced at
{money(setup)} + {money(monthly)}/month. Rates are assumptions, not measurements; replace
them with your own once the first thousand scans are in.*
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--listings", type=int, default=1_000, help="business listings pulled per day")
    ap.add_argument("--check", action="store_true", help="fail if MARKET.md is out of date")
    args = ap.parse_args()

    settings = Settings(_env_file=None)
    text = render(settings, args.listings)
    if args.check:
        if (OUT.read_text() if OUT.exists() else "") != text:
            print("MARKET.md is out of date; run python tools/estimate_market.py")
            return 1
        print("MARKET.md is up to date")
        return 0
    OUT.write_text(text)
    rate = yield_rate()
    print(f"wrote {OUT}: {rate:.2%} of listings become a mailable, fixable lead "
          f"({args.listings * rate:.0f} a day from {args.listings:,} listings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
