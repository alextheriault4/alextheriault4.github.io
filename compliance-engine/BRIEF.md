# Build this: an automated ADA + AI-search remediation business

**This document is the whole specification.** It is written to be handed to someone with no
access to the existing code. Everything needed to rebuild the business from an empty
directory is here: what the owner asked for in his own words, the requirements extracted
from that, the data model, the 80-point checklist in full, the scoring arithmetic, the
dollar figures and their sources, the exact word lists that keep the emails lawful, the
pricing algorithm, the build order, and — most valuable — the mistakes already made and
corrected, so they do not have to be made twice.

A working implementation exists (Python, ~9,800 lines, 137 passing tests, never yet pointed
at a real stranger). You are not expected to match it line for line. You are expected to end
up with something that satisfies §3, honours §5, and does not repeat §26.

---

## Contents

**Part I — the business**
1. The idea in one page · 2. The owner's requests, verbatim · 3. Requirements ·
4. Preferences and non-goals · 5. Constraints that must never regress

**Part II — the specification**
6. System shape · 7. Data model · 8. The checklist and the score · 9. The scanner ·
10. The exposure model · 11. Pricing · 12. Outreach · 13. Replies and negotiation ·
14. Money · 15. Can we even fix it · 16. Onboarding · 17. The fixer · 18. The care cycle ·
19. The autopilot · 20. Legal and safety · 21. Visibility · 22. Configuration

**Part III — building it**
23. Stack · 24. Build order · 25. Testing · 26. Problems already hit and how they were
fixed · 27. Runbook · 28. What is unproven · 29. Market model · 30. Done means

---

# Part I — the business

## 1. The idea in one page

Almost every small-business website fails accessibility standards, and almost none are
written so AI assistants can read and cite them. Both are fixable, both cost the owner
money, and neither is something a plumber or a dentist will do themselves.

So: find those sites automatically, prove the problem by scanning their actual website,
email the owner a short honest note with the numbers, answer their reply, take payment, fix
the site, verify the fix, then keep it fixed for a small monthly fee. Every step runs
without a human. The operator watches a dashboard.

**The price: $99 to fix it, then $9.99/month to keep it fixed.** The one-off fix is also
$99. First year: $218.88. That price is set against the customer's real alternative —
doing nothing, or spending an afternoon on it — not against what the work is worth.

Why it can work: the scan costs nothing to run, the fix is mostly mechanical, and for the
best segment (sites served from a public GitHub repository) the delivery path needs no
credentials from the customer at all — you fork the repo, open a pull request, they press
Merge.

Why it might not: see §28. Nothing here has been sent to a real stranger yet.

## 2. The owner's requests, verbatim

Seven requests produced the entire design. They are quoted in full because paraphrase loses
the parts that turned out to matter most. Read them before the requirements table — the
requirements are derived from these, and where the two disagree, these win.

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

**Supersession:** request 6 replaces the `$499` in request 5 with `$99`. Build $99. Nothing
else has been superseded.

## 3. Requirements

Every one of these must be true of the finished system.

| # | Requirement |
|---|---|
| R1 | Find small-business websites automatically, by trade and city |
| R2 | Detect real ADA/WCAG failures on their real site, with a real browser |
| R3 | Detect AI-search and LLM-readability failures |
| R4 | Either problem, or both, qualifies a lead |
| R5 | Cold-email the owner explaining what we do |
| R6 | The email must state what a lawsuit would plausibly cost them, **or** what they are losing by being invisible to AI search, so the fee looks small next to it |
| R7 | Read the replies and keep negotiating until they accept |
| R8 | Collect the money, and the sales tax |
| R9 | Actually go in and fix their website |
| R10 | Completely automated: after setup the owner should not have to touch it |
| R11 | Target small companies, not chains |
| R12 | A master agent controlling smaller ones — one loop driving isolated stages |
| R13 | The owner needs visibility: he must be able to confirm it is working as expected |
| R14 | Real email and domains are the **last** step, after everything else is proven |
| R15 | Bill the model work to the owner's Claude subscription, not a metered API key |
| R16 | Escalate to the owner as little as possible |
| R17 | Remove every avoidable way the owner gets sued |
| R18 | **Refunds are never automatic.** They come to the owner for approval |
| R19 | An exact step-by-step for testing live on the owner's own website and mailbox |
| R20 | An exact checklist of ADA + SEO items, reusable for any website he builds |
| R21 | That checklist must produce a compliance/optimisation **percentage** usable in outreach |
| R22 | A retainer, as the main offer |
| R23 | Outreach must say what they stand to gain or save |
| R24 | Only contact sites we know we can change for them |
| R25 | After payment, automatically tell the customer how to grant access — as easily as possible for them |
| R26 | The one-off costs the same as the retainer's up-front fee |
| R27 | Keep the cost down; these are small companies |
| R28 | The monthly check must also apply **new** rules and SEO strategies as they appear, and that must be stated as part of the package |
| R29 | $99 up front — low enough that buying beats doing it themselves |
| R30 | An estimate of how many websites this actually finds per day |
| R31 | The pricing strategy must be able to change if nobody is buying |
| R32 | A step-by-step for going live to real businesses |

## 4. Preferences, defaults and non-goals

**Chosen, not demanded.** Each is changeable, but know why it was picked.

- **One SQLite file, WAL mode.** One operator, one machine, tens of thousands of rows. A
  database server would buy nothing and cost setup.
- **No queue, no workers, no containers.** One loop every five minutes runs every stage.
  Two systemd units is the whole deployment.
- **Server-rendered HTML dashboard.** No build step, no framework. It is looked at twice a
  week.
- **The model writes words; the code owns numbers and state.** No price, no dollar figure,
  no status transition is ever decided by the language model. See §12 and §13 — this is the
  single most load-bearing design rule in the system.
- **Two plans, not a pricing grid.** A small business will not compare five tiers.
- **US-only.** CAN-SPAM is notice-and-opt-out and is implementable by a machine. Canada's
  CASL and the EU/UK's GDPR/PECR are consent regimes this does not implement, with penalties
  in the millions.
- **Every generated document is regenerated from code, with a `--check` mode wired into the
  test suite.** Docs that can drift, will.

**Non-goals.** Not a certification, not legal advice, not an accessibility overlay. No Wix,
Squarespace, GoDaddy, Weebly or Duda customers (no third-party editing API exists — see
§15). No phone calls, no CRM, no salespeople. Not multi-tenant, not a product for other
agencies.

## 5. Constraints that must never regress

If a change would break one of these, the change is wrong.

1. **Refunds never move money without the owner.** Everything else may resolve itself.
2. **Never claim legal compliance.** Not "compliant", not "certified", not "protected", not
   "you will be sued". The FTC's action against accessiBe is the precedent for why
   overstating an accessibility product is an enforcement risk. The score is described as
   *automated conformance against the checks that apply to this site*, in those words.
3. **Never send a dollar figure the code did not authorise.** Enforced by a lint, §12.
4. **Never email anyone whose site you could not actually fix.**
5. **Never re-price someone who already has a quote or a subscription.**
6. **Never crawl like an attacker.** Identified user agent pointing at a page that explains
   the bot, `robots.txt` obeyed, a crawl delay, a handful of pages.
7. **Never store a client credential unencrypted**, and delete it once work is delivered.
8. **Live mode stays refused by code** until an entity, insurance, lawyer review and an
   encryption key are all in place.

On R17, "make sure there's no way I get sued": no code can promise that, and the system
should say so plainly rather than pretend. What it does is remove the *specific, known* ways
businesses in this niche get sued or fined — contacting people outside CAN-SPAM's reach,
cold-emailing plaintiff-side professions, aggressive crawling, making claims you are not
licensed to make, holding credentials badly, and taking money for work you cannot deliver.
The rest is ordinary business exposure, which is what the entity, the insurance and the
lawyer review exist for.

---

# Part II — the specification

## 6. System shape

One **orchestrator** runs a `tick()` every five minutes. Each stage is isolated: an
exception in one lead is logged against that lead and never stalls the others. Stages, in
order:

```
scan → draft → inbound → follow-ups → send → chase access → start fixes →
verify → care cycle → pricing review → maintenance
```

Every tick writes a heartbeat and a JSON report the dashboard displays. Two global stops
exist: a **pause** switch, and a **circuit breaker** that trips automatically on bounce or
complaint rates.

Suggested module layout (names used throughout this document):

```
orchestrator · config · db · llm · models · schemas
legal · autopilot · exposure · plans · pricing · fixability · onboarding · care
standards/{checks,scoring} · prospecting · scanning · outreach · inbox · deals ·
fixing · finance · dashboard
```

## 7. Data model

Ten tables. SQLite, one file, `PRAGMA journal_mode=WAL`, plus an ALTER-based migration step
that adds any column introduced after a database was first created (`CREATE TABLE IF NOT
EXISTS` will not do it for you).

| table | what it holds | columns that matter |
|---|---|---|
| `leads` | one business | `url`, `domain`, `business_name`, `category`, `city`, `region`, `country`, `contact_email`, `contact_source`, `platform`, `status`, `needs_human_reason`, `next_action_at`, `followups_sent`, `clarify_count`, `retry_count`, `fixability`, `fix_channel`, `fix_detail`, `repo`, `access_granted_at`, `price_point` |
| `scans` | one scan of one site | `lead_id`, `kind` (baseline\|verification), `status`, `ada_score`, `aiseo_score`, `ada_summary` (JSON), `aiseo_summary` (JSON), `pages` (JSON), `exposure` (JSON), `checklist_version` |
| `findings` | one failure on one scan | `scan_id`, `kind`, `rule_id`, `impact`, `description`, `help_url`, `page_url`, `count`, `sample` |
| `messages` | every email in and out | `lead_id`, `thread_token`, `direction`, `kind` (initial\|followup\|reply\|checkout\|delivery\|system\|welcome\|access_reminder), `subject`, `body_text`, `body_html`, `to_addr`, `from_addr`, `message_id`, `in_reply_to`, `status`, `intent`, `lint` (JSON), `approved`, `hold_reason`, `sent_at` |
| `deals` | one sale | `lead_id`, `plan`, `price_cents`, `monthly_cents`, `currency`, `status`, `checkout_url`, `stripe_session_id`, `stripe_payment_intent`, `stripe_subscription_id`, `tax_cents`, `paid_at`, `delivered_at`, `care_started_at`, `care_cancelled_at`, `next_care_at`, `care_cycles` |
| `fixes` | one remediation attempt | `deal_id`, `status`, `strategy`, `bundle_path`, `summary` (JSON), `before_ada`, `after_ada`, `before_aiseo`, `after_aiseo`, `error` |
| `ledger` | money | `deal_id`, `kind` (charge\|refund\|processing_fee\|sales_tax), `amount_cents`, `stripe_id`, `memo`, `occurred_at` |
| `suppression` | never contact again | `address` (email or `@domain`), `reason` |
| `events` | append-only audit log | `lead_id`, `kind`, `detail` (JSON) |
| `kv` | small state | current price point, price history, last tick, breaker, per-lead tokens, encrypted credentials |

**Lead statuses.** `new → scanned → queued → contacted → engaged → accepted → paid →
delivered → verified`, with the terminal side-branches `no_contact`, `clean` (scored too
well to pitch), `not_fixable`, `not_interested`, `unsubscribed`, `bounced`, `excluded`,
`refunded`, `needs_human`, `archived`.

**Deal statuses.** `proposed → accepted → checkout_sent → paid → in_progress → delivered →
verified`, plus `refund_requested` (waiting on the owner), `refunded`, `cancelled`.

**Message statuses.** `draft` (failed lint or awaiting approval), `queued`, `sent`,
`failed`, `suppressed`, `received`, `held` (dry run: would have sent).

## 8. The checklist and the score

This is the spine of the product. Build it first (§24). It is the source of truth for the
scanner, the report, the email, the fixer and the monthly cycle, and the human-readable
checklist document is generated *from* it so the two can never disagree.

**Each check carries:** `id`, `title`, `area` (ada|seo), `category`, `weight` 1–10,
`detection` (`auto` | `heuristic` | `manual`), the `standard` it comes from, a plain-English
`why` a small business should care, a `fix` sentence, `auto_fixable`, the underlying
automated rule ids it maps to, an `applies` note, and `since` — the checklist edition that
introduced it.

**The scoring rule, exactly:**

```
score(area) = round(100 × earned_weight / applicable_weight)

where, over the checks in that area:
  applicable_weight = Σ weight of checks with status pass|fail, EXCLUDING detection=manual
  earned_weight     = Σ weight of checks with status pass,      EXCLUDING detection=manual
  checks that do not apply to this site are excluded from BOTH sides
  a check never evaluated counts as not_applicable, not as a failure
  if applicable_weight == 0 the score is 100
```

Manual checks are excluded **in the scorer**, not by trusting each detector to behave — the
guarantee that a percentage never contains a guess belongs in one place. Manual items are
reported separately as "needs a person to check" and never as measured failures.

**Bands** (a word for the number, so the report never leans on the number alone): ≥95
excellent · ≥85 good · ≥70 fair · ≥50 poor · else critical.

**Versioning.** The checklist has an edition (`YYYY.MM`, string-comparable). Every check
records the edition that introduced it; every scan records the edition it was measured
against; every edition has a one-line note saying what changed. This is what makes R28 real
rather than a slogan — see §18.

### The 80 checks

46 accessibility, 34 AI-search. Detection: **A** automated, **H** heuristic, **M** needs a
person. **Fix: Y** means the remediation can be generated automatically.

#### ADA — Operable - can people use it without a mouse or good eyesight?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `keyboard-access` | 10 | H | - | 2.1.1 Keyboard A | Everything works with a keyboard |
| `no-keyboard-trap` | 8 | M | - | 2.1.2 No Keyboard Trap A | Keyboard focus is never trapped |
| `focus-visible` | 9 | H | Y | 2.4.7 Focus Visible AA | Keyboard focus is clearly visible |
| `focus-order` | 6 | H | Y | 2.4.3 Focus Order A | Tab order follows the visual order |
| `focus-not-obscured` | 4 | M | - | 2.4.11 Focus Not Obscured (Minimum) AA | Focused elements are not hidden behind sticky bars |
| `skip-link` | 6 | A | Y | 2.4.1 Bypass Blocks A | There is a way to skip repeated navigation |
| `landmarks` | 6 | A | Y | 1.3.1 Info and Relationships A | Page regions are marked as landmarks |
| `page-title` | 8 | A | Y | 2.4.2 Page Titled A | Every page has a unique, descriptive title |
| `link-purpose` | 8 | A | Y | 2.4.4 Link Purpose (In Context) A | Links say where they go |
| `button-name` | 9 | A | Y | 4.1.2 Name, Role, Value A | Buttons have accessible names |
| `frame-title` | 5 | A | Y | 2.4.1 Bypass Blocks A, 4.1.2 Name, Role, Value A | Embedded frames are labelled |
| `heading-order` | 5 | A | Y | 1.3.1 Info and Relationships A | Heading levels don't skip |
| `target-size` | 5 | A | Y | 2.5.8 Target Size (Minimum) AA | Tap targets are big enough |
| `pointer-alternatives` | 4 | M | - | 2.5.1 Pointer Gestures A, 2.5.7 Dragging Movements AA | Gestures and dragging have simple alternatives |
| `label-in-name` | 4 | H | - | 2.5.3 Label in Name A | Visible labels match their accessible names |
| `timing-and-motion` | 5 | A | Y | 2.2.1 Timing Adjustable A, 2.2.2 Pause, Stop, Hide A, 2.3.1 Three Flashes A | Time limits and moving content can be controlled |

#### ADA — Perceivable - can people take the information in?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `image-alt` | 10 | A | Y | 1.1.1 Non-text Content A | Images have text alternatives |
| `image-alt-quality` | 4 | H | Y | 1.1.1 Non-text Content A | Alt text is meaningful, not a filename |
| `video-captions` | 8 | M | - | 1.2.2 Captions (Prerecorded) A | Video has captions |
| `audio-description` | 4 | M | - | 1.2.5 Audio Description (Prerecorded) AA | Video has audio description where needed |
| `semantic-structure` | 9 | A | Y | 1.3.1 Info and Relationships A | Headings, lists and tables use real markup |
| `form-labels` | 10 | A | Y | 1.3.1 Info and Relationships A, 3.3.2 Labels or Instructions A | Form fields have labels |
| `input-purpose` | 3 | A | Y | 1.3.5 Identify Input Purpose AA | Common fields declare their purpose |
| `meaningful-sequence` | 5 | M | - | 1.3.2 Meaningful Sequence A | Reading order makes sense without styling |
| `sensory-characteristics` | 3 | M | - | 1.3.3 Sensory Characteristics A | Instructions don't rely on shape or position alone |
| `color-not-alone` | 6 | H | Y | 1.4.1 Use of Color A | Colour is not the only way information is shown |
| `audio-control` | 7 | A | Y | 1.4.2 Audio Control A | Nothing plays sound automatically |
| `color-contrast` | 10 | A | Y | 1.4.3 Contrast (Minimum) AA | Text has enough contrast against its background |
| `non-text-contrast` | 6 | H | - | 1.4.11 Non-text Contrast AA | Buttons, icons and form borders have enough contrast |
| `resize-text` | 6 | H | - | 1.4.4 Resize Text AA, 1.4.10 Reflow AA | Text can be enlarged to 200% without breaking |
| `zoom-enabled` | 7 | A | Y | 1.4.4 Resize Text AA | Pinch zoom is not disabled |
| `images-of-text` | 4 | M | - | 1.4.5 Images of Text AA | Text is real text, not pictures of text |
| `text-spacing` | 3 | M | - | 1.4.12 Text Spacing AA | Layout survives increased text spacing |
| `hover-content` | 3 | M | - | 1.4.13 Content on Hover or Focus AA | Tooltips and popovers can be dismissed and hovered |

#### ADA — Robust - does it work with assistive technology?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `aria-valid` | 8 | A | Y | 4.1.2 Name, Role, Value A | ARIA is used correctly |
| `unique-ids` | 4 | A | Y | 4.1.2 Name, Role, Value A | Element IDs used by ARIA are unique |
| `widget-names` | 6 | A | - | 4.1.2 Name, Role, Value A | Custom widgets expose a name and role |
| `status-messages` | 4 | M | - | 4.1.3 Status Messages AA | Dynamic updates are announced |
| `accessibility-statement` | 5 | A | Y | Best practice; expected by the DOJ's web accessibility guidance | The site has an accessibility statement |

#### ADA — Understandable - is it predictable and clear?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `page-language` | 7 | A | Y | 3.1.1 Language of Page A | The page declares its language |
| `language-of-parts` | 2 | M | - | 3.1.2 Language of Parts AA | Foreign phrases are marked up |
| `consistent-navigation` | 4 | H | - | 3.2.3 Consistent Navigation AA, 3.2.4 Consistent Identification AA | Navigation is consistent across pages |
| `no-surprise-changes` | 4 | M | - | 3.2.1 On Focus A, 3.2.2 On Input A | Nothing changes unexpectedly on focus or input |
| `error-identification` | 6 | H | - | 3.3.1 Error Identification A, 3.3.3 Error Suggestion AA | Form errors are described in text |
| `consistent-help` | 3 | H | - | 3.2.6 Consistent Help A | Help and contact details are easy to find |
| `accessible-auth` | 3 | M | - | 3.3.8 Accessible Authentication (Minimum) AA | Login doesn't depend on a memory test |

#### SEO — AI readiness - can an assistant read, understand and quote it?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `llms-txt` | 6 | A | Y | llmstxt.org proposal | There is an llms.txt summary for AI assistants |
| `server-rendered` | 9 | A | - | Google Search Central: JavaScript SEO; AI crawler behaviour | Content exists without running JavaScript |
| `answer-ready-content` | 6 | H | Y | Best practice for generative search and AI assistants | The page answers real questions directly |
| `entity-clarity` | 7 | H | Y | Best practice for entity recognition | It is obvious what and where the business is |
| `freshness` | 3 | H | Y | Best practice; Google Search Central: freshness | Content shows signs of being current |
| `no-ai-blocking-meta` | 4 | A | Y | Google Search Central: nosnippet, max-snippet, noai conventions | No meta tags block AI use of the content |

#### SEO — Content and metadata - is there something worth showing?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `title-tag` | 9 | A | Y | Google Search Central: title links | Page titles are present and well formed |
| `meta-description` | 6 | A | Y | Google Search Central: snippets | Pages have a meta description |
| `h1` | 6 | A | Y | Google Search Central: heading structure | Each page has exactly one H1 |
| `content-depth` | 7 | A | - | Google Search Central: helpful content | Pages have enough readable text |
| `nap-visible` | 7 | A | - | Local SEO best practice; Google Business Profile consistency | Phone and address appear in the page text |
| `descriptive-urls` | 3 | A | - | Google Search Central: URL structure | URLs are readable |
| `internal-links` | 4 | A | - | Google Search Central: link best practices | Pages are linked to each other |
| `open-graph` | 3 | A | Y | Open Graph protocol | Shared links show a preview |

#### SEO — Crawlability - can search engines and assistants reach it?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `robots-exists` | 5 | A | Y | Robots Exclusion Protocol (RFC 9309) | robots.txt exists and is valid |
| `crawlers-allowed` | 10 | A | Y | Robots Exclusion Protocol (RFC 9309) | Search crawlers are not blocked |
| `ai-crawlers-allowed` | 9 | A | Y | Publisher controls for GPTBot, ClaudeBot, PerplexityBot, Google-Extended | AI assistants are allowed to read the site |
| `sitemap` | 6 | A | Y | sitemaps.org protocol 0.9 | An XML sitemap exists and is referenced |
| `indexable` | 10 | A | Y | Google Search Central: robots meta tag | Pages are not accidentally set to noindex |
| `https` | 8 | A | - | Google Search Central: HTTPS as a ranking signal | The site is served over HTTPS |
| `canonical` | 4 | A | Y | Google Search Central: canonicalization | Pages declare a canonical URL |
| `broken-links` | 5 | A | - | Best practice | Internal links are not broken |

#### SEO — Performance - is it fast enough on a phone?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `lcp` | 8 | A | - | Core Web Vitals: Largest Contentful Paint under 2.5s | The main content loads quickly |
| `cls` | 5 | A | - | Core Web Vitals: Cumulative Layout Shift under 0.1 | The layout doesn't jump while loading |
| `page-weight` | 5 | A | - | Best practice; web.dev performance budgets | The page isn't unnecessarily heavy |
| `mobile-friendly` | 9 | A | Y | Google Search Central: mobile-first indexing | The site works on a phone |
| `image-optimisation` | 4 | A | Y | web.dev image best practices | Images are sized and lazily loaded |

#### SEO — Structured data - do machines know what the business is?

| id | weight | det | fix | standard | what it checks |
|---|---:|:-:|:-:|---|---|
| `structured-data` | 10 | A | Y | schema.org LocalBusiness / Organization | The business is described in structured data |
| `structured-data-valid` | 6 | A | Y | schema.org vocabulary; JSON-LD 1.1 | Structured data parses and uses real types |
| `nap-structured` | 8 | A | Y | schema.org PostalAddress; Google Business Profile consistency | Name, address and phone are in the markup |
| `opening-hours` | 5 | A | Y | schema.org openingHoursSpecification | Opening hours are machine readable |
| `faq-schema` | 4 | A | Y | schema.org FAQPage | Common questions are marked up as FAQs |
| `breadcrumbs` | 3 | A | Y | schema.org BreadcrumbList | Page hierarchy is described |
| `social-profiles` | 3 | A | Y | schema.org sameAs | Official profiles are linked from the markup |

**Weight guidance:** 9–10 for anything that stops someone completing a task (no alt text on
meaningful images, no accessible name on a control, contrast failures, unlabelled form
fields, a page an assistant cannot reach). 5–8 for real barriers with workarounds. 1–4 for
quality items. The weights are opinions; what matters is that they are *fixed in advance*
and applied uniformly, so a percentage means the same thing on every site.

## 9. The scanner

Real headless Chromium, not an HTTP fetch — half the checks need rendered DOM and computed
styles.

1. Fetch and obey `robots.txt` first. Identify honestly in the user agent, with a URL to a
   page that explains the bot. Crawl delay ~2s. At most 4 pages (home, plus the most
   link-prominent internal pages).
2. Run an off-the-shelf accessibility engine (axe-core is the obvious choice; vendor the
   file rather than pulling it at runtime) and map its rule ids onto your checks.
3. Run your own checks for everything axe cannot see: AI-readability, structured data,
   crawlability by AI agents, metadata, performance signals.
4. Merge into one result per check per page, take the worst result across pages, and score.
5. Compute the exposure figures (§10) and the fixability verdict (§15).
6. Store the scan, the findings, the checklist edition, and a snapshot for diffing later.

**Result statuses per check:** `pass`, `fail`, `needs_review`, `not_applicable`. An
automated engine's "incomplete" bucket maps to `needs_review`, never to `fail`.

## 10. The exposure model

R6 is what makes the email work, and it is also the easiest place to get sued. Rule: **every
number in an email comes from a data file with a source, and the email says it is an
estimate.**

Keep the assumptions in a data file, not in prompts or prose. The working values:

**Accessibility exposure**

| value | number | basis |
|---|---|---|
| lawsuits per year (US) | 4,000 | Industry year-end reports put recent years at roughly 4,000–4,600 federal and state filings. Excludes demand letters, which are far more common and rarely public |
| typical early settlement | $5,000–$20,000 | Commonly reported range for small businesses that settle early |
| defence fees if it proceeds | $10,000–$50,000 | Rough range once counsel is engaged past the initial demand |
| California Unruh statutory minimum | $4,000 per occurrence, plus fees | Why California sees a disproportionate share of filings |
| state multipliers | CA 1.5, NY 1.4, FL 1.2, PA 1.1, IL 1.1, else 1.0 | Filing concentration by state |

```
severity  = clamp((100 - ada_score) / 100, 0, 1)
low       = settlement_low × state_multiplier
typical   = (settlement_low + (settlement_high - settlement_low) × severity
             + defense_fees_low × severity) × state_multiplier
high      = (settlement_high + defense_fees_high) × state_multiplier
```

**AI-search exposure**

| value | number | basis |
|---|---|---|
| share of local discovery now via AI assistants | 10% | Deliberately conservative working assumption; revise as data appears |
| traditional search volume drop by 2026 | 25% | Gartner (Feb 2024) prediction |
| default conversion rate | 3% | Working assumption |
| monthly visits by trade | 300–1,500 (e.g. restaurant 1,500, dentist 800, plumber 400) | Working assumptions by category |
| average ticket by trade | $45 (restaurant) to $9,000 (roofing) | Working assumptions by category |

```
forfeit          = clamp((100 - aiseo_score) / 100, 0, 1)
annual_at_risk   = visits × 12 × ai_share × conversion × ticket × forfeit
range            = [annual_at_risk × 0.5, annual_at_risk × 1.5]
```

**The value case** — the comparison the email must make — is arithmetic over those figures
and the price: first-year cost, recoverable annual revenue, the cheapest realistic claim,
the multiple between them, and months-to-payback. Nothing new is invented at this step, and
every figure keeps the "estimate" label it arrived with.

Publish the sources in the email footer. Four is enough.

## 11. Pricing

**Two plans, same work, same up-front price.**

| plan | price | one-line pitch |
|---|---|---|
| **Fix and keep it fixed** *(recommended)* | $99 to fix it, then $9.99/month | we fix everything in the report now, then check it every month and fix whatever slips |
| **One-off fix** | $99 once | the same fix, once, with no monthly checking afterwards |

The retainer's `includes`, which appear in the email, the agreement and the report — write
them once and reuse them verbatim:

- every issue in the report fixed, usually within 10 business days
- an automatic recheck every month against the whole checklist
- anything that regresses fixed the same week, at no extra cost
- new pages you publish checked and corrected as they appear
- *the checklist itself kept current — when WCAG guidance changes, or the search engines and
  AI assistants change what they read, the new checks are added and your site is measured
  against them at no extra cost* ← **this sentence is R28**
- a short monthly email showing both scores and what changed
- cancel any time, in one click, with no notice period

The one-off says plainly: *no monitoring afterwards — new pages and new rules are not
covered.*

**Why the retainer leads.** Accessibility does not stay fixed (they add a page, upload an
image with no alt text, the theme updates). The verification promise is already ongoing work,
so charge for it as a service. And one-off revenue restarts at zero every month, while
recurring revenue compounds and makes each acquired customer worth far more.

**Why both cost $99 up front.** It is the same work. Charging more for the one-off is a
penalty for declining a subscription, and customers read it that way. (This was got wrong
first — §26, A7.)

**Negotiation floors.** Maximum discount 20%, and computed floors round **up** to whole
dollars ($79.20 is arithmetic; $80 is a price). The model may never quote below the floor or
above list; the code clamps both ends after the model replies.

### Adaptive pricing (R31)

A price is a hypothesis and cold outreach tests it for free.

- A **ladder** of price points, most expensive first:
  `$199+$19.99 · $149+$14.99 · $99+$9.99 · $79+$9.99 · $49+$4.99`. One rung is current;
  $99 is where it starts.
- The current rung is **stamped on each lead** the first time you write to them, and every
  later email, follow-up, negotiation and checkout for that lead is priced from the stamp.
- Score a rung on the emails **actually delivered** at it and the sales that came back:
  `conversion = paid ÷ contacted`. Also track replies and revenue per email sent, which is
  the number that really decides whether a move helped.
- **Review every tick.** Do nothing until the rung has had ≥60 delivered emails *and* has
  been current ≥14 days. Then: conversion < 0.4% → step **down** one rung; ≥ 4.0% → step
  **up** one rung; in between → hold. Never more than one rung per move.
- At the **bottom rung** with nothing selling, stop and say so: "the problem is the message
  or the market, not the price." Do not loop downward.
- Record every move with its evidence, show the whole ladder on the dashboard, and provide
  a manual override and an off switch.

Three properties make this safe to leave running unattended, and all three must hold: a
quote already given never changes; an existing subscription is never re-priced (the payment
processor holds its price, and the deal row holds the agreed amount); and the bottom of the
ladder is a finding, not a loop.

## 12. Outreach

**What the model is given:** a context object containing only approved facts — the two
scores, the top four failures in plain language, the exposure figures, the plan and its
price, the value comparison. **What the model returns:** a subject and five short
paragraphs. Nothing else.

**The prompt rules that matter:**

- Use only dollar figures that appear in the context, written exactly as given. Never invent
  numbers, never round ($9.99 is not $10).
- The scores may be quoted, described as an automated check of the points that apply to
  their site. Never say or imply a score means they are or are not legally compliant.
- Say a dollar figure is an estimate and what it is based on.
- Never guarantee compliance, never say "certified", never say or imply they will be sued or
  fined, never manufacture urgency.
- Plain language, second person, specific to what the scan found. No hype, no exclamation
  marks, no bullet lists. Under 180 words. Subject under 60 characters and not starting
  "Re:".
- One paragraph must make the gain/save comparison explicit (R23): what they stand to gain
  or avoid, set against what it costs. State both plainly and let the reader draw the
  conclusion. Do not add pressure, and do not use the word "only" about money.

**Then lint the draft in code.** A model instruction is a preference; the lint is the rule.
Reject any draft where:

- The subject is empty, over 78 characters, all caps, contains `!`, or contains any of:
  `re:`, `fw:`, `fwd:`, `invoice`, `payment`, `legal`, `urgent`, `lawsuit`, `notice`,
  `warning`, `action required`, `account`, `complaint`, `violation`, `suspended`,
  `important`.
- The body contains any forbidden marketing phrase: `guarantee`, `guaranteed`,
  `fully compliant`, `100% compliant`, `certified`, `certification`, `certificate`,
  `you will be sued`, `you'll be sued`, `will be sued`, `lawsuit has been`, `has been filed`,
  `legal notice`, `final notice`, `immediate action`, `act now`, `urgent`, `last chance`,
  `limited time`, `fine of`, `fines`, `penalty`, `penalties`, `protect you from`,
  `lawsuit-proof`, `immune`, `government requires you`, `required by law to hire`,
  `your account`, `verify your`, `we noticed you were sued`, `before it's too late`,
  `don't get sued`, `avoid a lawsuit`, `avoid lawsuits`, `compliance certificate`,
  `ada certified`.
- The body contains any legal-conclusion phrase: `you are required by law`,
  `the law requires you`, `you must comply`, `you are violating`, `your site violates`,
  `is illegal`, `unlawful`, `you are non-compliant`, `in violation of`, `breaks the ada`,
  `breaking the law`, `legally obligated`, `legally required`, `we are attorneys`,
  `our lawyers`, `legal opinion`, `as your counsel`, `cease and desist`, `statute requires`,
  `mandated by law`, `federal law requires`, `you will be fined`, `immune from`,
  `protects you from lawsuits`, `makes you lawsuit-proof`, `eliminates your risk`.
- Any dollar figure appears that is not in the authorised list for this email.
- Dollar figures appear without the word "estimate" somewhere in the body.
- The unsubscribe instruction, the postal address or the legal name is missing.
- The body (excluding footer) runs over 320 words.

Keep a map of safe replacements — "violates" → "was flagged by the scan against",
"non-compliant" → "flagged against WCAG 2.2 AA checks", "required by law" → "commonly
expected" — and use it when repairing a draft.

**A failed draft is not a human's problem.** Feed the lint's own complaints back to the
model up to twice; if it still fails, send a fixed template assembled from pre-approved
sentences and the same approved figures. Outcomes are "queued" or "deferred for model
capacity" — never "waiting for the owner".

**The footer** (CAN-SPAM, and it must be truthful):

```
—
Full report for {domain}: {report_url}
The dollar figures above are estimates, not predictions, based on publicly reported
settlement ranges and stated traffic assumptions.
  Source: {title} - {url}      (up to four)
You're receiving this one-time business message because {domain} is publicly listed as
a {category} in {city}. We won't email again after two short follow-ups.
To opt out, reply with the word "unsubscribe" or visit {url} — either works immediately.
{legal_name}, {postal_address} · {website}
```

Also set the RFC 8058 one-click unsubscribe headers.

**Sending rules.** Weekday send window 09:00–17:00 in the operator's timezone. Daily cap 40
(ramp a new domain 10 → 20 → 40). Two follow-ups, at 3 and 7 days, then stop forever. A
180-day cooldown before the same domain can be contacted again. Replies come back to
`reply+<thread-token>@yourdomain`, which is how a reply is matched to its conversation — so
that mailbox needs a catch-all. A circuit breaker halts all sending if bounces exceed 5% or
complaints exceed 0.2% over a sample of at least 20.

## 13. Replies and negotiation

Poll IMAP for unread mail. Match to a thread by the plus-address token, falling back to
`In-Reply-To`. Classify intent with a cheaper model: `interested`, `question`,
`objection_price`, `objection_other`, `not_interested`, `unsubscribe`, `wrong_person`,
`auto_reply`, `bounce`, `accept`, `already_customer`, `unclear`.

Any reply stops the follow-up clock.

Then, by intent:

| intent | what happens — no human involved |
|---|---|
| `unsubscribe` | Suppress the address permanently, immediately. No reply needed |
| hostile / abusive | One short non-argumentative stand-down, then permanent suppression |
| asks for data deletion | Erase everything held about them except the proof that you stopped emailing |
| `wrong_person` | Close politely, suppress |
| `bounce` | Mark bounced, suppress, count toward the breaker |
| `unclear` | One clarifying question. A second unclear reply closes the file politely |
| out of scope / model unsure | Plainly decline the extra and restate what is sold |
| everything else | The negotiation agent |

**Negotiation policy — the model writes the words, the code owns the numbers:**

- Lead with the retainer. Offer the one-off only if they clearly refuse anything recurring.
- The model proposes a price; the code then clamps it: never below the floor, never above
  list, monthly clamped the same way.
- `ready_to_close` is honoured **only** if the classified intent is an explicit acceptance.
  The model cannot decide a deal is done.
- The reply is linted like any other outbound email, with the newly proposed figures added
  to the authorised list.
- Never guarantee legal compliance. Say what is fixed and that you re-scan to verify.
- Under 150 words, no bullet lists, no exclamation marks.
- If the model refuses or errors, stand down without moving the price and record why — and
  make sure that error path itself is exercised by a test (§26, B1).

## 14. Money

Payment processor checkout, with the setup fee and the recurring fee on **one** page
(Stripe's subscription mode with a one-off line item does this). Automatic sales tax through
the processor's tax product — the engine asks for a computed rate and never invents one.
Webhooks for checkout completed, invoice paid, and subscription deleted. Record charges,
fees, refunds and tax in a ledger with a CSV export.

**Refunds (R18) are the one human gate in the whole system.** When work cannot be delivered
or a customer asks, the engine moves the deal to `refund_requested`, surfaces it on the
dashboard with Refund / Keep-the-money buttons, and tells the customer nothing until the
owner decides. Money never leaves the account automatically. This was got wrong first — §26,
A1.

## 15. Can we even fix it

**Decide during the scan, from evidence, before any email is written.** Selling a
remediation and then mailing a zip file earns refund requests, and it is not what the email
promised.

Three tiers:

| tier | meaning | may we pitch? |
|---|---|---|
| `direct` | We can apply the change ourselves once they grant access, and granting it is a couple of clicks | **Yes** |
| `assisted` | We could produce the change but they must paste it in | No (default) |
| `unknown` | No usable signal | No |

**Detection, in this order — the order matters:**

1. **Site builder first.** Wix, Squarespace, GoDaddy, Weebly, Duda, Shopify → `assisted`,
   whatever else is true. Recognise them by body and header fingerprints.
2. **GitHub Pages** (`Server: github.com` or an `x-github-request-id` header, or a
   `*.github.io` hostname) → `direct`, via pull request. Infer the repository: `alex.github.io`
   is served from `alex/alex.github.io` by definition; a project page at
   `alex.github.io/thing` comes from `alex/thing`; a custom domain hides it, but many sites
   link to their repo anyway.
3. **WordPress with a reachable REST API** (probe `/wp-json/`; a probe failure must never
   break the scan) → `direct`, via application password.
4. **Netlify / Vercel** (`x-nf-request-id`, `x-vercel-id`, or their `Server` headers, or
   `*.netlify.app` / `*.vercel.app`) → `direct`, Git-backed.
5. **Cloudflare Pages** — **only** from a `*.pages.dev` hostname. Cloudflare's `cf-ray`
   header is present on every site behind their CDN, which is a large fraction of the web
   including Wix and Squarespace, and is evidence of nothing. This exact mistake was made
   and shipped; see §26, A5.
6. Otherwise `unknown`.

Anything not `direct` is marked `not_fixable` and never enters outreach. Make this a
configurable gate, so the owner can choose to sell paste-it-in work later.

**Why GitHub-hosted sites are the best first market:** the customer grants you *nothing*.
Fork the public repository, commit, open a pull request explaining every change, and they
press Merge. No token, no password, nothing on their site moves until they choose. Implement
it as: check push permission; if absent, fork, wait for the fork to become ready (poll until
it has branches — forking is asynchronous), push a branch to the fork, and open the PR
cross-repo with `maintainer_can_modify` set.

## 16. Onboarding after payment (R25)

The moment payment lands, email the customer the *shortest path their platform allows*, plus
a private setup page at an unguessable token URL (the token is the credential; no login).

| their site | what you ask for |
|---|---|
| GitHub, repo known from the scan | **Nothing at all.** A pull request arrives; they press Merge |
| GitHub, custom domain | One thing: paste the repository address. No password, no token |
| WordPress with REST | An application password — four clicks, revocable, never their real password, stored encrypted, deleted on delivery |

Refuse to store a credential at all if no encryption key is configured — say so rather than
writing it in the clear.

**Never let paid work stall behind a form.** One reminder after two days. After three days,
stop waiting and deliver the finished files with instructions instead.

The welcome email also restates the R28 promise: when the rules change, their site is
measured against the new checks at no extra cost.

## 17. The fixer

Build a bundle per deal, then apply it. What it generates, all driven by the failing checks:

- **Per page:** alt text written by the model for images that need it, page `<title>` and
  meta description, `lang` attribute, heading order normalised, a skip link, landmark
  regions (`<main>` wrapping), accessible names for buttons and links, form label
  associations, frame titles, and a CSS block that fixes contrast failures by darkening or
  lightening the offending colour until it clears 4.5:1.
- **Site-wide:** `robots.txt` (with the sitemap line, and without blocking AI crawlers),
  `sitemap.xml`, `llms.txt`, JSON-LD `LocalBusiness` with hours parsed from the page,
  breadcrumbs, an FAQ block, and a small accessibility stylesheet (visible focus styles,
  minimum tap targets).
- **Always:** a `CHANGES.md` mapping every edit to the finding it resolves, and `.orig`
  copies of every patched page so the customer can diff.

Apply through the route decided in §15. Then **verify**: rescan, store before/after scores,
send a before/after report. If the customer never publishes, nudge at 7 and 21 days; if
still nothing at 45 days, queue a refund **for the owner's approval** (§14).

## 18. The care cycle and checklist versioning

Monthly, per active subscription:

1. Rescan the whole site against the **current** checklist edition.
2. Diff against the previous cycle: what regressed, what is new, what improved.
3. **Compute new-edition checks separately.** A check added since the client was last
   measured is *not* a regression — it never existed last month, and reporting it as one is
   a false statement to a paying customer (§26, A3). It gets its own paragraph.
4. Fix what is auto-fixable in either set.
5. Send a short report: both scores, what changed, what was fixed, and — when the checklist
   moved — name the new checks and say there is no extra charge.
6. Schedule the next cycle.

Cancellation is one click from any receipt and is honoured immediately.

## 19. The autopilot (R16)

The design rule: **every branch that would once have said "a human should look at this" gets
a safe automatic answer instead**, and the answer is written to a notices feed the owner can
read without having decided anything.

| situation | automatic resolution |
|---|---|
| Draft fails the lint | Repair twice from the lint's own complaints, then the fixed safe template |
| Model refuses or errors | Stand down, record why, leave the price untouched |
| Model capacity / rate limit | Defer the lead one hour and carry on. Not an error |
| Reply arrives before a usable scan | Requeue for a rescan |
| Unclear reply | One clarifying question, then a polite close |
| Hostile reply | One stand-down, permanent suppression |
| Out-of-scope request | Plainly decline, restate what is sold |
| Data-deletion request | Erase everything except the proof you stopped emailing |
| Scan fails | Retry once, then archive the lead |
| Build fails | Retry once, then record the failure against the deal |
| Delivered work never goes live | Nudge at 7 and 21 days, then queue a refund **for approval** |
| Bounce/complaint rates too high | Trip the breaker; stop all sending |

The dashboard's "needs a human" counter should sit at zero. Anything in it is a genuine
gap — treat a non-zero count as a bug in the autopilot, not as work for the owner.

## 20. Legal and safety

- **US-only.** Block non-US country codes and these TLDs: `ca uk eu de fr es it nl be ie se
  no dk fi pl pt at ch gr cz ro hu au nz in cn jp kr br mx`. Block `.gov`, `.mil`, `.edu`.
- **Excluded trades** (plaintiff-side professions, regulated verticals, procurement
  regimes): `lawyer, attorney, law, legal, solicitor, paralegal, court, government,
  municipal, city hall, police, school, university, college, political, campaign, church,
  cannabis, dispensary, firearms, gun, casino, gambling, adult, escort, payday, debt
  collection, crypto`.
- **Crawl politely.** Obey `robots.txt`, 2-second delay, ≤4 pages, an identified user agent
  pointing at a public page that explains the bot and how to block it.
- **Data minimisation.** Delete site snapshots after 90 days; delete client credentials once
  work is delivered; honour deletion requests completely.
- **Encrypt credentials at rest** (Fernet or equivalent). Without a key, refuse to store
  rather than store in the clear. Back the key up off the server.
- **Preflight gate.** Live mode is refused by code until: a real postal address, a real
  website, a real legal name, a real from-address, an encryption key, **an entity formed**,
  **liability insurance**, and **an agreement reviewed by a lawyer**. The last three are
  attestations — the code records that the owner says they are true.
- **Self-test rail.** An allowlist of the operator's own addresses, enforced at the send
  gate. While it is set, mail physically cannot reach anyone else, and the business-readiness
  checks are skipped because no stranger is reachable. Clearing it brings them straight back.
- Publish a terms page and a per-deal agreement. Have both read by a lawyer before the first
  stranger is emailed; the narrow question is *does this promise anything we do not deliver,
  and does anything here read as legal advice*.

## 21. Visibility (R13)

A local web dashboard behind a token, plus a CLI. Pages:

- **Overview** — funnel counts, emails sent, replies, deals, net revenue, "needs a human"
  (should be zero), gates (what is allowed to happen and why not), the pricing ladder, the
  last tick's report, recent activity, and anything the autopilot handled for you.
- **Leads** — searchable list; per lead: both scores, every finding with severity, the
  exposure estimate, the fixability verdict and access state, the pinned price, the whole
  email thread with each message's lint result, and a timeline.
- **Outbox** — anything queued or held, with an approve-and-send button.
- **Finance** — charges, fees, tax by state, ledger export.
- **Refunds** — the approval queue.
- **Public pages** (no login): the prospect's report, unsubscribe, the agreement, the
  customer setup page, checkout return, and the payment webhook.

**The public report is the main sales asset** — the cold email is three paragraphs and a
link, and the link does the persuading. It must carry: both percentages with their bands and
the honest denominator spelled out ("x of y applicable points"); every failure with its
severity, what was found, why it matters to this business in plain language, and what fixing
it involves; the checks that *passed*, so it reads as a measurement rather than a list of
complaints; the items that need a person, listed separately and never counted as failures;
the exposure estimate with every assumption and source visible; the checklist edition it was
measured against; and, after a fix, the before/after. It must also say in as many words that
a score is automated conformance against applicable checks and not a statement of legal
compliance.

CLI commands worth having: `init`, `add-leads`, `prospect`, `scan`, `draft`, `send`, `tick`,
`run`, `dashboard`, `status`, `preflight`, `pricing`, `secret`, `notices`, `refunds`,
`simulate-reply`, `simulate-payment`, `erase`, `export-ledger`.

## 22. Configuration

Everything env-driven with a common prefix and nested groups. Defaults are deliberately
safe: dry run, all autonomy off, console email provider. The engine must refuse to send,
charge or modify anything unless the mode is live **and** the matching autonomy flag is on
**and** the relevant provider is configured **and** preflight passes.

| group | setting | default |
|---|---|---|
| root | `mode` | `dry_run` |
| | `tick_seconds` | 300 |
| | `secrets_key` | *(empty — blocks credential storage)* |
| pricing | `care_setup_cents` / `care_monthly_cents` | 9900 / 999 |
| | `fix_only_cents` | 9900 |
| | `floor_setup_cents` / `floor_monthly_cents` / `max_discount_pct` | 4900 / 999 / 20 |
| | `adaptive` | true |
| | `ladder_setup_cents` | [19900, 14900, 9900, 7900, 4900] |
| | `ladder_monthly_cents` | [1999, 1499, 999, 999, 499] |
| | `review_after_sends` | 60 |
| | `step_down_below_conversion_pct` / `step_up_at_conversion_pct` | 0.4 / 4.0 |
| | `min_days_between_moves` | 14 |
| | `clean_ada_percent` / `clean_seo_percent` | 92 / 88 — at or above both, leave them alone |
| autonomy | `auto_send_outreach`, `auto_reply`, `auto_send_checkout`, `auto_apply_fixes` | all **false** |
| autopilot | `enabled` | true |
| | `lint_repair_attempts` / `clarify_attempts` / retries | 2 / 1 / 1 |
| | `verify_reminder_days` / `auto_refund_after_days` | [7, 21] / 45 |
| | `capacity_backoff_minutes` | 60 |
| outreach | `daily_send_cap` | 40 |
| | `followup_days` | [3, 7] |
| | `send_window_start_hour` / `end_hour` / `timezone` | 9 / 17 / America/New_York |
| | `max_bounce_rate` / `max_complaint_rate` / `min_sample_for_breaker` | 0.05 / 0.002 / 20 |
| | `recontact_cooldown_days` | 180 |
| model | `provider` | subscription-CLI provider |
| | `model` / `classify_model` | a frontier model / a cheaper one for triage |
| | `max_budget_usd` per call | 1.0 |
| prospecting | `require_fixable` | **true** |
| scanning | `max_pages_per_site` / `page_timeout_ms` | 4 / 25000 |
| legal | `us_only`, `respect_robots`, `delete_credentials_after_delivery` | true |
| | `crawl_delay_seconds` / `snapshot_retention_days` | 2.0 / 90 |
| | `only_email_addresses` | empty (the self-test rail) |
| | `business_entity_formed`, `liability_insurance`, `agreement_reviewed_by_lawyer` | all false |

---

# Part III — building it

## 23. Stack

The reference implementation uses Python 3.11, Playwright + headless Chromium, a vendored
axe-core, BeautifulSoup, FastAPI + Jinja2, SQLite, Pydantic settings, `cryptography` (Fernet),
`httpx`, and `pytest`. None of that is load-bearing except the real browser — half the
accessibility checks need rendered DOM and computed styles, so an HTML parser alone cannot
do this job.

**On the language model.** The owner wants the work billed to his Claude subscription rather
than a metered API key (R15). The way that works: shell out to the Claude Code CLI in
headless mode, and **strip `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the child
process environment** so the CLI authenticates as the signed-in user. Replace the CLI's
system prompt and disable its tools and project settings, which keeps the cached prefix
small and byte-identical between calls — measured cost was about $0.28 of quota on the first
call and about $0.017 on each one after, because the prefix becomes a cache read. Keep a
direct-API provider and a deterministic fake provider behind the same interface: the fake one
lets the entire pipeline run in tests with no model at all, and switching to metered API
credits when volume demands it should be a one-line config change.

Distinguish a **capacity error** (rate limit, subscription usage limit) from a real error.
Capacity is a normal condition: defer the lead an hour and carry on.

Check the subscription's terms before running a commercial service on a plan intended for
interactive use. That is a question for the provider's terms, not something code can answer.

## 24. Build order

Each step is testable before the next exists, and the expensive judgement calls come first
rather than being retrofitted.

1. **The checklist.** Before any scanning code: every check, its weight, area, detection
   method, source standard, why it matters, whether it is auto-fixable, and the edition it
   was introduced in. Generate the human-readable document from it. Everything downstream is
   a function of this list; retrofitting weights or the `since` field later means rewriting
   all of it.
2. **Scoring, with an honest denominator.** Decide what "92%" means before anything puts
   that number in front of a stranger.
3. **Config and database.** Env-driven settings, safe defaults, migrations from commit one.
4. **The scanner.** Real browser, real `robots.txt`. Test against fixture websites served
   over real HTTP — one deliberately broken, one that scores 100/100.
5. **Fixability — at the same time as the scanner.** If it comes later you will have built an
   outreach pipeline that promises what you cannot deliver, and every later feature needs
   retrofitting with the gate.
6. **The exposure model**, with sources in a data file. If a number cannot be cited, it
   cannot be in an email.
7. **The lint before the email writer.** Build the thing that rejects bad drafts first. It
   changes what you ask the model for.
8. **Outreach, then inbox, then negotiation** — with "the model writes words, the code owns
   numbers and state" enforced from the first line.
9. **Deals and payments.** Subscription mode with a setup fee, tax on, webhook-driven.
   Refunds behind human approval from the start, not as a later safety retrofit.
10. **The fixer.** GitHub PR path first: it is the one needing nothing from the customer.
11. **Orchestrator and dashboard together.** An automated pipeline you cannot see is not
    finished.
12. **The autopilot.** Walk every branch that says "a human should look at this" and give it
    a safe automatic answer.
13. **Adaptive pricing last.** It needs conversion data, which needs everything above.

## 25. Testing

The reference implementation has 137 tests running in about five minutes with no keys and no
network. What makes them worth having:

- **Fixture websites served over real HTTP**, scanned by the real browser: one deliberately
  broken, one that scores 100/100, and one on a host you deliberately have no way into (so
  the fixability gate's *rejection* path is tested, not just its acceptance path).
- **A deterministic fake model** so the whole pipeline — draft, classify, negotiate, close —
  runs end to end with no model calls.
- **A self-audit**: run your own scanner over your own public pages. A company that
  cold-emails small businesses about inaccessible websites, from an inaccessible website, is
  the easiest target in this industry.
- **Freshness tests** that fail if a generated document has drifted from the code.
- **Exercise the error paths.** The one production bug that shipped was in an exception
  handler the fake model could never trigger (§26, B1).

## 26. Problems already hit, and how they were fixed

This is the most valuable section in the document. The bugs are ordinary. The judgement
errors are the expensive ones, because each looked correct until someone asked what the
customer would actually experience.

### A. Judgement errors — caught in review, not by a failing test

**A1. Refunds were automatic.** The first build refunded undeliverable work by itself. That
reads as tidy automation and is in fact the one irreversible, money-losing action in the
system. *Fix:* a `refund_requested` state, an approval queue, and nothing said to the
customer until the owner decides. The owner asked for this explicitly; it would have been
wrong anyway.

**A2. The scores were flattering.** Accessibility engines bucket results into violations,
passes, incomplete and inapplicable. Counting only violations against a fixed denominator
produces a number that is technically derived and practically meaningless — and it was going
into a cold email to a stranger. *Fix:* weighted scoring with an honest denominator,
inapplicable checks excluded from both sides, manual checks excluded entirely and reported
separately.

**A3. A newly added checklist item was reported as a regression.** After the checklist was
versioned, a client's monthly report said "1 thing slipped since last month" about a check
that did not exist last month. That is a false statement to a paying customer. *Fix:*
new-edition checks are excluded from the regression set and get their own paragraph
explaining what changed and that there is no extra charge.

**A4. We were pitching sites we could not fix.** Nothing stopped outreach to a Wix site, and
the only possible delivery would have been a zip file and instructions — not what the email
promised. *Fix:* the fixability gate, on by default (§15).

**A5. Every site behind Cloudflare looked "directly fixable".** The host fingerprints treated
the `cf-ray` header as evidence of Cloudflare Pages. `cf-ray` is present on *every* site
behind Cloudflare's CDN — a large fraction of the web, Wix and Squarespace included — so the
gate from A4 was waving through exactly the sites it existed to exclude. *Fix:* recognise
Git-backed hosting from the hostname (`.pages.dev`, `.netlify.app`, `.vercel.app`,
`.github.io`) and from Netlify's and Vercel's own distinctive headers, and check site
builders *before* any host signal — Wix behind a CDN is still Wix.

**A6. A price change would have moved a quote already given.** Once pricing could move on its
own, a prospect who replied three weeks later would have been quoted from the current ladder,
and the negotiation floor could even have clamped their price *upward* past what the first
email said. *Fix:* stamp the rung on the lead at first contact; every later step reads the
stamp. Paid deals were already safe (the deal row and the processor hold the agreed price) —
the in-flight conversation was not.

**A7. The one-off was priced above the retainer's setup fee.** The reasoning was that a
one-off must carry its own acquisition cost. The customer's reading is that they are charged
more for identical work because they declined a subscription. *Fix:* both $99.

**A8. The negotiation floor was $79.20.** Twenty percent off $99 is arithmetically correct
and is not a price anyone quotes. *Fix:* computed floors round *up* to whole dollars, which
also keeps them above the discount policy's limit.

**A9. The test suite nearly disabled a production gate to make itself pass.** Adding the
fixability gate broke unrelated tests because the fixture HTTP server sent no host headers,
so every fixture site was `not_fixable`. The quick fix — turn the gate off in test settings —
would have meant the production path was never exercised again. *Fix:* make the fixture
server advertise a realistic host header, and add a second fixture on a deliberately
unhostable host so the rejection path is covered too. **Whenever a new gate breaks tests, the
right fix is almost always a better fixture, not a relaxed setting.**

**A10. Cold outreach from a personal Gmail.** Fine for testing, wrong for production: it gets
filtered, and a spam complaint against a personal address cannot be undone. *Fix:* a separate
sending domain with SPF/DKIM/DMARC, a warm-up ramp, and the catch-all reply address tested
before any stranger is contacted.

### B. Bugs

**B1. `NameError` inside the error handler.** Both exception branches of the negotiation
agent referenced undefined names, so the first time the model refused or errored, the error
handler would itself have crashed. No test caught it because the fake model never refuses.
*Fix:* one helper that builds a valid stand-down reply from values actually in scope.
**Lesson: exercise your error paths, or read them adversarially.**

**B2. Raw JSON out of SQLite.** One accessor returned stored JSON columns as strings while
another decoded them; a caller using the wrong one got `'str' object has no attribute 'get'`.
*Fix:* one way to read a row, used everywhere.

**B3. A test helper that lied.** A helper that created "leads emailed at price X" reused the
same domains on its second call, silently re-pricing the first batch, so the conversion
arithmetic in the test was wrong. *Fix:* namespace the fixtures. **A failing assertion is
sometimes the helper, not the code.**

**B4. A tautological assertion.** `body["head"] == "us:" + body["head"].split(":")[1]` cannot
fail. Grep for that shape.

**B5. Hardcoded prices in tests and emails.** One `$9.99` literal in a customer email and
`$499` in three tests all broke on the reprice. *Fix:* derive every price from settings, so
the next reprice touches one file.

**B6. Time arithmetic against a fabricated "now".** A test passed a fixed timestamp in the
past while the record's own timestamp was real wall-clock time, producing negative elapsed
days and a nonsense "next move in 204 days". Production was fine; it is still a trap for any
time-based logic.

**B7. Import and API drift in tests.** Wrong module for a helper, two methods that never
existed, a column name off by one word, a fixture's return tuple in the wrong order. All
trivial, all cost time.

### C. Environment traps

**C1. The subscription CLI must not see an API key.** The child process inherits the
environment; if `ANTHROPIC_API_KEY` is present, the CLI uses it silently and the bill arrives
metered, defeating the entire point of R15.

**C2. Keep the cached prefix small and byte-identical.** Start the headless CLI with a
replaced system prompt and no tools, integrations or project settings. Let the real system
prompt and tool definitions through and every call is a cache miss.

**C3. Usage limits are a normal condition, not an error.** Treating them as failures burns
retries and marks good leads dead.

**C4. Two concurrent test runs starve each other** when both launch browsers. One at a time.

**C5. In a preprovisioned container, do not re-download the browser.** Point at the one
already installed; re-downloading can exhaust the disk allowance.

## 27. Runbook

### Part 1 — dry run, nothing leaves the machine (~30 minutes)

You are both the operator and the prospect. Two rails make it risk-free: dry-run mode, and
the self-test allowlist enforced at the send gate.

1. Install; run the test suite to prove the install.
2. Create the config. Set real company details — legal name, **real postal address**,
   website, from-address — because they go in the footer of every email. Set mode to dry run,
   and set the allowlist to a **second mailbox you control**, which will play the prospect.
3. Run preflight. It should pass: with the allowlist set, the business-readiness checks are
   skipped because no stranger is reachable.
4. Add your own website as a lead, with the second mailbox as its contact address.
5. Scan it. Expect 10–30 seconds, both scores, a findings list, and — for a GitHub Pages
   site — a `direct / github_pr` fixability verdict with the repository inferred.
6. Open the dashboard and spend a few minutes there. This is the visibility layer: funnel,
   lead detail, findings, the report a prospect would see, the outbox with lint results,
   notices, finance, the pricing ladder.
7. Draft and "send". Nothing leaves the machine; read the queued email, check the footer,
   the estimate labels, the sources, and the unsubscribe line.
8. Play the prospect: a question, then a lowball (offer well under the floor and confirm it
   is clamped *up* to the floor, not accepted), then "go ahead and send the link". Watch the
   classified intent and the drafted replies. Then try `unsubscribe`, a hostile message, and
   a deletion request — each should resolve with **zero** items in "needs a human".
9. Simulate payment. Read the welcome email, open the customer setup page, then run a tick
   and inspect the generated fix bundle for your real website: `CHANGES.md`, patched pages
   next to their originals, `robots.txt`, `sitemap.xml`, `llms.txt`.
10. Trigger a refund request and confirm it appears in the approval queue with nothing moved
    and nothing said to the customer.

### Part 2 — real email, still only to you

Create an app password on the sending mailbox. Switch to live mode with SMTP and IMAP
configured, **leave the autonomy switches off** so every message waits for your approval, and
keep the allowlist set. Send one real email to the prospect mailbox, click the report and
unsubscribe links, reply for real, and confirm the reply is matched to its thread and
answered. Then turn the autonomy switches on.

Optionally wire the payment processor in test mode with a forwarded webhook and pay with a
test card, to see the deal marked paid, the fix built and the finance page populated.

### Part 3 — going live to real businesses

1. **The four things that stop being optional** the moment the allowlist is cleared: an
   entity formed, liability insurance, an agreement reviewed by a lawyer, and an encryption
   key generated and backed up off the server. Preflight blocks live sending until each is
   attested.
2. **A sending domain that is not a personal mailbox.** SPF, DKIM, DMARC. A catch-all for
   the `reply+token@` addresses, tested before any stranger is emailed. Ramp the daily cap
   10 → 20 → 40 over three weeks.
3. **A dedicated account for the pull requests**, with a token stored encrypted, then turn
   the fixer on.
4. **Payments live**: live keys, automatic tax switched on with nexus registered where
   applicable, a webhook endpoint on a publicly reachable URL (which is also where report,
   unsubscribe and setup links point).
5. **Clear the allowlist, re-run preflight, prospect a first category and city, and start
   the loop.** Expect most of what is pulled to be dropped before you see it — roughly 6%
   surviving is the designed behaviour, not a fault.
6. **Read the first ten emails before they go.** After ten you will know whether you trust
   it; the lint catches the rest.

**Then, twice a week, five minutes:** "needs a human" should be zero; refunds are the only
thing genuinely waiting on you; watch bounce and complaint rates against the breaker; the
pricing ladder will sit still until 60 emails have gone out and then move on its own; export
the ledger at tax time.

## 28. What is unproven

Be honest with whoever funds or inherits this.

- **Never sent to a real stranger.** Reply rate, complaint rate and conversion are all
  published benchmarks, not measurements.
- **The contact-address rate is the softest assumption** (45%) and it gates the whole funnel.
  It will be the first thing real data corrects.
- **No delivery route for site builders**, which is two fifths of the market. A manual or
  semi-manual route for Wix and Squarespace would move the funnel more than any amount of
  extra prospecting — and would need a different promise in the email.
- **Deliverability is unproven.** No domain has been warmed. The breaker is protection, not
  evidence.
- **Payments have only run in test mode.** Tax registration and nexus are the operator's to
  arrange.
- **The legal posture is risk reduction, not immunity**, and the three readiness flags are
  the operator's word, not a verification.
- **Running a commercial service on an interactive-use subscription** is a question for the
  provider's terms. Keep the metered-API switch one line away.

## 29. Market model

An estimate built from the filters the system actually applies, at 1,000 business listings
pulled per day. Each rate is the share of the previous stage that survives.

| stage | survives | per day | basis |
|---|---:|---:|---|
| business listings pulled | — | 1,000 | ~20 category-and-city queries |
| carries a usable website URL | 85% | 850 | normalisation: social pages, builder subdomains, aggregators, dead links |
| inside the contact policy | 80% | 680 | US-only and none of the excluded trades |
| site loads and can be scanned | 90% | 612 | parked domains, bad certificates, robots exclusions, timeouts — a judgement call |
| a contact address we can find | 45% | 275 | it must be in the HTML; many small sites expose only a form. **The softest number here** |
| scores below the leave-it-alone bar | 90% | 248 | WebAIM's 2025 study of a million home pages found 94.8% with detected WCAG failures |
| **we can actually change it** | 25% | **62** | ~34% of US small-business sites are WordPress or Shopify (Clutch 2025) with the REST API usually reachable, plus a few percent on Git-backed hosts. The 41% on Wix/Squarespace/GoDaddy are excluded on purpose |

**About 6% of listings become a mailable, fixable lead — roughly 60 per 1,000 pulled.**

Supply is not the constraint. Filling a 40-a-day send cap needs about 650 listings, thirteen
queries, a few minutes of traffic. What limits the business is how many strangers a young
sending domain should email in a day, and — far more than the scan — how many small-business
sites run somewhere you have a way in.

At the cap, 40 emails a day is 1,200 a month. Published benchmarks put closed sales between
0.2% and 1% of emails sent: **2 to 12 sales a month**, or $198–$1,188 up front plus
$20–$120/month of new recurring revenue. The recurring half compounds and the up-front half
does not, so after month three the number that matters is how many subscriptions are still
alive — which is also why the price watches its own conversion and moves itself (§11).

**Sources.** [WebAIM Million 2025](https://webaim.org/projects/million/2025) ·
[Clutch, State of Small Business Websites 2025](https://clutch.co/resources/state-of-small-business-websites-2025) ·
[Instantly Cold Email Benchmark Report 2026](https://instantly.ai/cold-email-benchmark-report-2026) ·
[Reachoutly cold email conversion benchmarks](https://reachoutly.com/cold-email/conversion-rate/) ·
[Gartner on search volume decline](https://www.gartner.com/en/newsroom/press-releases/2024-02-19-gartner-predicts-search-engine-volume-will-drop-25-percent-by-2026-due-to-ai-chatbots-and-other-virtual-agents) ·
[ADA.gov web guidance](https://www.ada.gov/resources/web-guidance/) ·
[UsableNet lawsuit reports](https://blog.usablenet.com/ada-web-accessibility-lawsuit-reports) ·
[llms.txt](https://llmstxt.org/) · [Schema.org LocalBusiness](https://schema.org/LocalBusiness)

---

## 30. Done means

You can stop building when all of this is true at once:

1. A stranger's website can be scanned end to end, producing two percentages you would be
   comfortable defending to that stranger, a findings list, an exposure estimate with
   sources, and a fixability verdict.
2. An email can be drafted from that scan, and the lint rejects it if it contains a dollar
   figure the code did not authorise, a forbidden phrase, or a legal conclusion.
3. A reply of every intent in §13 resolves itself without a human, including the hostile
   one, the unclear one and the deletion request.
4. A deal can be quoted, closed, paid and taxed, and the price the prospect was first given
   is the price they pay however the ladder has moved since.
5. A fix can be generated for a real site, delivered as a pull request the owner merges, and
   verified by a rescan that shows the scores moving.
6. A month later the site is rescanned, regressions are fixed, checks added since the last
   measurement are applied and named, and a report goes out — with no extra charge and no
   human involvement.
7. The dashboard shows all of it, and "needs a human" reads zero.
8. The only thing that ever waits on the owner is a refund.
9. Live mode is refused by the code until the entity, the insurance, the lawyer review and
   the encryption key are in place.
10. The whole suite runs green with no API keys and no network.
