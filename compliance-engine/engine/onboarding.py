"""Getting permission to change the site, without making the customer work for it.

The moment someone pays, the clock is running on the promise we made in the outreach. What
usually kills that promise is access: the agency asks for FTP details, the owner does not
have them, and three weeks later everyone is annoyed.

So access is arranged the easiest way each platform allows, and the customer is told exactly
which one applies to them:

``github_pr``       Nothing at all. We fork the public repository, open a pull request, and
                    they press the green Merge button. No credentials ever change hands.
``wordpress_rest``  One application password, which is four clicks inside the WordPress admin
                    they are already logged in to. It is revocable and never their real
                    password. We store it encrypted and delete it after delivery.
``header_snippet``  A block of HTML to paste once. Only reachable if the fixability gate is
                    switched off - we do not pitch these.

Everything here is idempotent, so a retried tick cannot double-send or double-store.
"""
from __future__ import annotations

import secrets
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .db import Database, utcnow
from .exposure import money
from .legal import SecretBox
from .models import EventKind, MessageStatus
from .outreach.compose import to_html

# How long we wait for access before falling back to sending the finished files with
# instructions. Nobody's money sits idle because a form was never filled in.
ACCESS_WAIT_DAYS = 3
REMIND_AFTER_DAYS = 2


@dataclass
class AccessState:
    channel: str                 # github_pr | wordpress_rest | header_snippet | none
    ready: bool                  # can we apply the fix right now?
    headline: str                # one line, for the email and the dashboard
    steps: list[str] = field(default_factory=list)
    needs_form: bool = False     # does the setup page need to collect something?
    repo: str | None = None
    granted_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"channel": self.channel, "ready": self.ready, "headline": self.headline,
                "steps": self.steps, "needs_form": self.needs_form, "repo": self.repo,
                "granted_at": self.granted_at}


def setup_token(db: Database, lead_id: int) -> str:
    """A stable, unguessable link for this customer's setup page."""
    key = f"lead:{lead_id}:setup_token"
    token = db.get_kv(key)
    if not token:
        token = secrets.token_urlsafe(16)
        db.set_kv(key, token)
    return token


def setup_url(settings: Settings, token: str) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/setup/{token}"


def lead_for_token(db: Database, token: str) -> dict[str, Any] | None:
    row = db.one("SELECT key FROM kv WHERE key LIKE 'lead:%:setup_token' AND value = ?", (token,))
    if not row:
        return None
    return db.get_lead(int(row["key"].split(":")[1]))


def normalise_repo(raw: str) -> str | None:
    """Accept whatever they paste: a URL, an SSH remote, or just owner/name."""
    text = (raw or "").strip()
    m = re.search(r"github\.com[/:]([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", text)
    if m:
        return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    m = re.fullmatch(r"([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", text)
    if m:
        return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return None


def access_state(db: Database, settings: Settings, lead: dict[str, Any]) -> AccessState:
    """What we need from this customer, if anything, and whether we already have it."""
    channel = lead.get("fix_channel") or "none"
    granted = lead.get("access_granted_at")
    site = lead.get("domain") or "your site"

    if channel == "github_pr":
        repo = db.get_kv(f"lead:{lead['id']}:github_repo") or lead.get("repo")
        if repo:
            return AccessState(
                channel, True,
                f"Nothing to set up - we'll open a pull request on {repo} and you press Merge.",
                steps=[f"We open a pull request on {repo} with every change listed and explained.",
                       "You (or whoever maintains the site) read it and press Merge.",
                       "Your site rebuilds, we rescan it, and you get the before/after report."],
                repo=repo, granted_at=granted)
        return AccessState(
            channel, False,
            "One thing to tell us: which repository your site is built from.",
            steps=["Open your site's repository on GitHub and copy the address from the browser bar.",
                   "Paste it below. That is the whole setup - no password, no access token.",
                   "We open a pull request there; you press Merge and your site rebuilds."],
            needs_form=True, granted_at=granted)

    if channel == "wordpress_rest":
        have = bool(db.get_kv(f"lead:{lead['id']}:wp_app_password"))
        return AccessState(
            channel, have,
            "Four clicks in WordPress and we can apply everything for you."
            if not have else "Access received - we're applying the changes now.",
            steps=[f"Sign in to {site}/wp-admin (you are probably already signed in).",
                   "Go to Users, then Profile, and scroll to Application Passwords.",
                   "Type a name - \"Accessibility fixes\" - and press Add New Application Password.",
                   "Copy the code it shows you and paste it below. It is not your password, "
                   "it only works for this, and you can revoke it from the same screen at any time."],
            needs_form=not have, granted_at=granted)

    if channel == "header_snippet":
        return AccessState(
            channel, False,
            "Your platform has no way to let us in, so we'll send you the changes to paste.",
            steps=["We email you the finished code with exactly where each piece goes.",
                   "Most of it is one block in your site's header settings.",
                   "Tell us when it's live and we rescan and send the before/after report."],
            granted_at=granted)

    return AccessState("none", False, "We'll email you the finished changes with instructions.",
                       granted_at=granted)


def grant_github(db: Database, settings: Settings, lead_id: int, repo_raw: str) -> tuple[bool, str]:
    repo = normalise_repo(repo_raw)
    if not repo:
        return False, "That doesn't look like a GitHub repository address."
    db.set_kv(f"lead:{lead_id}:github_repo", repo)
    _record(db, lead_id, "github_pr", repo=repo)
    return True, repo


def grant_wordpress(db: Database, settings: Settings, lead_id: int, *, site_url: str,
                    username: str, app_password: str) -> tuple[bool, str]:
    if not (username.strip() and app_password.strip()):
        return False, "We need both the WordPress username and the application password."
    if not settings.secrets_key:
        # Refuse rather than write someone's credential to disk in the clear.
        return False, "This installation cannot store credentials securely yet."
    box = SecretBox(settings.secrets_key)
    db.set_kv(f"lead:{lead_id}:wp_url", (site_url or "").strip())
    db.set_kv(f"lead:{lead_id}:wp_user", username.strip())
    db.set_secret(f"lead:{lead_id}:wp_app_password", app_password.strip().replace(" ", ""), box)
    _record(db, lead_id, "wordpress_rest")
    return True, "ok"


def _record(db: Database, lead_id: int, channel: str, **detail: Any) -> None:
    lead = db.get_lead(lead_id)
    if lead and not lead.get("access_granted_at"):
        db.update("leads", lead_id, access_granted_at=utcnow())
    db.log_event(EventKind.ACCESS_GRANTED, lead_id, channel=channel, **detail)


# ---------------------------------------------------------------------------------------
# The welcome email


def welcome_body(settings: Settings, lead: dict[str, Any], deal: dict[str, Any],
                 state: AccessState, url: str) -> str:
    from . import plans as plan_lib

    plan = plan_lib.get(settings, deal.get("plan") or deal.get("package") or "care")
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(state.steps, 1))
    ask = (f"Everything is here, and it takes about a minute:\n{url}"
           if state.needs_form else
           f"There is nothing for you to do right now. If you want to follow along:\n{url}")
    return "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"Payment received - thank you. Work on {lead['domain']} starts today.",
        state.headline,
        steps,
        ask,
        ("Your plan also keeps the site checked every month against the current rules. When the "
         "accessibility guidelines or the way AI search reads sites change, your site gets brought "
         "up to the new standard at no extra cost - that is what the monthly fee is for."
         if plan and plan.monthly_cents else
         "This is the one-off fix. If you'd like the monthly check that keeps it fixed as the rules "
         f"change, reply and we'll add it for {money(settings.pricing.care_monthly_cents)} a month."),
        "Reply to this email if anything is unclear - a person reads it.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}",
    ])


def queue_welcome(db: Database, settings: Settings, deal_id: int) -> int | None:
    """Send the access instructions. Safe to call twice; the second call does nothing."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if not deal:
        return None
    lead = db.get_lead(deal["lead_id"])
    if not lead or not lead.get("contact_email"):
        return None
    if db.one("SELECT id FROM messages WHERE lead_id=? AND kind='welcome'", (lead["id"],)):
        return None
    thread = db.thread_for_lead(lead["id"])
    token = thread[0]["thread_token"] if thread else setup_token(db, lead["id"])
    last_in = next((m for m in reversed(thread) if m["direction"] == "in"), None)
    state = access_state(db, settings, lead)
    url = setup_url(settings, setup_token(db, lead["id"]))
    body = welcome_body(settings, lead, deal, state, url)
    return db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "welcome",
        "subject": f"You're set up - here's how we get into {lead['domain']}"
                   if state.needs_form else f"You're set up - we're starting on {lead['domain']}",
        "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{token}.welcome@{settings.company.reply_domain}>",
        "in_reply_to": last_in["message_id"] if last_in else None,
        "status": MessageStatus.QUEUED, "lint": {"ok": True, "problems": []}, "created_at": utcnow(),
    })


def queue_reminder(db: Database, settings: Settings, lead: dict[str, Any], state: AccessState) -> int | None:
    """One nudge, once, when we are still waiting on the one thing we asked for."""
    if db.one("SELECT id FROM messages WHERE lead_id=? AND kind='access_reminder'", (lead["id"],)):
        return None
    thread = db.thread_for_lead(lead["id"])
    token = thread[0]["thread_token"] if thread else setup_token(db, lead["id"])
    url = setup_url(settings, setup_token(db, lead["id"]))
    body = "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"Your changes for {lead['domain']} are built and waiting. We just need the one thing "
        f"from the last email: {state.headline.lower()}",
        url,
        f"If it's easier, reply to this email with it and we'll take it from there. If we haven't "
        f"heard back in a couple of days we'll send you the finished files with instructions instead, "
        f"so nothing is stuck either way.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}",
    ])
    return db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "access_reminder",
        "subject": f"One quick thing to finish {lead['domain']}",
        "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{token}.access@{settings.company.reply_domain}>",
        "status": MessageStatus.QUEUED, "lint": {"ok": True, "problems": []}, "created_at": utcnow(),
    })


def deals_ready_to_fix(db: Database, settings: Settings, now: datetime | None = None) -> list[int]:
    """Paid deals we can start on: access granted, or we have waited long enough."""
    now = now or datetime.now(timezone.utc)
    out: list[int] = []
    rows = db.query("SELECT d.* FROM deals d WHERE d.status='paid' AND NOT EXISTS "
                    "(SELECT 1 FROM fixes f WHERE f.deal_id=d.id) ORDER BY d.id")
    for deal in rows:
        lead = db.get_lead(deal["lead_id"])
        if not lead:
            continue
        state = access_state(db, settings, lead)
        if state.ready or not state.needs_form:
            out.append(deal["id"])
            continue
        paid_at = _parse(deal.get("paid_at"))
        if paid_at and now - paid_at >= timedelta(days=ACCESS_WAIT_DAYS):
            # We will not hold their work hostage to a form. Deliver the files instead.
            db.add_notice(lead["id"], f"{lead['domain']}: no access after {ACCESS_WAIT_DAYS} days; "
                                      "delivering the changes as files instead")
            out.append(deal["id"])
    return out


def chase_access(db: Database, settings: Settings, now: datetime | None = None) -> int:
    """Remind anyone we are still waiting on, once."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    for deal in db.query("SELECT * FROM deals WHERE status IN ('paid','in_progress')"):
        lead = db.get_lead(deal["lead_id"])
        if not lead or not lead.get("contact_email") or lead.get("access_granted_at"):
            continue
        state = access_state(db, settings, lead)
        if not state.needs_form:
            continue
        paid_at = _parse(deal.get("paid_at"))
        if paid_at and now - paid_at >= timedelta(days=REMIND_AFTER_DAYS):
            if queue_reminder(db, settings, lead, state):
                sent += 1
    return sent


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
