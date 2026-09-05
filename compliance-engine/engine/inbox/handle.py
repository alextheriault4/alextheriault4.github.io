"""Turn inbound email into state changes."""
from __future__ import annotations

import json
from typing import Any

from .. import schemas
from ..config import Settings
from ..db import Database, utcnow
from ..llm import LLM, LLMError, LLMRefusal
from ..models import DealStatus, LeadStatus, MessageStatus, Package
from ..outreach.compliance import lint_email
from ..outreach.compose import allowed_figures, build_context, compose_initial, to_html
from ..deals.checkout import create_checkout, open_or_create_deal, queue_checkout_email
from .negotiate import respond
from .provider import EmailProvider, InboundEmail

CLASSIFY_SYSTEM = """You classify replies to a cold business email about fixing a company's website accessibility and
AI-search readiness. Read the reply and decide the sender's intent. Be literal: "unsubscribe"/"remove me"/"stop" is
unsubscribe even if polite; a clear yes to buying is accept; a price pushback or a named lower number is objection_price;
out-of-office and automatic responses are auto_reply; delivery failure notices are bounce. Quote any questions verbatim.
If they name a price they'd pay, put it in counter_offer_cents. If they redirect to someone else, put that email in forwarded_to."""

TERMINAL = {LeadStatus.UNSUBSCRIBED, LeadStatus.BOUNCED, LeadStatus.NOT_INTERESTED, LeadStatus.ARCHIVED}


def find_lead_for(db: Database, mail: InboundEmail) -> tuple[dict[str, Any] | None, str | None]:
    token = mail.thread_token()
    if token:
        m = db.one("SELECT lead_id, thread_token FROM messages WHERE thread_token=? ORDER BY id LIMIT 1", (token,))
        if m:
            return db.get_lead(m["lead_id"]), m["thread_token"]
    for ref in [mail.in_reply_to or "", *mail.references]:
        m = db.one("SELECT lead_id, thread_token FROM messages WHERE message_id=?", (ref.strip(),))
        if m:
            return db.get_lead(m["lead_id"]), m["thread_token"]
    lead = db.one("SELECT * FROM leads WHERE lower(contact_email)=?", (mail.from_addr.lower(),))
    if lead:
        m = db.one("SELECT thread_token FROM messages WHERE lead_id=? ORDER BY id DESC LIMIT 1", (lead["id"],))
        return lead, (m["thread_token"] if m else None)
    return None, None


def cancel_pending(db: Database, lead_id: int, reason: str) -> None:
    db.execute("UPDATE messages SET status='suppressed', hold_reason=? WHERE lead_id=? AND direction='out' AND status IN ('queued','held','draft')",
               (reason, lead_id))
    db.update("leads", lead_id, next_action_at=None)


def process_inbound(db: Database, settings: Settings, llm: LLM, provider: EmailProvider) -> dict[str, int]:
    stats: dict[str, int] = {"received": 0, "unmatched": 0}
    for mail in provider.fetch_inbound():
        stats["received"] += 1
        intent = handle_one(db, settings, llm, mail)
        if intent is None:
            stats["unmatched"] += 1
        else:
            stats[intent] = stats.get(intent, 0) + 1
    return stats


def handle_one(db: Database, settings: Settings, llm: LLM, mail: InboundEmail) -> str | None:
    lead, token = find_lead_for(db, mail)
    if lead is None or token is None:
        db.log_event("email_received", None, unmatched=True, from_addr=mail.from_addr, subject=mail.subject[:120])
        if mail.text.strip().lower().startswith("unsubscribe") or "unsubscribe" in mail.subject.lower():
            db.suppress(mail.from_addr, "unsubscribe")
        return None
    in_id = db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "in", "kind": "reply", "subject": mail.subject,
        "body_text": mail.text, "to_addr": ", ".join(mail.to_addrs), "from_addr": mail.from_addr,
        "message_id": mail.message_id, "in_reply_to": mail.in_reply_to, "status": MessageStatus.RECEIVED, "created_at": utcnow(),
    })
    db.log_event("email_received", lead["id"], message_id=in_id, from_addr=mail.from_addr)
    db.update("leads", lead["id"], next_action_at=None)  # a reply of any kind stops the follow-up clock

    if mail.is_bounce():
        cls = schemas.ReplyClassification(intent="bounce", confidence=1.0, summary="delivery failure notice")
    else:
        try:
            cls = llm.structured(
                system=CLASSIFY_SYSTEM, schema=schemas.ReplyClassification, effort="low",
                user="Classify this reply.\n\n```json\n" + json.dumps({"subject": mail.subject, "reply_text": mail.text[:4000],
                                                                       "from": mail.from_addr}, indent=1) + "\n```",
            )
        except (LLMRefusal, LLMError) as e:
            cls = schemas.ReplyClassification(intent="unclear", confidence=0.0, summary=f"classifier failed: {e}")
    db.update("messages", in_id, intent=cls.intent)
    db.log_event("reply_classified", lead["id"], message_id=in_id, intent=cls.intent, confidence=cls.confidence, summary=cls.summary)

    intent = cls.intent
    if intent == "unsubscribe":
        db.suppress(mail.from_addr, "unsubscribe", lead["id"])
        if lead.get("contact_email") and lead["contact_email"].lower() != mail.from_addr.lower():
            db.suppress(lead["contact_email"], "unsubscribe", lead["id"])
        cancel_pending(db, lead["id"], "unsubscribed")
        db.set_lead_status(lead["id"], LeadStatus.UNSUBSCRIBED)
        return intent
    if intent == "bounce":
        if lead.get("contact_email"):
            db.suppress(lead["contact_email"], "bounce", lead["id"])
        cancel_pending(db, lead["id"], "bounced")
        db.set_lead_status(lead["id"], LeadStatus.BOUNCED)
        return intent
    if intent in ("not_interested", "already_customer"):
        db.suppress(mail.from_addr, intent, lead["id"])
        cancel_pending(db, lead["id"], intent)
        db.set_lead_status(lead["id"], LeadStatus.NOT_INTERESTED)
        return intent
    if intent == "auto_reply":
        return intent
    if intent == "wrong_person":
        cancel_pending(db, lead["id"], "redirected")
        if cls.forwarded_to and "@" in cls.forwarded_to and not db.is_suppressed(cls.forwarded_to):
            db.update("leads", lead["id"], contact_email=cls.forwarded_to.lower(), contact_source="referral", followups_sent=0)
            db.set_lead_status(lead["id"], LeadStatus.SCANNED)
            compose_initial(db, settings, llm, lead["id"])
        else:
            db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, f"wrong person, no forward address: {cls.summary}")
            db.log_event("escalated", lead["id"], reason=cls.summary)
        return intent
    if lead["status"] in TERMINAL:
        return intent
    if intent in ("objection_other", "unclear") or cls.confidence < 0.5:
        db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, f"{intent}: {cls.summary}")
        db.log_event("escalated", lead["id"], reason=cls.summary, intent=intent)
        return intent

    # interested / question / objection_price / accept → the negotiation agent replies
    scan = db.latest_scan(lead["id"])
    if scan is None:
        db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, "reply received but no scan on file")
        return intent
    reply = respond(db, settings, llm, lead, scan, cls, mail.text)
    if reply.escalate:
        db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, f"negotiation escalated: {reply.escalate_reason}")
        db.log_event("escalated", lead["id"], reason=reply.escalate_reason, intent=intent)
        return intent
    package = Package(reply.package)
    deal = open_or_create_deal(db, lead["id"], package, reply.proposed_price_cents, settings.pricing.currency)
    _queue_reply(db, settings, lead, scan, token, mail, reply.body_text, [reply.proposed_price_cents])
    if reply.ready_to_close and intent == "accept":
        db.update("deals", deal["id"], status=DealStatus.ACCEPTED)
        db.log_event("deal_accepted", lead["id"], deal_id=deal["id"], price_cents=reply.proposed_price_cents)
        create_checkout(db, settings, deal["id"])
        queue_checkout_email(db, settings, deal["id"], token, mail.message_id)
        db.set_lead_status(lead["id"], LeadStatus.ACCEPTED)
    else:
        db.set_lead_status(lead["id"], LeadStatus.ENGAGED)
    return intent


def _queue_reply(db: Database, settings: Settings, lead: dict[str, Any], scan: dict[str, Any], token: str,
                 mail: InboundEmail, body_core: str, extra_cents: list[int]) -> int:
    ctx = build_context(settings, lead, scan)
    greeting = "Hi," if not lead.get("business_name") else f"Hi {lead['business_name']} team,"
    body = "\n\n".join([
        greeting, body_core.strip(),
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\nReply \"unsubscribe\" at any time to stop hearing from us.",
    ])
    allowed = allowed_figures(ctx) + extra_cents + [settings.pricing.ada_cents, settings.pricing.aiseo_cents, settings.pricing.bundle_cents]
    subject = mail.subject if mail.subject.lower().startswith("re:") else f"Re: {mail.subject}"
    lint = lint_email(subject=subject.replace("Re: ", "", 1), body_text=body, allowed_cents=allowed,
                      postal_address=settings.company.postal_address, legal_name=settings.company.legal_name)
    lint.problems = [p for p in lint.problems if "without the word 'estimate'" not in p]
    lint.ok = not lint.problems
    seq = len(db.thread(token)) + 1
    msg_id = db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "reply", "subject": subject,
        "body_text": body, "body_html": to_html(body), "to_addr": mail.from_addr, "from_addr": settings.company.from_email,
        "message_id": f"<{token}.{seq}@{settings.company.reply_domain}>", "in_reply_to": mail.message_id,
        "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT, "lint": lint.as_dict(), "created_at": utcnow(),
    })
    if not lint.ok:
        db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, "reply failed lint: " + "; ".join(lint.problems))
        db.log_event("email_lint_failed", lead["id"], message_id=msg_id, problems=lint.problems)
    return msg_id
