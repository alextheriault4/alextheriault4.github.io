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
| Dashboard | `engine/dashboard` | Funnel and KPIs, gates and autonomy switches, "needs a human" queue, held messages with approve/discard, lead timeline and full thread, deal and fix status, finance, pause / resume / breaker reset. Public pages: report, one-click unsubscribe, service agreement, pay, bundle download, Stripe webhook. |
| Orchestrator | `engine/orchestrator.py` | One `tick` runs every stage in order with per-lead error isolation; `run` loops forever; heartbeat on the dashboard. |

## Quick start (dry run, no keys needed)

```bash
cd compliance-engine
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium            # or set CE_SCANNING__CHROMIUM_PATH to an existing Chrome/Chromium

compliance-engine init                 # creates data/engine.db and a .env from .env.example
# edit .env: company name, legal name, postal address, website. Leave CE_MODE=dry_run.
# no ANTHROPIC_API_KEY yet? set CE_LLM__PROVIDER=fake to exercise the pipeline with canned text.

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

1. **Model.** Set `ANTHROPIC_API_KEY` (or run `ant auth login`) and `CE_LLM__PROVIDER=claude`. Default model is `claude-opus-5` with adaptive thinking, structured outputs and server-side refusal fallbacks; a refusal escalates the lead instead of retrying.
2. **Identity.** Form the entity, get the postal address you'll put in every email, write a one-page site at `CE_COMPANY__WEBSITE`, and point `CE_STRIPE__PUBLIC_BASE_URL` at wherever the dashboard's public pages are reachable (behind a reverse proxy with TLS; admin pages need the token).
3. **Payments.** Stripe account, enable Stripe Tax, set `CE_STRIPE__SECRET_KEY`, add a webhook for `checkout.session.completed` and `charge.refunded` to `/webhooks/stripe`, set `CE_STRIPE__WEBHOOK_SECRET`, then `CE_AUTONOMY__AUTO_SEND_CHECKOUT=true`.
4. **Email, last.** Buy a *separate* sending domain (never your main one), set SPF, DKIM, DMARC, a mailbox that speaks SMTP + IMAP, and make sure `reply+anything@` on that domain lands in the inbox (a catch-all or plus-addressing). Warm it up for 2-4 weeks at low volume. Then `CE_EMAIL__PROVIDER=smtp`, `CE_EMAIL__DOMAIN_VERIFIED=true`, keep `CE_OUTREACH__DAILY_SEND_CAP` small (20-40), and turn on `AUTO_SEND_OUTREACH` and `AUTO_REPLY`.
5. **Fixes.** `AUTO_APPLY_FIXES=true` lets it push to WordPress or open GitHub PRs when a client gives access (entered on the lead page). Bundle delivery needs no switch.
6. **Run it as a service.** `deploy/*.service` are systemd units for the loop and the dashboard. `/health` is the liveness check; the dashboard shows the last tick.

## What is and isn't automated (read this part)

- **Taxes.** Stripe Tax calculates and collects sales tax on each checkout. It does not register you in a state or file returns. The finance page shows taxable sales by client state so you can see where you're approaching economic-nexus thresholds; the CSV export is what your accountant (or Stripe's filing partners) needs. Income tax is yours.
- **Fixing arbitrary websites.** Fully hands-off application only exists where there is an API: WordPress (REST + application password, plus one small must-use plugin file for the site-level pieces) and Git-hosted sites (pull request). Wix, Squarespace, GoDaddy and similar builders don't expose their editors to third parties, so those clients get a bundle with exact per-platform steps and a header snippet. The delivery email offers to apply the changes if they hand over a collaborator invite; that request lands in "needs a human".
- **Content and design.** Some findings need a human decision (thin content, no phone/address on the page, HTTPS, captions, JS-only rendering). They are listed as "needs your input" in the change log, not silently ignored, and they don't count against verification.
- **Escalations.** The agents stop and ask you when: a draft fails lint, a reply is hostile/threatens legal action/unclear, a prospect asks for something outside the packages, a redirect has no forwarding address, a fix build fails, or a delivered fix never verifies within 45 days. Expect a few per hundred leads.
- **Deliverability.** The circuit breaker pauses cold sends when bounces exceed 5% or complaints 0.2% (tunable). A tripped breaker stays tripped until you reset it on the dashboard.

## The legal shape of this

This is a legitimate service category, but the pitch pattern ("you could be sued") has attracted
regulators, so the engine is built to stay on the right side of it:

- **CAN-SPAM** (B2B cold email is legal in the US when compliant): honest From and subject, physical postal address, working opt-out honoured immediately (link, one-click `List-Unsubscribe-Post`, or the word "unsubscribe" in a reply), no further mail after opt-out, and a stated reason for the contact. All enforced in code, not just prompts.
- **FTC deception rules.** The FTC's 2025 order against accessiBe was about overstated compliance claims. The lint forbids "guarantee", "certified", "fully compliant", "avoid lawsuits", fines, penalties, urgency, and any dollar figure the model made up. The email and report say *estimate* and link the sources in `engine/data/assumptions.json`. Keep that file current.
- **No legal advice.** The service agreement (`/agreement/<deal>`) states scope, refund terms and that nothing here makes a site immune from complaints.
- **Verification-backed refund.** If the rescan doesn't show the reported issues resolved, the client gets a refund. It keeps the promise concrete and keeps you honest.

Have a lawyer read the outreach template, the agreement and this section before going live.
Non-US recipients bring GDPR/PECR/CASL rules that this engine does not attempt; keep prospecting to the US.

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

## Layout

```
compliance-engine/
  engine/
    config.py  db.py  models.py  schemas.py  llm.py  exposure.py  orchestrator.py  cli.py
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
