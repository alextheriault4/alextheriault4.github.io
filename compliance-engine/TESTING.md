# Testing it live on your own site and mailbox

The safe way to see this thing work end to end: **you are both the operator and the
prospect.** It scans your website, emails your mailbox, you reply as a suspicious small
business owner, and it negotiates, invoices, fixes the site and reports back.

Two safety rails make this risk-free:

- `CE_LEGAL__ONLY_EMAIL_ADDRESSES` — a hard allowlist at the send gate. With it set, mail
  physically cannot go to anyone but you, whatever the pipeline decides.
- `CE_MODE=dry_run` for Part 1, so nothing leaves the machine at all.

Every command below was run start to finish before this was written.

---

## Before you start

You need:

- Python 3.11+, and the repo checked out.
- The `claude` CLI, signed in (`claude` once, interactively). That is what bills the work
  to your Claude subscription instead of an API key.
- **A second mailbox** to play the prospect — another Gmail, Outlook, Proton, anything
  free. Call it `PROSPECT@example.com` below. You *can* use a `+prospect` alias on your
  own Gmail instead, but a separate mailbox makes it obvious which side is which and
  avoids Gmail's habit of hiding mail you sent to yourself.

```bash
git clone https://github.com/alextheriault4/alextheriault4.github.io.git
cd alextheriault4.github.io/compliance-engine
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

Everything is on `main`. Sanity-check the install with `pytest -q` — 137 tests, about five
minutes, and it needs no keys or network.

If `compliance-engine` isn't on your PATH after that, use `python -m engine` instead —
identical behaviour.

---

# Part 1 — Dry run (30 minutes, nothing leaves your machine)

## Step 1. Create the config

```bash
compliance-engine init
```

That writes `data/engine.db` and a `.env`. Open `.env` and set these — real values, they
go in the footer of every email:

```ini
CE_MODE=dry_run
CE_LLM__PROVIDER=claude_code          # your Claude subscription

CE_COMPANY__NAME=Theriault Web Access
CE_COMPANY__LEGAL_NAME=Theriault Web Access LLC
CE_COMPANY__POSTAL_ADDRESS=<your real street address>
CE_COMPANY__WEBSITE=https://alextheriault4.github.io
CE_COMPANY__FROM_NAME=Alex
CE_COMPANY__FROM_EMAIL=alextheriault4@gmail.com
CE_COMPANY__REPLY_DOMAIN=gmail.com
CE_COMPANY__REPLY_LOCAL_PART=alextheriault4
CE_COMPANY__SIGNER_NAME=Alex Theriault
CE_COMPANY__SUPPORT_EMAIL=alextheriault4@gmail.com

CE_DASHBOARD__ADMIN_TOKEN=<pick any password>

# The rail. Nothing can be emailed to anyone else while this is set.
CE_LEGAL__ONLY_EMAIL_ADDRESSES=["PROSPECT@example.com"]
```

`REPLY_LOCAL_PART` matters: replies come back to
`alextheriault4+<thread token>@gmail.com`, which is how a reply gets matched to its
conversation. Gmail delivers plus-addresses to your normal inbox.

## Step 2. Confirm it will let you run

```bash
compliance-engine preflight
```

Expect `preflight: ready to go live`. Because the allowlist is set, the engine skips the
checks that only exist to protect strangers (entity, insurance, lawyer review) — you
cannot reach a stranger. Clear the allowlist and those come straight back.

## Step 3. Point it at your own website

```bash
compliance-engine add-leads \
  --url https://alextheriault4.github.io \
  --name "Alex Theriault" --category "web design" \
  --city Springfield --region IL \
  --email PROSPECT@example.com
```

## Step 4. Scan it

```bash
compliance-engine scan --limit 1
compliance-engine status
```

Takes 10–30 seconds. It opens headless Chromium, fetches your `robots.txt` first, obeys
it, runs axe-core over your pages, and checks the AI-search signals. `status` should show
`"leads": {"scanned": 1}`.

The scan also works out **how we would change the site**. Your site is on GitHub Pages, so
it should come back as `direct` / `github_pr` with the repository worked out from the
domain — that is the case where the customer grants us nothing at all. If a lead comes back
`not_fixable`, that is the gate doing its job: we do not email people whose sites we could
not actually fix. You will see it on the lead page under "Site access".

## Step 5. Look at what it found

```bash
compliance-engine dashboard
```

Open <http://127.0.0.1:8787>, enter your `CE_DASHBOARD__ADMIN_TOKEN`. **This is the
visibility layer — spend a few minutes here:**

| Where | What you're looking at |
|---|---|
| **Overview** | Funnel counts, gates (what's allowed to happen and why not), the self-test banner, notices, last tick |
| **Leads → your site** | Both scores, every finding with severity, the exposure estimate, the full email thread, timeline |
| **Leads → your site → Site access** | How we would apply the fix (`github_pr` here), and once there is a deal, the customer's own setup link |
| **The report link** on that page | Exactly what a prospect sees: findings, before/after, sourced estimates |
| **Outbox** | Anything queued or held, with the compliance-lint result |
| **Notices** | Everything the autopilot handled on its own |
| **Finance** | Revenue, fees, tax by state, ledger export |
| **Overview → Pricing** | The price ladder: what each rung has been emailed, replied to, sold, and earned, plus what would move it next |

Leave the dashboard running in its own terminal for the rest of this. The same pricing table
is available without the browser:

```bash
compliance-engine pricing
```

Nothing will move it yet — a price is only judged after 60 emails have actually gone out at
it, and a dry run sends none.

## Step 6. Draft and "send" the first email

```bash
compliance-engine draft
compliance-engine send --now
```

`--now` matters: cold email normally waits for a weekday inside business hours, so without
it an evening test looks like nothing happened.

In dry run the "sending" writes to `data/outbox/`:

```bash
ls data/outbox/
cat data/outbox/*.json | head -40
```

Check the `Reply-To` is `alextheriault4+<token>@gmail.com`, that every dollar figure is
labelled an estimate with sources, and that the unsubscribe line is there.

## Step 7. Play the prospect

```bash
compliance-engine simulate-reply --lead 1 --text "Interesting. What exactly would you change?"
compliance-engine simulate-reply --lead 1 --text "That's more than I want to spend. Could you do it for $40?"
compliance-engine simulate-reply --lead 1 --text "OK go ahead and send the link"
```

Watch the lead page after each one. You'll see the classified intent, the reply it wrote,
the price held at your floor (not $40), and then a deal at `checkout_sent`. The lead page
also shows which rung of the price ladder that prospect was pinned to; it will not change
even if the engine later moves the price.

Worth trying the edge cases too — each should resolve itself with **zero** items in "Needs
a human":

```bash
compliance-engine simulate-reply --lead 1 --text "unsubscribe"          # instant, permanent
compliance-engine simulate-reply --lead 1 --text "This is a scam, I'm calling my lawyer"   # one apology, then silence
compliance-engine simulate-reply --lead 1 --text "delete my data"       # erases everything
```

(Use a fresh lead for each, or re-add the lead — an unsubscribe is permanent by design.)

## Step 8. Take the payment and build the fix

```bash
compliance-engine simulate-payment --deal 1
```

Before the fix runs, look at what the customer just received. In **Outbox** there is a new
"welcome" email telling them how we get in — for a GitHub site whose repository we already
know, that is "nothing to set up; a pull request will arrive and you press Merge". It also
restates the monthly promise: when the rules change, their site is measured against the new
checks at no extra cost.

The link in that email is their setup page. Open it (it needs no login — the token is the
credential):

```bash
python - <<'EOF'
from engine.config import get_settings
from engine.db import Database
from engine import onboarding
s = get_settings(); db = Database(s.database_path)
print(onboarding.setup_url(s, onboarding.setup_token(db, 1)))
EOF
```

That page is what a customer on a custom domain would use to paste their repository
address, or a WordPress customer to paste an application password. Nothing else is ever
asked of them. If they ignore it, one reminder goes out after two days and after three days
the engine stops waiting and delivers the files instead.

Now build the fix:

```bash
compliance-engine tick
```

Then look at what it produced for **your actual website**:

```bash
find data/fixes -type f | head -20
cat data/fixes/*/1/CHANGES.md
```

`CHANGES.md` maps every edit to the finding it resolves. `pages/` holds patched copies
next to `.orig` originals so you can diff them. There's also `robots.txt`, `sitemap.xml`,
`llms.txt` and a header snippet.

## Step 9. See the refund approval queue

Refunds never happen on their own. To see the queue:

```bash
python - <<'EOF'
from engine.config import get_settings
from engine.db import Database
from engine.autopilot import request_refund
s = get_settings(); db = Database(s.database_path)
request_refund(db, s, 1, "test: pretending the client never published")
EOF

compliance-engine refunds
```

The dashboard overview now shows **"Refunds waiting on you"** with Refund / Keep the money
buttons. Nothing has moved and the customer has been told nothing. Approve or decline:

```bash
compliance-engine refunds --decline 1 --note "just testing"
```

---

# Part 2 — Live email (real messages, still only to you)

Everything above ran without sending anything. Now make it real.

## Step 10. Get an app password

Gmail needs 2-Step Verification on, then <https://myaccount.google.com/apppasswords> →
create one for "Mail". It's a 16-character string. (Your normal password will not work.)

## Step 11. Switch on live sending

Add to `.env`:

```ini
CE_MODE=live
CE_EMAIL__PROVIDER=smtp
CE_EMAIL__SMTP_HOST=smtp.gmail.com
CE_EMAIL__SMTP_PORT=587
CE_EMAIL__SMTP_USER=alextheriault4@gmail.com
CE_EMAIL__SMTP_PASSWORD=<the 16-char app password>
CE_EMAIL__IMAP_HOST=imap.gmail.com
CE_EMAIL__IMAP_USER=alextheriault4@gmail.com
CE_EMAIL__IMAP_PASSWORD=<the same app password>
CE_EMAIL__DOMAIN_VERIFIED=true        # true for gmail.com: Google already publishes SPF/DKIM/DMARC

# Leave these OFF for the first live run so you approve each message by hand.
CE_AUTONOMY__AUTO_SEND_OUTREACH=false
CE_AUTONOMY__AUTO_REPLY=false
```

Confirm the allowlist is still set to `PROSPECT@example.com`. Then:

```bash
compliance-engine preflight    # must still say ready
compliance-engine status       # check "self_test_allowlist" shows your address
```

## Step 12. First live email, with you as the gate

```bash
compliance-engine add-leads --url https://alextheriault4.github.io \
  --name "Alex Theriault" --category "web design" --city Springfield --region IL \
  --email PROSPECT@example.com
compliance-engine scan --limit 1
compliance-engine draft
compliance-engine send --now
```

With autonomy off, the message is **held**, not sent. Go to **Outbox** in the dashboard,
read it one more time, and press **Approve & send**. Then:

```bash
compliance-engine send --now
```

Check `PROSPECT@example.com`. A real email should be there. Click the report link and the
unsubscribe link (they point at `http://127.0.0.1:8787`, so use the browser on the same
machine; if you want them to work from your phone, run a tunnel like
`cloudflared tunnel --url http://localhost:8787` and set `CE_STRIPE__PUBLIC_BASE_URL` to
the tunnel URL).

## Step 13. Reply for real

From `PROSPECT@example.com`, hit reply and write something like *"What exactly would you
change, and do you need our login?"*. Then:

```bash
compliance-engine tick
```

`tick` polls IMAP for unread mail, matches the reply to its thread by the plus-address or
`In-Reply-To`, classifies it, and drafts an answer. Look at the lead page to see the
inbound message and the classified intent, then approve the reply in the Outbox and
`send --now` again.

Once you trust it, turn the switches on and stop approving:

```ini
CE_AUTONOMY__AUTO_SEND_OUTREACH=true
CE_AUTONOMY__AUTO_REPLY=true
```

## Step 14. Real payment plumbing (optional)

Use **Stripe test mode** so no real money moves:

```ini
CE_STRIPE__SECRET_KEY=sk_test_...
CE_AUTONOMY__AUTO_SEND_CHECKOUT=true
```

For the webhook, run Stripe's CLI in another terminal:

```bash
stripe listen --forward-to localhost:8787/webhooks/stripe
# it prints whsec_... — put that in CE_STRIPE__WEBHOOK_SECRET and restart the dashboard
```

Reply "go ahead" from the prospect mailbox, `compliance-engine tick`, open the checkout
link that arrives, pay with test card `4242 4242 4242 4242` (any future expiry, any CVC).
The webhook marks the deal paid, the next `tick` builds the fix, and Finance shows the
charge, the fee estimate and the tax line.

## Step 15. Let it run by itself

```bash
compliance-engine run
```

One process, ticking every 5 minutes. Watch it from the dashboard. `deploy/*.service` has
systemd units for running the loop and the dashboard permanently.

---

# Part 3 — Going live to real businesses

Everything above was you emailing yourself. This part is the one that involves strangers,
so it is deliberately more work.

## Step 16. The four things that stop being optional

The moment `CE_LEGAL__ONLY_EMAIL_ADDRESSES` is cleared, `preflight` starts demanding these
and the send gate stays shut until each is true. They are attestations — setting the flag
does not do the thing, it records that you did it:

```ini
CE_LEGAL__BUSINESS_ENTITY_FORMED=true      # an LLC, so a claim lands on the company
CE_LEGAL__LIABILITY_INSURANCE=true         # errors-and-omissions cover, bought before you take money
CE_LEGAL__AGREEMENT_REVIEWED_BY_LAWYER=true
CE_SECRETS_KEY=<generate below>            # client credentials are encrypted at rest
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

What the lawyer should read: the agreement at `/agreement/<deal id>`, the terms at `/terms`,
and one real drafted email. What you are asking them is narrow — does this promise anything
we do not deliver, and does anything here read as legal advice. The README's "Legal risk"
section lists what the engine already refuses to say and why.

Back up `CE_SECRETS_KEY` somewhere other than the server. Lose it and every stored client
credential is unreadable.

## Step 17. A sending domain that is not your personal Gmail

Cold outreach from `gmail.com` gets filtered, and a spam complaint against your personal
address is a problem you cannot undo. Buy a separate domain — a lookalike of your main one
is normal practice — and set up SPF, DKIM and DMARC with the mailbox provider. Then:

```ini
CE_COMPANY__FROM_EMAIL=alex@outreach.yourcompany.com
CE_COMPANY__REPLY_DOMAIN=outreach.yourcompany.com
CE_COMPANY__REPLY_LOCAL_PART=reply
CE_EMAIL__DOMAIN_VERIFIED=true             # only after you have actually checked the records
```

Replies come back to `reply+<thread token>@outreach.yourcompany.com`, so that mailbox needs
a **catch-all** or plus-addressing. Test it by emailing `reply+test@` and confirming it
arrives before you send anything to a stranger.

Warm the domain up: `CE_OUTREACH__DAILY_SEND_CAP=10` for the first week, 20 the second, then
40. A new domain sending 40 cold emails on day one is how you get a poor reputation you then
have to buy your way out of.

## Step 18. The GitHub account that opens the pull requests

Fixes on GitHub-hosted sites are delivered as a pull request from a fork, so the engine
needs a token for the account whose name will appear on those PRs. Use a dedicated account,
not your personal one. A fine-grained token with public-repository read and write, or a
classic token with `public_repo`, is enough:

```bash
compliance-engine secret --set github_token     # prompts, nothing appears on screen
compliance-engine secret                        # confirms it is stored
```

It is encrypted with `CE_SECRETS_KEY`. Then turn the fixer on:

```ini
CE_AUTONOMY__AUTO_APPLY_FIXES=true
```

## Step 19. Stripe for real

```ini
CE_STRIPE__SECRET_KEY=sk_live_...
CE_STRIPE__WEBHOOK_SECRET=whsec_...        # from the endpoint you create in the dashboard
CE_STRIPE__PUBLIC_BASE_URL=https://app.yourcompany.com
CE_AUTONOMY__AUTO_SEND_CHECKOUT=true
```

Turn on **Stripe Tax** in the Stripe dashboard and register where you have nexus — the
engine asks Stripe to compute tax, it does not invent rates. Create the webhook endpoint at
`https://app.yourcompany.com/webhooks/stripe` and subscribe it to
`checkout.session.completed`, `invoice.paid` and `customer.subscription.deleted`.

`CE_STRIPE__PUBLIC_BASE_URL` is also where report, unsubscribe and setup links point, so it
has to be reachable from the outside — a small VPS, or `cloudflared tunnel` to start with.

## Step 20. Take the rail off and start small

```ini
# delete this line entirely
# CE_LEGAL__ONLY_EMAIL_ADDRESSES=[...]
CE_MODE=live
CE_AUTONOMY__AUTO_SEND_OUTREACH=true
CE_AUTONOMY__AUTO_REPLY=true
CE_OUTREACH__DAILY_SEND_CAP=10
```

```bash
compliance-engine preflight     # must be clean; it names anything missing
compliance-engine prospect --category dentist --city Springfield --region IL --limit 50
compliance-engine status
compliance-engine run
```

`prospect` pulls from OpenStreetMap for free (no key). Add `CE_PROSPECTING__GOOGLE_PLACES_KEY`
for much better coverage. Most of what it pulls will be dropped before you ever see it —
that is the funnel in `MARKET.md` doing its job, and roughly 6% surviving is the expected
shape, not a fault.

## Step 21. What to look at, and how often

Five minutes on the dashboard, twice a week:

| Look at | You want to see |
|---|---|
| **Needs a human** | zero. Anything here is a case the autopilot could not close |
| **Refunds waiting on you** | the only thing that ever genuinely blocks on you |
| **Replies** | bounce and complaint rates under the breaker's limits; if the breaker trips, sending stops on its own |
| **Pricing** | the ladder. It will sit at $99 until 60 emails have gone out, then move on its own if it needs to |
| **Finance** | charges, fees, tax by state. Export the ledger at tax time |
| **Notices** | everything the autopilot decided without asking. Worth reading for the first month, skimmable after |

The one thing worth doing by hand early: read the first ten emails it sends before they go,
by leaving `CE_AUTONOMY__AUTO_SEND_OUTREACH=false` for the first batch. After ten you will
know whether you trust it, and the compliance lint catches the rest.

---

## Things that will confuse you if nobody warns you

| Symptom | Cause |
|---|---|
| `send` reports `skipped` | Outside the weekday 09:00–17:00 send window. Use `send --now` |
| Email is `held` | An autonomy switch is off — approve it in the Outbox, which is the intended behaviour until you trust it |
| Email is `suppressed` with "not on ...ONLY_EMAIL_ADDRESSES" | The allowlist did its job |
| Nothing sends and gates say "preflight not passed" | `compliance-engine preflight` lists exactly what's missing |
| A lead goes to `excluded` | The contact policy refused it (non-US, law firm, `.gov`, etc.). Intended |
| Lead sits at `scanned` with a future `next_action_at` | Claude subscription usage limit hit; it retries in an hour. `compliance-engine status` shows the provider |
| `clean` instead of an email | Your site scored too well to pitch. Test against `tests/fixtures/sites/bad_site` instead |
| No reply picked up | Gmail put it somewhere other than INBOX, or it was already read. IMAP only fetches UNSEEN in INBOX |

## When you're done testing

```bash
# stop everything reaching anyone
compliance-engine dashboard   # → Pause
```

Before you ever point this at real businesses, clear `CE_LEGAL__ONLY_EMAIL_ADDRESSES` —
and note that `preflight` will immediately start demanding the entity, the insurance and
the lawyer review, because at that point you are emailing strangers. See the "Legal risk"
section of the README for what that means and what it does not cover.
