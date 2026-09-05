# Compliance engine

An autonomous pipeline that finds small-business websites with accessibility (ADA / WCAG) and
AI-search gaps, emails the owner an honest, sourced pitch, handles the reply thread until they
buy, takes payment, remediates the site, verifies the result, and keeps the books. You watch it
from a dashboard; it only stops for the handful of situations it is not allowed to decide.

Everything defaults to a **dry run**: no email leaves the machine, no card is charged, no site
is touched. Each of those is behind its own switch, so you can prove one stage at a time.

```
prospect ──► scan ──► draft ──► send ──► replies ──► negotiate ──► checkout ──► fix ──► verify ──► ledger
 (CSV,      (axe +    (Claude,  (rate-   (classify,   (price       (Stripe +   (patch   (rescan,    (P&L,
  OSM,       AI-SEO    lint,     limited,  suppress,    floor,       Stripe Tax)  HTML,    before/     tax by
  Places)    audit)    footer)   window)   escalate)    escalate)                 files)   after)      state)
```

## What's in the box

| Stage | Module | What it does |
|---|---|---|
| Prospect | `engine/prospecting` | Leads from a CSV, OpenStreetMap (free), or Google Places (key). Drops chains and aggregators. Finds a contact email and detects the platform (WordPress, Wix, Squarespace...). |
| Scan | `engine/scanning` | Headless Chromium + axe-core (WCAG 2.1/2.2 AA) plus manual checks (skip link, focus styles, generic links, autoplay). AI-search audit: robots.txt and AI-crawler blocks, sitemap, llms.txt, JSON-LD LocalBusiness/FAQ, title/description, H1, canonical, OG, HTTPS, viewport, thin or JS-only content, phone/address in text, load time. Two 0-100 scores. |
| Exposure | `engine/exposure.py` + `engine/data/assumptions.json` | Sourced dollar ranges (settlement ranges, defense fees, Unruh, state multipliers; traffic × AI share × conversion × ticket). The email may quote **only** these numbers. |
| Draft | `engine/outreach/compose.py` | Claude writes five short paragraphs from the scan; code adds greeting, signature, the CAN-SPAM footer, sources, report link, unsubscribe link. |
| Lint | `engine/outreach/compliance.py` | Rejects guarantees, "certified", urgency, legal-notice language, deceptive subjects, any dollar figure the exposure model didn't produce, missing address/unsubscribe/legal name. Failed drafts go to "needs human", never out. |
| Send | `engine/outreach/sequence.py` | Weekday business-hours window in your timezone, daily cap, suppression list, two follow-ups (day 3, day 7), bounce/complaint circuit breaker, pause switch. |
| Inbox | `engine/inbox` | Threads matched by `reply+<token>@` address or Message-ID. Claude classifies intent; code acts: unsubscribe and bounces suppress instantly, "not interested" is honoured permanently, redirects re-target the new person, questions/objections go to the negotiation agent, anything hostile or unclear escalates to you. |
| Negotiate | `engine/inbox/negotiate.py` | Claude writes the reply inside a fixed policy: list prices, max discount, hard floor; the code clamps the price and never closes a deal without an explicit "yes". |
| Checkout | `engine/deals/checkout.py` | Stripe Checkout with Stripe Tax (sales tax calculated and collected per jurisdiction) and invoice creation; webhook marks the deal paid and writes the ledger. Placeholder link + "simulate payment" until Stripe is live. |
| Fix | `engine/fixing` | Deterministic HTML patches keyed to findings (alt text, labels, names, lang, title, meta, OG, canonical, JSON-LD, FAQ schema, landmarks, skip link, heading levels, frame titles, focus styles, contrast overrides, tap targets), plus robots.txt (AI crawlers unblocked), sitemap.xml, llms.txt. Applied via WordPress REST + generated mu-plugin, a GitHub pull request, or delivered as a bundle with per-platform instructions and a "needs your input" list. |
| Verify | `engine/fixing/verify.py` | Rescans every 3 days for 45 days; "resolved" means a +15 jump, at least 70, and nothing critical left in the paid area. Sends the before/after report; otherwise escalates. |
| Finance | `engine/finance/ledger.py` | Charges, refunds, estimated fees, tax collected, monthly P&L, taxable sales by client state (nexus watch), CSV export for your accountant. |
| Autopilot | `engine/autopilot.py` | Gives every dead end a pre-decided answer so nothing waits on you: lint repair, safe fallback template, stand-downs, clarify-then-close, automatic refunds, data erasure. |
| Risk controls | `engine/legal.py` | Who may be contacted, how politely we crawl, what we're allowed to claim, and how client credentials are held. |
| Dashboard | `engine/dashboard` | Funnel and KPIs, gates and autonomy switches, notices, "needs a human" queue, held messages with approve/discard, lead timeline and full thread, deal and fix status, finance, pause / resume / breaker reset. Public pages: report, one-click unsubscribe, service agreement, pay, bundle download, crawler info, privacy, terms, self-serve data erasure, Stripe webhook. |
| Orchestrator | `engine/orchestrator.py` | One `tick` runs every stage in order with per-lead error isolation; `run` loops forever; heartbeat on the dashboard; retention housekeeping. |

## Which model account it spends

Three providers, set with `CE_LLM__PROVIDER`:

| Provider | Bills against | How |
|---|---|---|
| `claude_code` *(default)* | **Your Claude subscription** | Runs the Claude Code CLI headlessly. The child process is started with `ANTHROPIC_API_KEY` stripped, so the CLI falls back to your `claude` login. Just run `claude` once to sign in. |
| `claude` | A metered API key | Anthropic API directly, needs `ANTHROPIC_API_KEY`. |
| `fake` | Nothing | Deterministic canned responses; the whole pipeline runs with no model at all. |

The subscription path replaces Claude Code's own system prompt and drops its tools, MCP
servers and settings, which keeps the cached prefix small and byte-identical between
calls. Measured here: **≈$0.28 of quota on the first call, ≈$0.017 on every call after**,
because the prefix becomes a cache read. Reply triage runs on `CE_LLM__CLASSIFY_MODEL`
(Sonnet by default) since it is a small job. `CE_LLM__MAX_BUDGET_USD` caps any single call.

Two things worth knowing before you point a business at it:

- **Subscription usage limits are real.** When one is hit the engine does not fail or ask
  you anything: it marks the lead deferred, waits `CE_AUTOPILOT__CAPACITY_BACKOFF_MINUTES`,
  and carries on. Sustained volume is what API credits are for; switch `CE_LLM__PROVIDER`
  to `claude` and the rest of the engine is unchanged.
- **Check your plan's terms** before running a commercial service on a subscription
  intended for interactive use. That is a question for Anthropic's terms, not something
  this code can answer.

## Quick start (dry run, no keys needed)

```bash
cd compliance-engine
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium            # or set CE_SCANNING__CHROMIUM_PATH to an existing Chrome/Chromium

compliance-engine init                 # creates data/engine.db and a .env from .env.example
# edit .env: company name, legal name, postal address, website. Leave CE_MODE=dry_run.
# uses your Claude subscription by default (run `claude` once to sign in);
# set CE_LLM__PROVIDER=fake to exercise the pipeline with no model calls at all.

compliance-engine add-leads --csv examples/leads.csv
compliance-engine add-leads --url https://some-local-business.com --category dentist --city Springfield --region IL
compliance-engine prospect --category plumber --city Springfield --region IL --limit 25   # OpenStreetMap, free

compliance-engine tick                 # scan → draft → "send" to data/outbox/ → ...
compliance-engine dashboard            # http://127.0.0.1:8787, token from CE_DASHBOARD__ADMIN_TOKEN
```

In dry run the console email provider writes every outbound message to `data/outbox/` as
`.json` and `.eml`. Play the prospect from the lead page ("Inject reply") or the CLI:

```bash
compliance-engine simulate-reply --lead 1 --text "What would you actually change? Do you need our login?"
compliance-engine simulate-reply --lead 1 --text "Can you do it for $800?"
compliance-engine simulate-reply --lead 1 --text "OK go ahead and send the link"
compliance-engine simulate-payment --deal 1
compliance-engine tick                 # builds the fix bundle under data/fixes/<domain>/<deal>/ and queues delivery
```

Tests run the whole thing against two bundled fixture sites (one broken, one clean):

```bash
pytest
```

## Turning it on, one switch at a time

The engine will not do anything irreversible until **all three** hold: `CE_MODE=live`, the matching
`CE_AUTONOMY__AUTO_*` flag is true, and the provider is configured (verified domain, Stripe key,
site access). Anything blocked by a gate is *held* and shows up on the dashboard with an
"Approve & send" button, so you can run live with a human in the loop first, then flip the flag.

0. **Preflight.** Run `compliance-engine preflight`. It lists everything blocking live mode and refuses to let the gates open until each item is fixed. Nothing below matters until it passes.
1. **Model.** Default is your Claude subscription via `CE_LLM__PROVIDER=claude_code` — just run `claude` once to sign in. For sustained volume switch to `CE_LLM__PROVIDER=claude` with an `ANTHROPIC_API_KEY`. Either way the model is `claude-opus-5` with adaptive thinking, structured outputs and refusal fallbacks; a refusal falls back to the fixed template rather than stopping.
2. **Identity.** Form the entity, get the postal address you'll put in every email, write a one-page site at `CE_COMPANY__WEBSITE`, and point `CE_STRIPE__PUBLIC_BASE_URL` at wherever the dashboard's public pages are reachable (behind a reverse proxy with TLS; admin pages need the token).
3. **Payments.** Stripe account, enable Stripe Tax, set `CE_STRIPE__SECRET_KEY`, add a webhook for `checkout.session.completed` and `charge.refunded` to `/webhooks/stripe`, set `CE_STRIPE__WEBHOOK_SECRET`, then `CE_AUTONOMY__AUTO_SEND_CHECKOUT=true`.
4. **Email, last.** Buy a *separate* sending domain (never your main one), set SPF, DKIM, DMARC, a mailbox that speaks SMTP + IMAP, and make sure `reply+anything@` on that domain lands in the inbox (a catch-all or plus-addressing). Warm it up for 2-4 weeks at low volume. Then `CE_EMAIL__PROVIDER=smtp`, `CE_EMAIL__DOMAIN_VERIFIED=true`, keep `CE_OUTREACH__DAILY_SEND_CAP` small (20-40), and turn on `AUTO_SEND_OUTREACH` and `AUTO_REPLY`.
5. **Fixes.** `AUTO_APPLY_FIXES=true` lets it push to WordPress or open GitHub PRs when a client gives access (entered on the lead page). Bundle delivery needs no switch.
6. **Run it as a service.** `deploy/*.service` are systemd units for the loop and the dashboard. `/health` is the liveness check; the dashboard shows the last tick.

## How little it asks of you

With `CE_AUTOPILOT__ENABLED=true` (the default) every dead end has a pre-decided answer.
The engine takes it, writes a **notice** saying what it did, and moves on. Notices are a
log, not a queue: nothing there is waiting on a decision.

| Situation | What it does instead of asking you |
|---|---|
| Draft fails the compliance lint | Feeds the lint's own complaints back to the model (twice), then falls back to a fixed template built from pre-approved sentences and figures, which passes by construction |
| Model refuses or errors | Same fixed template |
| Subscription usage limit / rate limit | Marks the lead deferred, retries in an hour. Nothing is wrong with the lead |
| Reply is unclear | One short clarifying question; if the next reply is still unclear, closes politely and suppresses. Never a third email |
| Reply is hostile, mentions lawyers, or asks how you got their address | Apologises once, suppresses permanently, closes the file. Never argues |
| Reply asks to delete their data | Erases snapshots, findings and message bodies immediately; keeps only the suppression record |
| Wrong person, no forwarding address | Closes the file |
| Asks for work you don't sell | Declines plainly and restates the packages |
| Fix build fails | Retries, then queues a refund **for your approval** |
| Client never publishes the changes | Nudges at day 7 and 21, then queues a refund **for your approval** at day 45 |

**Refunds are the one deliberate exception.** The engine works out that a refund is owed
and then stops: no money moves and the customer is told nothing until you say yes. They
appear on the dashboard overview with Refund / Keep the money buttons, and in
`compliance-engine refunds --approve <deal>` / `--decline <deal>`.

`compliance-engine notices` (or the Notices tab) shows what was handled. The overview's
"Needs a human" count should sit at zero; the tests assert exactly that after each
scenario above. Set `CE_AUTOPILOT__ENABLED=false` to get the older behaviour where these
cases stop and wait for you.

**To watch all of this happen on your own website and mailbox, follow
[TESTING.md](TESTING.md)** — a verified step-by-step run from scan to fix, with a hard
allowlist so nothing can reach anyone but you.

The one thing that still stops everything is deliberate: the deliverability circuit
breaker. If bounces exceed 5% or complaints 0.2%, cold sending pauses until you reset it.
That is the number that gets a sending domain blacklisted, so it is worth your attention.

## What is and isn't automated (read this part)

- **Taxes.** Stripe Tax calculates and collects sales tax on each checkout. It does not register you in a state or file returns. The finance page shows taxable sales by client state so you can see where you're approaching economic-nexus thresholds; the CSV export is what your accountant (or Stripe's filing partners) needs. Income tax is yours.
- **Fixing arbitrary websites.** Fully hands-off application only exists where there is an API: WordPress (REST + application password, plus one small must-use plugin file for the site-level pieces) and Git-hosted sites (pull request). Wix, Squarespace, GoDaddy and similar builders don't expose their editors to third parties, so those clients get a bundle with exact per-platform steps and a header snippet. The delivery email offers to apply the changes if they hand over a collaborator invite; that request lands in "needs a human".
- **Content and design.** Some findings need a human decision (thin content, no phone/address on the page, HTTPS, captions, JS-only rendering). They are listed as "needs your input" in the change log, not silently ignored, and they don't count against verification.
- **Escalations.** With the autopilot on, the cases above resolve themselves and you get notices instead. Turn it off and they queue up for you.
- **Deliverability.** The circuit breaker pauses cold sends when bounces exceed 5% or complaints 0.2% (tunable). A tripped breaker stays tripped until you reset it on the dashboard.

## Legal risk

**Nothing here makes it impossible for you to be sued.** Anyone can file anything, and a
business that emails strangers, takes their money, and changes their website has real
surface area. What the engine does is remove the specific, documented ways companies doing
exactly this work get sued, fined, or reported. That is a meaningful reduction, not a
guarantee, and no software can offer you the second thing.

**What is handled in code**

- **CAN-SPAM.** B2B cold email is lawful in the US when it is honest and offers a working
  opt-out. Every message carries a truthful From and subject, your physical postal
  address, the reason for contact, and three ways out (link, one-click
  `List-Unsubscribe-Post`, or the word "unsubscribe" in a reply). Opt-outs take effect
  immediately and permanently. Enforced by the lint, not by asking a model nicely.
- **Jurisdiction.** Canada's CASL and the EU/UK regimes require consent this engine does
  not obtain, with penalties in the millions. Non-US businesses are refused outright — by
  TLD, by country and state, and by non-US markers in their own page text.
- **Who you contact.** Law firms and plaintiff-side professions are excluded, because they
  are the people most likely to turn an unwanted email into a filing. So are `.gov`,
  `.mil`, `.edu`, and regulated verticals (cannabis, firearms, gambling, adult, payday,
  debt collection). Legal and abuse mailboxes are never emailed.
- **FTC deception.** The 2025 FTC order against accessiBe was about overstated compliance
  claims. The lint forbids "guarantee", "certified", "fully compliant", "avoid lawsuits",
  fines, penalties, urgency, and any dollar figure the model invented. Every number traces
  to `engine/data/assumptions.json` and is labelled an estimate with sources linked.
- **Unauthorised practice of law and defamation.** The engine never states that a site
  "violates" anything, never tells anyone what the law requires of them, and never
  promises immunity. Those phrasings are blocked in `engine/legal.py` and tested.
- **Crawling.** The scanner identifies itself, links to a page explaining what it is and
  how to block it, fetches `robots.txt` first and obeys it including `Crawl-delay`, waits
  between requests, reads a handful of public pages, and never requests a login, admin,
  checkout, account, `.env` or `.git` path. That is the difference between "a crawler" and
  the fact pattern in an unauthorised-access complaint.
- **Contract.** The agreement caps liability at the fee paid, makes the refund the sole
  remedy, disclaims any guarantee of legal compliance, states plainly that it is not legal
  advice, and includes indemnity, governing law, arbitration and a class-action waiver.
- **Data.** Client credentials are encrypted at rest and deleted after delivery. Snapshots
  of other people's sites are purged after 90 days. Anyone can erase everything you hold
  about them from a link in any email, or by replying "delete" — honoured immediately,
  because refusing is the actual risk.
- **Your own site.** A company that pitches accessibility from an inaccessible website is
  the easiest target in this industry, so the public pages are scanned by our own scanner
  in the test suite and must score ≥90 with no serious findings.
- **Refunds.** Undeliverable or unverified work refunds itself, which removes the
  customer-side grievance that most often becomes a claim.

**What is still on you — software cannot do these**

1. **Form an entity** and operate through it, so a claim hits the company and not you.
2. **Get errors-and-omissions / professional liability insurance** before you take the
   first payment. This is the single highest-value item on the list.
3. **Have a lawyer read** the outreach template, the report page, and the service
   agreement. The agreement in particular is a reasonable starting draft, not counsel.
4. **Keep `engine/data/assumptions.json` current.** Stale settlement figures are how an
   honest estimate becomes a deceptive claim.
5. **Watch the complaint rate.** Volume plus complaints is what turns a lawful campaign
   into a regulator's example.

`compliance-engine preflight` checks the parts of this it can see and **refuses to let
live mode send, charge, or change anything** until they pass — including your explicit
acknowledgement that items 1-3 above are done. Set those flags only when they are actually
true; lying to your own preflight defeats the purpose.

## Configuration

All settings are environment variables with the `CE_` prefix (nested with `__`), read from `.env`.
See `.env.example` for the full list. Notable ones:

| Setting | Default | Meaning |
|---|---|---|
| `CE_MODE` | `dry_run` | `live` is required for any external side effect |
| `CE_AUTONOMY__AUTO_SEND_OUTREACH` / `AUTO_REPLY` / `AUTO_SEND_CHECKOUT` / `AUTO_APPLY_FIXES` | `false` | per-stage autonomy; off = held for approval |
| `CE_PRICING__ADA_CENTS` / `AISEO_CENTS` / `BUNDLE_CENTS` | 1490 / 990 / 1990 USD | list prices |
| `CE_PRICING__FLOOR_CENTS`, `MAX_DISCOUNT_PCT` | 990, 20 | the negotiation agent can't go below `max(floor, list × (1-discount))` |
| `CE_OUTREACH__DAILY_SEND_CAP`, `FOLLOWUP_DAYS`, send window, timezone | 40, [3,7], 9-17, America/New_York | cadence |
| `CE_LLM__MODEL`, `EFFORT` | `claude-opus-5`, `medium` | model and effort for drafting/negotiation (classification runs at `low`) |
| `CE_SCANNING__MAX_PAGES_PER_SITE` | 4 | home + 3 priority pages (contact/about/services...) |
| `CE_AUTOPILOT__ENABLED` | `true` | resolve dead ends automatically instead of queueing them for you |
| `CE_LEGAL__US_ONLY` | `true` | refuse non-US recipients (CASL/GDPR are not implemented) |
| `CE_LEGAL__RESPECT_ROBOTS`, `CRAWL_DELAY_SECONDS` | `true`, 2.0 | crawler etiquette |
| `CE_LEGAL__SNAPSHOT_RETENTION_DAYS` | 90 | auto-purge saved copies of other people's sites |
| `CE_SECRETS_KEY` | *(unset)* | Fernet key encrypting client credentials; required for live mode |

## Layout

```
compliance-engine/
  engine/
    config.py  db.py  models.py  schemas.py  llm.py  exposure.py  orchestrator.py  cli.py
    autopilot.py                 what happens instead of asking you
    legal.py                     who may be contacted, crawl etiquette, credential encryption
    data/assumptions.json        sourced numbers the emails may use
    prospecting/  scanning/  outreach/  inbox/  deals/  fixing/  finance/  dashboard/
    vendor/axe.min.js            axe-core 4.10 (MPL-2.0)
  tests/                         fixture sites + end-to-end dry-run tests
  examples/leads.csv  deploy/*.service  .env.example
```

## Extending

- New lead source: implement `search(category, city, region, limit)` yielding `Prospect` in `engine/prospecting/sources.py`.
- New check: append a `Finding` in `engine/scanning/ada.py` or `aiseo.py`, add a plain-English line to `PLAIN`, and (if fixable) a transform in `engine/fixing/patches.py` keyed to the same `rule_id`.
- New apply channel: add a strategy in `engine/fixing/apply.py` and a branch in `choose_strategy`.
- Different mailbox: implement `send()` / `fetch_inbound()` in `engine/inbox/provider.py`.
