# The brief

Everything someone needs to build this business from nothing: what the owner asked for, in
his words and then extracted as requirements; what exists today and why it is shaped that
way; every judgement call that was got wrong first and then corrected; and the order to
build it in if you were starting again on an empty directory.

If you only read one other file, read `README.md`. This one is the *why*; that one is the
*what*. `TESTING.md` is the runbook, `STANDARDS.md` is the checklist, `MARKET.md` is the
market estimate.

**Status as of this writing:** complete and tested, never yet pointed at a real stranger.
137 tests pass. ~9,800 lines of engine code, ~2,700 of tests. Nothing has been sent, charged
or fixed for a real customer, because the owner's stated order is *prove it works, then buy
the domain and mailbox*.

---

## 1. The idea in one page

Almost every small-business website fails accessibility standards, and almost none are
written in a way that AI assistants can read and cite. Both are fixable, both are worth
money to the owner, and neither is something a plumber or a dentist is going to do
themselves.

So: find those sites automatically, prove the problem with an actual scan of their actual
website, email the owner a short honest note with the numbers, answer their reply, take
payment, fix the site, verify the fix, and then keep it fixed for a small monthly fee. Every
step runs without a human. The operator watches a dashboard.

The money: **$99 to fix it, then $9.99/month to keep it fixed.** The one-off fix is also
$99. First year: $218.88. That price is set against what the customer's real alternative
costs them — nothing, or an afternoon of their own time — not against what the work is
worth.

Why it can work at all: the scan is free to run, the fix is mostly mechanical, and the
delivery path for the best segment (sites hosted from a public GitHub repository) needs no
credentials from the customer at all — we fork, open a pull request, they press Merge.

---

## 2. What the owner asked for, verbatim

These are the seven requests that produced everything in this repository, in order. They are
quoted in full because paraphrasing them loses the parts that turned out to matter most.

> **1.** "I want to make a company that automatically finds websites that aren't ada
> compliant or seo (ai specifically) optimized or both, reaches out to them explaining that
> their company specializes in this stuff for a decent price, then sees responses and emails
> back until the companies with the noncompliant websites accept the deal, then goes in and
> fixes their website for them. This should be completely automated and after setting it up
> I shouldn't have to touch it. This would obviously work best if targeting small companies.
> The email should include how much it would cost if they got sued for not being ada
> complaint or how much they are losing by not being ai search optimized, and then the fee
> seems small compared to that. The ai would also have to automate collecting money and
> taxes and all that stuff (maybe one master agent controlling a bunch of smaller ones) but
> I would also need visibility into it to make sure it's working as expected. I can get
> emails and domains but that should be the last step once everything else is proven to
> work"

> **2.** "Can we make it so it's connected to my Claude code credits. And let's make it
> escalate to me as little as possible. Make sure there's no way I get sued"

> **3.** "It shouldn't auto refund that should at least go to me. And then give me an exact
> step by step list of what to do to test this live on my own website and email so I can see
> what it does and the visibility as well"

> **4.** "Okay let's make sure we are doing everything correctly and maybe generate an exact
> list of things to check for for both ada compliance and seo optimization (we could use
> this for any website we make too) and this could be used to calculate percentages of how
> compliant or optimized a website is when we reach out to them. And if it makes sense to do
> a retainer instead of (or in addition to a lower) one time fee then make that
> possible/the main option as well (or give options, whatever you think is best). And again
> make sure this is completely automated"

> **5.** "Okay let's make it $9.99 a month and $499 up front (again make sure the outreach
> tells them how much they stand to gain/save with these services) and let's start outreach
> to only sites we know we can change for them (GitHub and whatever). And it should
> automatically tell a paying customer (in as easy a way for them as possible) how to make
> it so that the service can update their website for them. And the one off should be just
> $499 since it's essentially the same as the subscription if they dont update their website
> that much. And these are small companies so let's keep the cost down. And does the
> recurring check also update if any new rules/seo strategies come out? It should and that
> should be stated as part of the package."

> **6.** "Can we actually make it $99 this should be a low enough price where people buy it
> instead of doing it themselves. And do a quick scan online to estimate how many websites
> this would actually find per day. And the pricing strategy should be able to change if
> nobody is buying it. And get rid of any stale background tasks"

> **7.** "okay so merge everything and then give me an exact step-by-step to get this tested
> on my own website with my email and then going"

**Supersessions.** Request 6 replaces the `$499` in request 5 with `$99`. Nothing else has
been superseded. If you are rebuilding, build $99; the $499 number appears nowhere in the
code any more and should not come back.

---

## 3. The requirements, extracted

Hard requirements. Each one is a thing that must be true of any rebuild, with where it
currently lives.

| # | Requirement | Where it lives now |
|---|---|---|
| R1 | Find small-business websites automatically | `engine/prospecting/sources.py` — OpenStreetMap (free, no key), Google Places (better, needs key), CSV |
| R2 | Detect ADA/WCAG failures on their real site | `engine/scanning/ada.py` + vendored axe-core, real headless Chromium |
| R3 | Detect AI-search/LLM-readability failures | `engine/scanning/aiseo.py` — structured data, crawlability by AI agents, answerable content, `llms.txt` |
| R4 | Either problem, or both, qualifies a lead | `engine/scanning/runner.py` `classify_after_scan` |
| R5 | Cold-email the owner explaining what we do | `engine/outreach/compose.py` |
| R6 | The email must state what a lawsuit would cost them, or what they lose from AI-search invisibility, so the fee looks small next to it | `engine/exposure.py` `value_case()`, every figure sourced in `engine/data/assumptions.json` |
| R7 | Read replies and keep negotiating until they accept | `engine/inbox/handle.py`, `engine/inbox/negotiate.py` |
| R8 | Collect money, and taxes | Stripe Checkout + Stripe Tax, `engine/deals/checkout.py`, `engine/finance/ledger.py` |
| R9 | Actually go in and fix their website | `engine/fixing/` — build patches, apply via GitHub PR or WordPress REST, verify with a rescan |
| R10 | Completely automated; owner should not have to touch it after setup | `engine/orchestrator.py` (the master loop) + `engine/autopilot.py` (every dead end has an automatic answer) |
| R11 | Target small companies | Chain/brand/aggregator domains dropped in `sources.py`; category lists are small-business trades |
| R12 | "One master agent controlling a bunch of smaller ones" | `Orchestrator.tick()` runs each stage in order, each isolated so one lead's failure cannot stall the rest |
| R13 | Visibility — the owner must be able to confirm it is working | FastAPI dashboard, `engine/dashboard/` — funnel counts, every lead, every email with its lint result, finance, notices, pricing |
| R14 | Email and domains are the **last** step, after everything else is proven | Console email provider + `dry_run` mode are the defaults; SMTP/IMAP is opt-in and gated by preflight |
| R15 | Bill work to the Claude subscription, not a metered API key | `engine/llm.py` `ClaudeCodeLLM` — shells out to the `claude` CLI headless with `ANTHROPIC_API_KEY` stripped |
| R16 | Escalate to the owner as little as possible | `engine/autopilot.py` — every path that would once have said "a human should look at this" now has a safe automatic resolution |
| R17 | "Make sure there's no way I get sued" | `engine/legal.py` + `engine/outreach/compliance.py`. See §4 for what this can and cannot mean |
| R18 | Refunds are **never** automatic — they come to the owner | `DealStatus.REFUND_REQUESTED`, dashboard approval queue, `compliance-engine refunds --approve/--decline`. The single human gate in the system |
| R19 | An exact step-by-step to test it live on the owner's own website and mailbox | `TESTING.md`, parts 1–2 |
| R20 | An exact checklist of ADA + SEO items, reusable for any website | `engine/standards/checks.py`, published as `STANDARDS.md` — 80 checks (46 ADA, 34 SEO) |
| R21 | That checklist must produce a compliance/optimisation **percentage** for outreach | `engine/standards/scoring.py` — earned weight ÷ applicable weight |
| R22 | A retainer, as the main offer | `engine/plans.py` — `care` is recommended, `fix_only` is the alternative |
| R23 | Outreach must say what they stand to gain or save | `value_case()` figures are in the email context and the prompt requires their use |
| R24 | Only contact sites we can actually change | `engine/fixability.py` + `CE_PROSPECTING__REQUIRE_FIXABLE=true`; anything else is marked `not_fixable` and never emailed |
| R25 | After payment, automatically tell the customer how to grant access, as easily as possible | `engine/onboarding.py` + the public `/setup/<token>` page |
| R26 | The one-off costs the same as the retainer's up-front fee | Both `$99`; charging more for identical work would be a penalty for not subscribing |
| R27 | Keep the cost down — these are small companies | $99 + $9.99/mo; the whole first year is $218.88 |
| R28 | The monthly check must also cover **new** rules and SEO strategies, and that must be stated in the package | Versioned checklist (`CHECKLIST_VERSION`, `since=` on every check); the care cycle detects a client last measured against an older edition and reports the new checks, fixing what it can, at no extra charge. Stated in the plan's `includes`, the agreement and the terms |
| R29 | $99 specifically, low enough that buying beats doing it themselves | `PricingSettings.care_setup_cents = 9_900` |
| R30 | Estimate how many websites this finds per day | `tools/estimate_market.py` → `MARKET.md` |
| R31 | The pricing strategy must be able to change if nobody is buying | `engine/pricing.py` — a price ladder that moves itself on measured conversion |
| R32 | A step-by-step for going live to real businesses | `TESTING.md` part 3 |

### Preferences and defaults that were chosen, not demanded

These were judgement calls made inside the requirements. A rebuild can change them, but each
was chosen for a reason worth knowing.

- **SQLite, one file, WAL mode.** One operator, one machine, tens of thousands of rows. A
  Postgres dependency would buy nothing and cost setup.
- **No queue, no workers, no containers.** One `tick()` every five minutes does every stage.
  The whole thing runs as two systemd units.
- **Plain HTML dashboard, server-rendered Jinja.** No build step, no framework. The operator
  looks at it twice a week.
- **The model writes words; the code owns numbers.** No price, no dollar figure and no
  status transition is ever decided by the LLM. Prices are clamped in code after the model
  replies. Every dollar figure in an email must appear in a pre-approved list or the lint
  rejects the draft.
- **Two plans, not a grid.** A small business does not want to compare five tiers.
- **US-only.** CAN-SPAM is a notice-and-opt-out regime and is implementable. CASL and
  GDPR/PECR are consent regimes this engine does not implement, with penalties in the
  millions.
- **Everything generated is regenerated, not maintained.** `STANDARDS.md` comes from the
  check registry and `MARKET.md` from the estimator, each with a `--check` mode wired into
  the test suite, so documentation cannot drift from code.

### Explicit non-goals

- Not a compliance certification, not legal advice, not an accessibility overlay.
- No Wix, Squarespace, GoDaddy, Weebly or Duda customers — no third-party editing API
  exists, so the fix could only be a zip file and instructions, which is not what the email
  promises. This costs about two fifths of the market on purpose.
- No phone calls, no CRM, no sales team, no human in the loop except refunds.
- Not multi-tenant, not a SaaS product for other agencies.

---

## 4. The standing constraints

Things that must not regress. If a change would break one of these, the change is wrong.

1. **Refunds never move money without the owner.** Everything else may resolve itself.
2. **Never claim legal compliance.** Not "compliant", not "certified", not "protected", not
   "you will be sued". The FTC's order against accessiBe is the precedent for why
   overstating an accessibility product is an enforcement risk, not just a bad look. The
   score is described as *automated conformance against the checks that apply to this site*,
   in those words, in the report.
3. **Never send a dollar figure the code did not authorise.** The lint enforces this.
4. **Never email anyone whose site we could not actually fix.**
5. **Never re-price someone who already has a quote or a subscription.**
6. **Never scan like an attacker.** Identified user agent pointing at a page explaining the
   bot, `robots.txt` obeyed, crawl delay, a handful of pages.
7. **Never store a client credential unencrypted**, and delete it once the work is
   delivered.
8. **The go-live gates stay shut until preflight passes.** Live mode without an entity,
   insurance, lawyer review and an encryption key is refused by the code, not by a comment.

On "make sure there's no way I get sued": that is not a promise any code can keep, and the
repository says so plainly rather than pretending. What it does is remove the specific,
known ways businesses in this niche get sued or fined — contacting people outside CAN-SPAM's
reach, cold-emailing plaintiff-side professions, crawling aggressively, making claims you
are not licensed to make, holding credentials badly, and taking money for work you cannot
deliver. The remaining exposure is ordinary business exposure, which is what the entity, the
insurance and the lawyer review in preflight are for.

---

## 5. What exists today

```
compliance-engine/
  engine/
    orchestrator.py        the master loop: one tick runs every stage, each isolated
    config.py              every setting, env-driven, safe defaults (dry run, all gates off)
    db.py                  SQLite schema + migrations; leads, scans, findings, messages,
                           deals, fixes, ledger, suppression, events, kv
    llm.py                 three providers: claude_code (subscription), claude (API), fake
    models.py schemas.py   status enums and the structured outputs the model must return
    legal.py               who may be contacted, crawl etiquette, credential encryption
    autopilot.py           what happens instead of asking the owner
    exposure.py            the dollar figures, all sourced
    standards/checks.py    THE CHECKLIST — 80 checks, the source of truth
    standards/scoring.py   earned weight over applicable weight
    plans.py               the two plans and the negotiation floors
    pricing.py             the price ladder; moves the price on measured conversion
    fixability.py          can we actually change this site, decided during the scan
    onboarding.py          the moment they pay: the shortest access path they can take
    care.py                the monthly retainer cycle
    prospecting/ scanning/ outreach/ inbox/ deals/ fixing/ finance/ dashboard/
    data/assumptions.json  every number an email is allowed to cite, with its source
    vendor/axe.min.js      axe-core 4.10.3 (MPL-2.0)
  tests/                   137 tests, including fixture websites served over real HTTP
  tools/generate_standards.py   writes STANDARDS.md from the registry
  tools/estimate_market.py      writes MARKET.md from the funnel model
  README.md TESTING.md STANDARDS.md MARKET.md BRIEF.md
```

### The pipeline, end to end

1. **Prospect.** Category + city → OpenStreetMap or Google Places → businesses with a
   website. Chains, aggregators and social pages dropped.
2. **Gate.** `legal.check_lead` drops non-US, excluded trades (law, government, schools,
   medical-adjacent, firearms, gambling, and the rest), `.gov/.mil/.edu`, and anything on
   the suppression list. Exclusions are recorded, not silently discarded.
3. **Scan.** Headless Chromium, `robots.txt` first, up to four pages. axe-core for WCAG 2.2
   A/AA plus the engine's own checks; the AI-search checks in parallel. Produces two
   percentages, a findings list, an exposure estimate, and a **fixability verdict**.
4. **Qualify.** Too good to pitch → `clean`. No contact address → `no_contact`. Can't change
   it → `not_fixable`. Otherwise → `scanned`, ready for outreach.
5. **Draft.** The model writes five short paragraphs from a context object containing only
   approved facts and figures. The compliance lint checks it. A draft that fails is repaired
   by feeding the lint's own complaints back; if that fails twice, a fixed template built
   only from pre-approved sentences is used instead. The price is pinned to the lead here.
6. **Send.** Weekday send window, daily cap, per-domain cooldown, bounce/complaint circuit
   breaker, RFC 8058 one-click unsubscribe, CAN-SPAM footer with the real postal address.
7. **Reply.** IMAP poll, thread matched by plus-address token or `In-Reply-To`, intent
   classified by a cheaper model, then: unsubscribe is instant and permanent; hostile gets
   one stand-down and permanent suppression; unclear gets one clarifying question and then a
   polite close; out-of-scope gets a plain "we only sell the standard packages"; everything
   else goes to the negotiation agent, which may discount only within the code's floors.
8. **Close.** Explicit acceptance only — the model cannot decide a deal is closed. Stripe
   Checkout in subscription mode puts the setup fee and the recurring fee on one page, with
   Stripe Tax computing sales tax.
9. **Onboard.** Payment lands → a welcome email with the shortest access path: nothing at all
   for a known GitHub repo, one pasted repository address otherwise, four clicks for a
   WordPress application password. One reminder at two days; at three days the engine stops
   waiting and delivers the finished files rather than let paid work sit behind a form.
10. **Fix.** Patches built per finding; applied as a GitHub pull request from a fork (nothing
    on their site changes until they press Merge) or through the WordPress REST API.
11. **Verify.** Rescan, before/after report, both scores.
12. **Care.** Every month: rescan, diff against last cycle, fix regressions, cover new pages,
    apply any checks added to the checklist since they were last measured, send a short
    report. One click to cancel, honoured immediately.
13. **Price.** Every tick, the engine asks whether the current price is still right.

### The parts that are unusual, and why

**The checklist is the product's spine.** 80 checks, each with a weight, an area, a
detection method (automated / heuristic / needs a person), a plain-English "why it matters",
and whether it is auto-fixable. A score is `earned weight ÷ applicable weight` over the
checks that *apply to that site*, with manual and undecidable items excluded from both sides
— which is what makes the percentage honest enough to put in a cold email. `STANDARDS.md` is
generated from the registry, so it can never describe a check the scanner does not run.

**The checklist is versioned** (`CHECKLIST_VERSION`, a `YYYY.MM` edition; every check records
the edition that introduced it; every scan is stamped with the edition it used). That is what
makes R28 real rather than a marketing line: the care cycle can see that a client was last
measured against an older list, name the new checks in their monthly report, and fix what is
auto-fixable — at no extra charge, as the package says.

**Fixability is decided from evidence during the scan**, not guessed at sale time. Response
headers and hostnames identify GitHub Pages, Netlify, Vercel and Cloudflare Pages; the
WordPress REST API is probed directly; site builders are recognised by platform fingerprint.
`direct` may be pitched; `assisted` and `unknown` may not.

**The GitHub path needs nothing from the customer.** Fork the public repo, commit, open a
pull request with `maintainer_can_modify`, explain every change, and let them press Merge.
No token, no password, no access granted, no risk to them. This is why GitHub-hosted sites
are the best first market even though they are a small share of it.

**The autopilot's job is to make "needs a human" stay at zero.** Every branch that could
escalate has a safe automatic answer instead, and the resolution is written to the notices
feed so the owner can read what was decided without having decided it.

**Pricing moves itself.** A ladder of price points ($199/$149/$99/$79/$49, each with its own
monthly). The current rung is scored on emails actually delivered at it and sales that came
back. After a fair trial (60 emails, 14-day minimum) under 0.4% conversion steps down; 4% or
better steps up. The rung is stamped on each lead the first time we write to them, so a move
can never change a quote already given, and Stripe holds an existing subscription's price so
no customer is ever re-priced. At the bottom rung it stops and says the problem is the
message or the market, rather than looping downward forever.

---

## 6. Problems hit, and how they were fixed

This is the section that saves a rebuild the most time. The bugs are ordinary; the judgement
errors are the expensive ones, because each looked correct until someone asked what the
customer would experience.

### A. Judgement errors — caught in review, not by a test failure

**A1. Refunds were automatic.** The first build refunded undeliverable work on its own,
which reads as tidy automation and is actually the one irreversible, money-losing action in
the system. *Fixed:* a `refund_requested` state, an approval queue on the dashboard, and
`refunds --approve/--decline`. The owner asked for this explicitly; if they had not, it
would still have been wrong.

**A2. The scores were flattering.** axe-core buckets results into violations, passes,
incomplete and inapplicable. Counting only violations against a fixed denominator produces a
number that is technically derived and practically meaningless — and it would be in a cold
email to a stranger. *Fixed:* weighted scoring with an honest denominator, checks that do
not apply excluded from both sides, manual checks excluded entirely and reported separately.

**A3. A newly-added checklist check was reported as a regression.** After the checklist was
versioned, a client's monthly report said "1 thing slipped since last month" about a check
that did not exist last month. That is a false statement to a paying customer. *Fixed:*
new-edition checks are excluded from the regression set and get their own paragraph that
says what changed in the checklist and that there is no extra charge.

**A4. We were pitching sites we could not fix.** Nothing stopped outreach to a Wix site, and
the only possible delivery would have been a zip file and instructions — not what the email
promised. *Fixed:* the fixability gate, on by default.

**A5. Any site behind Cloudflare looked "directly fixable".** The host fingerprints matched
the `cf-ray` header as evidence of Cloudflare Pages. `cf-ray` is on *every* site behind
Cloudflare's CDN — a large fraction of the web, Wix and Squarespace included — so the gate
in A4 was letting through exactly the sites it existed to exclude. *Fixed:* Git-backed
hosting is recognised from the hostname (`.pages.dev`, `.netlify.app`, `.vercel.app`,
`.github.io`) and from Netlify's and Vercel's own distinctive headers; the site-builder check
now runs before any host check, because Wix behind a CDN is still Wix.

**A6. A price change would have moved a quote already given.** Once pricing could move on
its own, a prospect who replied three weeks later would have been quoted from today's ladder,
and the negotiation floor could even have clamped their price *upward* past what the first
email said. *Fixed:* the rung is pinned on the lead at first contact and every later step
reads the pin. Paid deals carry their own price on the deal row, and Stripe holds the
subscription price, so those were already safe — but the in-flight conversation was not.

**A7. The one-off was priced higher than the retainer's setup fee.** The reasoning was that a
one-off has to carry its own acquisition cost. The customer's reading is that they are being
charged more for the same work because they said no to a subscription. *Fixed:* both $99.

**A8. The negotiation floor was $79.20.** 20% off $99 is arithmetically right and is not a
price anyone quotes. *Fixed:* computed floors round *up* to whole dollars, which also keeps
them above the discount policy's limit.

**A9. The test suite was about to disable the fixability gate.** Adding the gate broke
unrelated tests, because the fixture HTTP server sent no host headers, so every fixture site
was `not_fixable`. The quick fix was `require_fixable=False` in the test settings — which
would have meant the production path was never exercised. *Fixed:* the fixture server
advertises `Server: GitHub.com`, and a second fixture was added on a deliberately unhostable
host so the gate's rejection path is tested too.

**A10. Cold outreach from a personal Gmail.** Fine for testing, wrong for production: it gets
filtered, and a spam complaint against a personal address is not undoable. *Fixed:* in
documentation, with a warm-up ramp (10 → 20 → 40 per day) and the catch-all reply address
tested before any stranger is contacted.

### B. Bugs

**B1. `NameError` in the negotiation fallbacks.** Both exception handlers referenced
undefined names (`package.value`, `current`), so the first time the model refused or errored,
the error handler would itself have crashed. Never triggered in tests because the fake model
never refuses. *Fixed:* a `_stand_down()` helper that builds a valid reply from the values
actually in scope. **Lesson: exercise your error paths, or read them adversarially.**

**B2. Raw JSON out of SQLite.** `db.one("SELECT * FROM scans …")` returns the stored JSON
columns as strings, while `db.latest_scan()` decodes them. A test using the former got
`AttributeError: 'str' object has no attribute 'get'`. *Fixed:* use the decoding accessor;
the lesson is to have exactly one way to read a row.

**B3. Test helper reused domains across price points.** Two calls to the "these leads were
emailed at price X" helper created the same lead domains, so the second silently re-priced
the first and the conversion maths was wrong. *Fixed:* namespace the fixtures by price point.
**A failing assertion in a test can be the helper lying, not the code.**

**B4. A tautological assertion.** `body["head"] == "us:" + body["head"].split(":")[1]` cannot
fail. *Fixed:* `body["head"].startswith("us:")`. Worth grepping for this shape.

**B5. Hardcoded prices in tests and emails.** A `$9.99` literal in the welcome email and
`$499` literals across three tests all broke on the reprice. *Fixed:* every one derives from
settings now, so the next reprice touches one file.

**B6. Time arithmetic against a fabricated "now".** A test passed a fixed `NOW` in the past
while the price point's `since` was real wall-clock time, producing negative elapsed days and
a nonsense "next move in 204 days". *Fixed:* the test sets both. Production is unaffected —
`since` is always in the past — but it is a real trap for any time-based logic.

**B7. Import and API drift in tests** — `engine.utils` does not exist (`utcnow` lives in
`db.py`), `db.events_for_lead()` and `db.all()` never existed, the column is
`needs_human_reason` not `status_reason`, and a fixture returns `(db, lead_id, deal_id)` not
`(db, deal, lead_id)`. All trivial, all cost time.

### C. Environment traps

**C1. Claude Code must not see an API key.** The whole point of `claude_code` as a provider
is that it bills the subscription. The child process inherits the environment, so
`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are explicitly stripped before spawning it —
otherwise the CLI silently uses the key and the bill arrives metered.

**C2. Keep the cached prefix small and byte-identical.** The headless CLI is started with a
replaced system prompt and no tools, MCP servers or project settings. Measured cost: about
$0.28 of quota on the first call and about $0.017 on every call after, because the prefix
becomes a cache read. Letting the real system prompt and tool definitions through makes every
call a cache miss.

**C3. Subscription usage limits are a normal condition, not an error.** `LLMCapacityError` is
distinct from `LLMError`: a capacity problem defers the lead for an hour and the loop carries
on. Treating it as a failure would burn retries and mark good leads dead.

**C4. Two concurrent pytest runs starve each other.** Both runs launch Chromium; the machine
had nothing left. One run at a time.

**C5. Playwright in a preprovisioned container.** Chromium already exists at
`/opt/pw-browsers/chromium` with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`. Running
`playwright install` re-downloads it and can exhaust the disk allowance.

---

## 7. What is deliberately not built, and what is still unproven

Be honest with whoever picks this up.

- **Never sent to a real stranger.** Every email so far went to the operator's own mailbox
  behind a hard allowlist. The reply rate, the complaint rate and the conversion rate are all
  estimates from published benchmarks, not measurements.
- **The contact-address rate is the softest number in the model** (assumed 45%). It gates the
  whole funnel and will be the first thing real data corrects.
- **No delivery route for site builders.** Two fifths of the market is excluded. A manual or
  semi-manual route for Wix/Squarespace would move the funnel more than any amount of extra
  prospecting — and would need a different promise in the email.
- **Deliverability is unproven.** No domain has been warmed. The circuit breaker will stop
  sending on a bad bounce or complaint rate, which is protection, not evidence.
- **Stripe has only run in test mode.** Tax registration and nexus are the operator's to set
  up; the engine asks Stripe to compute tax and never invents a rate.
- **The legal posture is risk reduction, not immunity.** Preflight refuses live mode until
  the entity, the insurance and the lawyer review are attested, and those attestations are
  the operator's word, not a verification.
- **Subscription terms.** Running a commercial service on a Claude subscription intended for
  interactive use is a question for Anthropic's terms. The code makes switching to a metered
  API key a one-line config change for exactly this reason.

---

## 8. If you were rebuilding from zero

The order matters. Each step is testable before the next exists, and the expensive judgement
calls come early rather than being retrofitted.

1. **The checklist first.** Before any scanning code, write the registry: every check, its
   weight, its area, how it is detected, why it matters, whether it can be auto-fixed.
   Generate the human-readable document from it. Everything downstream — the score, the
   report, the fix, the monthly cycle — is a function of this list, and retrofitting weights
   or a `since=` field later means rewriting all of it.
2. **Scoring, with an honest denominator.** Decide what "92% compliant" means before anything
   puts that number in an email.
3. **Config and the database.** Every setting env-driven, defaults safe (dry run, gates off,
   console email). Migrations from the first commit.
4. **The scanner.** Real browser, real `robots.txt`, fixture sites served over real HTTP in
   the tests — one deliberately broken, one that scores 100/100.
5. **Fixability, at the same time as the scanner.** If it comes later, you will have built an
   outreach pipeline that promises things you cannot deliver, and every later feature has to
   be retrofitted with the gate.
6. **The exposure model, with sources in a data file.** Not in prose, not in prompts. If a
   number cannot be cited, it cannot be in an email.
7. **The lint before the email writer.** Write the thing that rejects bad drafts first, then
   the thing that writes them. It changes what you ask the model for.
8. **Outreach, then inbox, then negotiation** — with the rule that the model writes words and
   the code owns numbers and state transitions, from the first line.
9. **Deals and Stripe.** Subscription mode with a setup fee, Stripe Tax on, webhook-driven.
   Refunds behind human approval from the start.
10. **The fixer.** GitHub PR path first — it is the one that needs nothing from the customer.
11. **The orchestrator and the dashboard together.** An automated pipeline you cannot see is
    not finished.
12. **The autopilot last-but-one.** Walk every branch that says "a human should look at this"
    and give it a safe automatic answer.
13. **Pricing that moves itself, last.** It needs conversion data, which needs everything
    above.

Two rules that paid for themselves repeatedly:

- **Generate every document from the code, with a `--check` mode in the test suite.** Docs
  that can drift, will.
- **Make the test fixtures realistic rather than relaxing the production settings to suit
  them.** Every time a new gate broke tests, the right fix was a better fixture.

---

## 9. Reference

**Commands.** `init`, `add-leads`, `prospect`, `scan`, `draft`, `send`, `tick`, `run`,
`dashboard`, `status`, `preflight`, `pricing`, `secret`, `notices`, `refunds`,
`simulate-reply`, `simulate-payment`, `erase`, `export-ledger`.

**The settings that change the business**, all `CE_`-prefixed:
`PRICING__CARE_SETUP_CENTS` (9900), `PRICING__CARE_MONTHLY_CENTS` (999),
`PRICING__ADAPTIVE` (true) and the ladder, `PRICING__CLEAN_ADA_PERCENT` / `CLEAN_SEO_PERCENT`
(the bar above which a site is left alone), `OUTREACH__DAILY_SEND_CAP` (40),
`PROSPECTING__REQUIRE_FIXABLE` (true), `LEGAL__ONLY_EMAIL_ADDRESSES` (the self-test rail),
`AUTONOMY__*` (four switches, all off by default), `LLM__PROVIDER` (`claude_code`).

**The four flags that gate live mode**, checked by `preflight`: entity formed, liability
insurance, agreement reviewed by a lawyer, `CE_SECRETS_KEY` set. They are attestations — the
code records that you say they are true.

**Tests:** 137, about five minutes, no keys or network needed. They include a self-audit
(`test_self_audit.py`) that runs our own scanner over our own public pages — a company that
cold-emails small businesses about inaccessible websites, from an inaccessible website, is
the easiest target in this industry — and two freshness tests that fail if `STANDARDS.md` or
`MARKET.md` drifts from the code.

**Numbers worth remembering:** 80 checks (46 ADA, 34 SEO, 48 auto-fixable). ~6% of business
listings become a mailable, fixable lead. 40 emails/day needs ~650 listings/day. At published
benchmarks that is 2–12 sales a month at the cap. First-year revenue per customer: $218.88.
