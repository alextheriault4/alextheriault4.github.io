"""Everything that would otherwise land in your lap.

The rule here is that a dead end is never a question for a human. Each one has a safe,
boring, pre-decided answer, and the engine takes it:

============================  ===========================================================
Dead end                      What happens instead of asking you
============================  ===========================================================
Draft fails the lint          Repaired with the lint's own complaints fed back, then
                              replaced by a template that cannot fail the lint.
Model refuses or errors       Same template.
No model capacity             The lead waits an hour and tries again. Nothing is wrong.
Reply is unclear              One short clarifying question; if still unclear, close
                              politely and stop. Never a third email.
Reply is hostile or legal      Stand down: apologise once, suppress the address forever,
                              close the file. Nothing is argued.
Wrong person, no forwarding   Close the file.
Asked for something we         Politely decline the extra and restate the packages.
don't sell
Fix build fails                Retry once, then queue a refund **for your approval**.
Fix never goes live            Two reminders, then queue a refund **for your approval**.
============================  ===========================================================

**Refunds are the deliberate exception.** The engine decides a refund is warranted and
then stops: nothing is charged back and the customer is told nothing until you approve
it. Money leaving your account is a decision about your business, not a dead end to be
tidied away. Pending refunds appear on the dashboard and in ``compliance-engine refunds``.

The distinction that matters elsewhere: a **notice** tells you something happened and
needs nothing from you; an **escalation** blocks a lead until you act. With the autopilot
on, normal operation produces notices, no escalations, and the occasional refund to okay.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import schemas
from .config import Settings
from .db import Database, utcnow
from .exposure import money
from .llm import LLM, LLMCapacityError, LLMError, LLMRefusal
from .models import DealStatus, LeadStatus, MessageStatus

# Replies that mean "stop, and do not make this worse by answering cleverly".
HOSTILE_MARKERS = (
    "attorney", "lawyer", "sue you", "suing", "legal action", "litigation", "cease and desist",
    "report you", "ftc", "attorney general", "spam complaint", "scam", "fraud", "harassment",
    "gdpr", "ccpa", "data protection", "unsolicited", "how did you get my", "stop contacting",
)
DELETE_REQUEST_MARKERS = ("delete my data", "delete my information", "remove my data", "erase my data",
                          "right to be forgotten", "data deletion")


def enabled(settings: Settings) -> bool:
    return settings.autopilot.enabled


# ---------------------------------------------------------------------------
# Deferral: capacity problems are not escalations
# ---------------------------------------------------------------------------

def defer(db: Database, settings: Settings, lead_id: int | None, stage: str, error: Exception) -> None:
    """Park a lead until there is model capacity again. No human involvement."""
    minutes = settings.autopilot.capacity_backoff_minutes
    when = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    if lead_id is not None:
        db.update("leads", lead_id, next_action_at=when)
    db.log_event("deferred", lead_id, stage=stage, retry_at=when, reason=str(error)[:300])


# ---------------------------------------------------------------------------
# Outreach that cannot fail the lint
# ---------------------------------------------------------------------------

def safe_outreach_paragraphs(ctx: dict[str, Any]) -> list[str]:
    """A first email built from fixed sentences and pre-approved figures.

    Every clause here is deliberately dull and every number comes from the exposure
    model, so the compliance lint passes by construction. This is what goes out when the
    model's own draft cannot be made to pass.
    """
    issues = ctx.get("top_issues") or []
    listed = "; ".join(i.get("plain", "") for i in issues[:3] if i.get("plain"))
    domain = ctx.get("domain", "your website")
    exposure = ctx.get("exposure", {})
    return [
        f"I ran an automated accessibility and search check on {domain} this week and thought the "
        f"results were worth passing along.",
        (f"The scan flagged a few things: {listed}." if listed
         else "The scan flagged a handful of accessibility and search issues."),
        (f"For context, settlements in web accessibility claims against small businesses have been "
         f"reported in the {exposure.get('ada_low', '')} to {exposure.get('ada_typical', '')} range once legal "
         f"fees are counted. That is an estimate from published figures, not a prediction about you."),
        f"We fix the items the report lists for a flat {ctx.get('price')} ({ctx.get('recommended_package')} package), "
        f"normally within {ctx.get('turnaround', '10 business days')}, and rescan afterwards so you can see the change.",
        "If you would like the full report, or would like us to go ahead, just reply to this email.",
    ]


def repair_prompt(problems: list[str]) -> str:
    return ("Your previous draft was rejected by our compliance checker for these reasons:\n- "
            + "\n- ".join(problems)
            + "\n\nWrite it again, fixing every one of them. Use only the dollar figures in the context "
              "JSON, exactly as written. Say nothing about what the law requires or what will happen to them.")


# ---------------------------------------------------------------------------
# Canned replies for the situations that used to escalate
# ---------------------------------------------------------------------------

def stand_down_body(settings: Settings) -> str:
    """One short, non-argumentative reply to anything hostile, then silence.

    Arguing with an angry recipient is how a complaint becomes a filing. This apologises,
    confirms removal, and stops.
    """
    return (
        "Thanks for telling me, and I'm sorry for the intrusion. I've removed your address from our "
        "list permanently and you won't hear from us again. If you'd like the scan data we held about "
        f"your site deleted as well, reply with the word \"delete\" and we'll erase it and confirm."
    )


def clarify_body(business: str | None) -> str:
    return (
        "Sorry, I don't think I followed that. To make sure I don't waste your time: would you like me "
        "to send the full accessibility and AI-search report for your site, or would you rather I close "
        "the file and stop emailing? Either answer is fine."
    )


def polite_close_body() -> str:
    return (
        "No problem at all, I'll close the file here so this doesn't clutter your inbox. If it becomes "
        "useful later, the report is still available at the link below. Thanks for your time."
    )


def out_of_scope_body(settings: Settings, ctx: dict[str, Any]) -> str:
    p = settings.pricing
    return (
        "Thanks for asking. We only do the two things in the report: fixing the accessibility issues it "
        f"lists ({money(p.ada_cents)}), and the AI-search readiness work ({money(p.aiseo_cents)}), or both "
        f"together ({money(p.bundle_cents)}). Anything beyond that isn't something we take on, so I'd rather "
        "say so than over-promise. If either package is useful, reply and I'll send the payment link."
    )


def is_hostile(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in HOSTILE_MARKERS)


def wants_deletion(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in DELETE_REQUEST_MARKERS) or low.strip() in ("delete", "delete.")


# ---------------------------------------------------------------------------
# Data deletion (honoured immediately, because refusing is the risk)
# ---------------------------------------------------------------------------

def erase_lead_data(db: Database, settings: Settings, lead_id: int) -> dict[str, Any]:
    """Delete everything we hold about a business except the proof we stopped emailing them.

    The suppression entry and a minimal audit trail survive on purpose: they are what
    demonstrates the opt-out was honoured.
    """
    import shutil

    lead = db.get_lead(lead_id)
    if lead is None:
        return {"deleted": False}
    removed = {"snapshots": 0, "credentials": 0, "findings": 0}
    snap_dir = settings.workdir / "snapshots" / str(lead["domain"])
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)
        removed["snapshots"] = 1
    removed["credentials"] = db.purge_lead_credentials(lead_id)
    scans = db.query("SELECT id FROM scans WHERE lead_id = ?", (lead_id,))
    for s in scans:
        cur = db.execute("DELETE FROM findings WHERE scan_id = ?", (s["id"],))
        removed["findings"] += cur.rowcount or 0
    db.execute("UPDATE scans SET ada_summary=NULL, aiseo_summary=NULL, pages=NULL, exposure=NULL WHERE lead_id = ?", (lead_id,))
    db.execute("UPDATE messages SET body_text='[erased at recipient request]', body_html=NULL WHERE lead_id = ?", (lead_id,))
    db.update("leads", lead_id, business_name=None, needs_human_reason="data erased at recipient request")
    if lead.get("contact_email"):
        db.suppress(lead["contact_email"], "erasure request", lead_id)
    db.set_lead_status(lead_id, LeadStatus.UNSUBSCRIBED, "data erased at recipient request")
    db.add_notice(lead_id, f"Erased all data for {lead['domain']} at the recipient's request", **removed)
    return {"deleted": True, **removed}


# ---------------------------------------------------------------------------
# Refunds
# ---------------------------------------------------------------------------

def request_refund(db: Database, settings: Settings, deal_id: int, reason: str) -> dict[str, Any]:
    """Queue a refund for your approval. **Money never moves without you.**

    This is the one deliberate exception to the autopilot: the engine will decide that a
    refund is warranted and stop there. Nothing is charged back and the customer is not
    told anything until you approve it, because a refund is a business decision about your
    money, not a dead end to be tidied away.
    """
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if deal is None or deal["status"] in (DealStatus.REFUNDED, DealStatus.REFUND_REQUESTED):
        return {"requested": False, "reason": "no open deal, or already queued"}
    lead = db.get_lead(deal["lead_id"])
    db.update("deals", deal_id, status=DealStatus.REFUND_REQUESTED)
    db.set_kv(f"deal:{deal_id}:refund_reason", reason)
    db.set_kv(f"deal:{deal_id}:refund_requested_at", utcnow())
    if lead:
        # Stop the verification clock so it doesn't ask again while you're deciding.
        db.update("leads", lead["id"], next_action_at=None)
    db.log_event("refund_requested", deal["lead_id"], deal_id=deal_id, reason=reason,
                 amount_cents=deal["price_cents"])
    db.add_notice(deal["lead_id"],
                  f"Refund of {money(deal['price_cents'])} for {lead['domain'] if lead else deal_id} "
                  f"is waiting for your approval", reason=reason, deal_id=deal_id, needs_you=True)
    return {"requested": True, "deal_id": deal_id, "amount_cents": deal["price_cents"], "reason": reason}


def pending_refunds(db: Database) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT d.*, l.domain, l.business_name FROM deals d JOIN leads l ON l.id = d.lead_id "
        "WHERE d.status = ? ORDER BY d.id", (DealStatus.REFUND_REQUESTED,))
    for r in rows:
        r["refund_reason"] = db.get_kv(f"deal:{r['id']}:refund_reason") or ""
        r["requested_at"] = db.get_kv(f"deal:{r['id']}:refund_requested_at") or ""
    return rows


def approve_refund(db: Database, settings: Settings, deal_id: int, approved_by: str = "dashboard") -> dict[str, Any]:
    """You said yes: move the money, tell the customer, close the file."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if deal is None or deal["status"] == DealStatus.REFUNDED:
        return {"refunded": False, "reason": "no refundable deal"}
    lead = db.get_lead(deal["lead_id"])
    reason = db.get_kv(f"deal:{deal_id}:refund_reason") or "approved refund"
    refunded_cents = int(deal["price_cents"])
    stripe_id = None
    if deal.get("stripe_payment_intent") and settings.stripe.secret_key:
        try:
            import stripe

            stripe.api_key = settings.stripe.secret_key
            r = stripe.Refund.create(payment_intent=deal["stripe_payment_intent"],
                                     reason="requested_by_customer",
                                     metadata={"deal_id": str(deal_id), "reason": reason[:200]})
            stripe_id = r.get("id")
            refunded_cents = int(r.get("amount") or refunded_cents)
        except Exception as e:  # noqa: BLE001 - a failed refund must be visible, not swallowed
            db.add_notice(deal["lead_id"],
                          f"Refund for {lead['domain'] if lead else deal_id} failed at Stripe - do it by hand",
                          error=str(e)[:300], deal_id=deal_id, needs_you=True)
            db.log_event("error", deal["lead_id"], stage="approve_refund", error=str(e)[:300])
            return {"refunded": False, "error": str(e)[:300]}
    db.update("deals", deal_id, status=DealStatus.REFUNDED)
    db.insert("ledger", {"deal_id": deal_id, "kind": "refund", "amount_cents": -refunded_cents,
                         "currency": deal["currency"], "stripe_id": stripe_id,
                         "memo": f"refund approved by {approved_by}: {reason}", "occurred_at": utcnow()})
    if lead:
        db.set_lead_status(lead["id"], LeadStatus.REFUNDED, reason)
        db.update("leads", lead["id"], next_action_at=None)
        db.purge_lead_credentials(lead["id"])
        db.add_notice(lead["id"], f"Refunded {money(refunded_cents)} to {lead['domain']}",
                      reason=reason, deal_id=deal_id, approved_by=approved_by)
        from .fixing.verify import queue_refund_email

        queue_refund_email(db, settings, deal_id, reason)
    db.log_event("refunded", deal["lead_id"], deal_id=deal_id, amount_cents=refunded_cents,
                 reason=reason, approved_by=approved_by)
    return {"refunded": True, "amount_cents": refunded_cents, "stripe_id": stripe_id}


def decline_refund(db: Database, settings: Settings, deal_id: int, note: str = "") -> dict[str, Any]:
    """You said no: put the deal back and stop asking about it."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if deal is None or deal["status"] != DealStatus.REFUND_REQUESTED:
        return {"declined": False, "reason": "no pending refund"}
    db.update("deals", deal_id, status=DealStatus.DELIVERED)
    db.set_kv(f"deal:{deal_id}:refund_declined", utcnow())
    db.delete_kv(f"deal:{deal_id}:refund_requested_at")
    lead = db.get_lead(deal["lead_id"])
    if lead:
        db.set_lead_status(lead["id"], LeadStatus.DELIVERED, note or "refund declined")
        # Resume the quiet re-checks; never re-ask you about this deal.
        nxt = datetime.now(timezone.utc) + timedelta(days=7)
        db.update("leads", lead["id"], next_action_at=nxt.isoformat(timespec="seconds"))
    db.log_event("refund_declined", deal["lead_id"], deal_id=deal_id, note=note)
    return {"declined": True, "deal_id": deal_id}


# ---------------------------------------------------------------------------
# The one place that decides "handle it" vs "genuinely ask"
# ---------------------------------------------------------------------------

def resolve(db: Database, settings: Settings, lead_id: int | None, situation: str, detail: str,
            action_taken: str) -> None:
    """Record that the autopilot dealt with something a human would otherwise have seen."""
    db.log_event("auto_resolved", lead_id, situation=situation, detail=detail[:400], action=action_taken)
    db.add_notice(lead_id, action_taken, situation=situation, detail=detail[:400])


def escalate(db: Database, settings: Settings, lead_id: int, reason: str) -> None:
    """Genuinely stop and ask. With the autopilot on this should be close to never."""
    if enabled(settings):
        # Even here, prefer closing the file over leaving a lead in limbo.
        db.set_lead_status(lead_id, LeadStatus.ARCHIVED, f"auto-closed (autopilot): {reason}")
        resolve(db, settings, lead_id, "would_have_escalated", reason, "Closed the file rather than asking you")
        return
    db.set_lead_status(lead_id, LeadStatus.NEEDS_HUMAN, reason)
    db.log_event("escalated", lead_id, reason=reason)
