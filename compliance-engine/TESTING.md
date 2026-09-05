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
git clone <your repo> && cd compliance-engine
git checkout claude/ada-seo-compliance-outreach-z8r1dv
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

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
| **The report link** on that page | Exactly what a prospect sees: findings, before/after, sourced estimates |
| **Outbox** | Anything queued or held, with the compliance-lint result |
| **Notices** | Everything the autopilot handled on its own |
| **Finance** | Revenue, fees, tax by state, ledger export |

Leave the dashboard running in its own terminal for the rest of this.

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
compliance-engine simulate-reply --lead 1 --text "That's more than I want to spend. Could you do it for $800?"
compliance-engine simulate-reply --lead 1 --text "OK go ahead and send the link"
```

Watch the lead page after each one. You'll see the classified intent, the reply it wrote,
the price held at your floor (not $800), and then a deal at `checkout_sent`.

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
