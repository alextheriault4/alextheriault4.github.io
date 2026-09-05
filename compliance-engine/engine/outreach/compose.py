"""Draft the first email and the follow-ups."""
from __future__ import annotations

import json
from typing import Any

from .. import schemas
from ..config import Settings
from ..db import Database, utcnow
from ..exposure import money
from ..llm import LLM, LLMError, LLMRefusal
from ..models import LeadStatus, MessageStatus, Package
from .compliance import footer, lint_email, new_thread_token

SYSTEM_PROMPT = """You write short, honest first-contact emails from a small web-accessibility and AI-search agency to
small-business owners. You are given the scan of their actual website and a small set of dollar figures.

Hard rules:
- Use ONLY dollar figures that appear in the context JSON, written exactly as given. Never invent numbers.
- When you mention a dollar figure, make clear it is an estimate and say what it is based on.
- Never guarantee compliance, never say "certified", never say or imply they will be sued or fined, never manufacture urgency.
- Never use the words: guarantee, certified, urgent, penalty, fine, final notice, legal notice, act now.
- Plain language, second person, specific to what the scan found. No hype, no exclamation marks, no bullet lists.
- The whole email body (your five paragraphs together) must be under 180 words. The subject must be under 60 characters and must not start with "Re:".
- Do not write a greeting or a sign-off; the system adds those.
Return the structured fields only."""


def recommend_package(ada_score: int, aiseo_score: int) -> Package:
    if ada_score < 70 and aiseo_score < 70:
        return Package.BUNDLE
    if ada_score < 70:
        return Package.ADA
    return Package.AISEO


def price_for(settings: Settings, package: Package) -> int:
    return {Package.ADA: settings.pricing.ada_cents, Package.AISEO: settings.pricing.aiseo_cents,
            Package.BUNDLE: settings.pricing.bundle_cents}[package]


def build_context(settings: Settings, lead: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
    exp = scan["exposure"]
    ada = scan["ada_summary"]
    seo = scan["aiseo_summary"]
    package = recommend_package(scan["ada_score"], scan["aiseo_score"])
    price = price_for(settings, package)
    top = (ada.get("top", []) + seo.get("top", []))
    top.sort(key=lambda i: {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}.get(i["impact"], 9))
    return {
        "domain": lead["domain"], "business_name": lead.get("business_name"), "category": lead.get("category"),
        "city": lead.get("city"), "region": lead.get("region"), "platform": lead.get("platform"),
        "ada_score": scan["ada_score"], "aiseo_score": scan["aiseo_score"],
        "top_issues": top[:4],
        "exposure": {
            "ada_low_cents": exp["ada_low_cents"], "ada_typical_cents": exp["ada_typical_cents"],
            "ada_low": money(exp["ada_low_cents"]), "ada_typical": money(exp["ada_typical_cents"]),
            "lawsuits_per_year": exp["lawsuits_per_year"], "unruh_applies": exp["unruh_applies"],
            "aiseo_annual_low": money(exp["aiseo_annual_low_cents"]), "aiseo_annual_high": money(exp["aiseo_annual_high_cents"]),
            "aiseo_annual_low_cents": exp["aiseo_annual_low_cents"], "aiseo_annual_high_cents": exp["aiseo_annual_high_cents"],
        },
        "recommended_package": package.value, "price": money(price), "price_cents": price,
        "turnaround": "10 business days", "company": settings.company.name,
    }


def allowed_figures(ctx: dict[str, Any]) -> list[int]:
    e = ctx["exposure"]
    return [e["ada_low_cents"], e["ada_typical_cents"], e["aiseo_annual_low_cents"], e["aiseo_annual_high_cents"], ctx["price_cents"]]


def report_url(settings: Settings, token: str) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/r/{token}"


def unsubscribe_url(settings: Settings, token: str) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/u/{token}"


def assemble_body(settings: Settings, lead: dict[str, Any], scan: dict[str, Any], paragraphs: list[str], token: str,
                  has_estimates: bool) -> str:
    greeting = f"Hi {lead['business_name']} team," if lead.get("business_name") else "Hello,"
    sign = f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}"
    ftr = footer(
        legal_name=settings.company.legal_name, postal_address=settings.company.postal_address,
        website=settings.company.website, domain=lead["domain"], category=lead.get("category"), city=lead.get("city"),
        unsubscribe_url=unsubscribe_url(settings, token), report_url=report_url(settings, token),
        sources=scan["exposure"].get("sources"), has_estimates=has_estimates,
    )
    return "\n\n".join([greeting, *[p.strip() for p in paragraphs if p and p.strip()], sign, ftr])


def to_html(text: str) -> str:
    import html
    paras = [f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n")]
    return "<div style=\"font-family:system-ui,sans-serif;font-size:15px;line-height:1.5;color:#111\">" + "".join(paras) + "</div>"


def compose_initial(db: Database, settings: Settings, llm: LLM, lead_id: int) -> int | None:
    """Draft the first email for a scanned lead. Returns the message id, or None if it can't be pitched."""
    lead = db.get_lead(lead_id)
    scan = db.latest_scan(lead_id)
    if not lead or not scan or not lead.get("contact_email"):
        return None
    if db.is_suppressed(lead["contact_email"]):
        db.set_lead_status(lead_id, LeadStatus.UNSUBSCRIBED, "address suppressed")
        return None
    ctx = build_context(settings, lead, scan)
    token = new_thread_token()
    user = "Write the first email for this business.\n\n```json\n" + json.dumps(ctx, indent=1) + "\n```"
    try:
        draft = llm.structured(system=SYSTEM_PROMPT, user=user, schema=schemas.OutreachDraft, effort="medium")
    except LLMRefusal as e:
        db.set_lead_status(lead_id, LeadStatus.NEEDS_HUMAN, f"model refused to draft: {e}")
        db.log_event("escalated", lead_id, reason=str(e))
        return None
    except LLMError as e:
        db.log_event("error", lead_id, stage="compose_initial", error=str(e))
        return None
    paragraphs = [draft.opening, draft.findings_paragraph, draft.exposure_paragraph, draft.offer_paragraph, draft.call_to_action]
    body = assemble_body(settings, lead, scan, paragraphs, token, has_estimates=True)
    lint = lint_email(subject=draft.subject, body_text=body, allowed_cents=allowed_figures(ctx),
                      postal_address=settings.company.postal_address, legal_name=settings.company.legal_name)
    msg_id = db.insert("messages", {
        "lead_id": lead_id, "thread_token": token, "direction": "out", "kind": "initial",
        "subject": draft.subject.strip(), "body_text": body, "body_html": to_html(body), "to_addr": lead["contact_email"],
        "from_addr": settings.company.from_email, "message_id": f"<{token}.1@{settings.company.reply_domain}>",
        "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT, "lint": lint.as_dict(), "created_at": utcnow(),
    })
    if lint.ok:
        db.set_lead_status(lead_id, LeadStatus.QUEUED)
        db.log_event("email_drafted", lead_id, message_id=msg_id, package=ctx["recommended_package"])
    else:
        db.set_lead_status(lead_id, LeadStatus.NEEDS_HUMAN, "draft failed lint: " + "; ".join(lint.problems))
        db.log_event("email_lint_failed", lead_id, message_id=msg_id, problems=lint.problems)
    return msg_id


FOLLOWUPS = [
    "Following up on my note from a few days ago about {domain}. The short version: {issue}. "
    "Happy to send the full report or walk you through what we'd change. Just reply here.",
    "Last note from me on this. If fixing the accessibility and AI-search gaps on {domain} isn't a priority right now, "
    "no problem at all, I'll close the file. If it is, reply and we'll take care of it for a flat {price} (estimate of "
    "the work is in the report linked below).",
]


def compose_followup(db: Database, settings: Settings, lead_id: int) -> int | None:
    lead = db.get_lead(lead_id)
    scan = db.latest_scan(lead_id)
    if not lead or not scan:
        return None
    thread = [m for m in db.thread_for_lead(lead_id) if m["direction"] == "out"]
    if not thread:
        return None
    n = int(lead.get("followups_sent") or 0)
    if n >= len(FOLLOWUPS) or n >= len(settings.outreach.followup_days):
        return None
    first = thread[0]
    ctx = build_context(settings, lead, scan)
    issue = ctx["top_issues"][0]["plain"] if ctx["top_issues"] else "a handful of accessibility and search gaps"
    text = FOLLOWUPS[n].format(domain=lead["domain"], issue=issue, price=ctx["price"])
    body = assemble_body(settings, lead, scan, [text], first["thread_token"], has_estimates=("$" in text))
    subject = first["subject"]
    lint = lint_email(subject=subject, body_text=body, allowed_cents=allowed_figures(ctx),
                      postal_address=settings.company.postal_address, legal_name=settings.company.legal_name)
    seq = len(thread) + 1
    return db.insert("messages", {
        "lead_id": lead_id, "thread_token": first["thread_token"], "direction": "out", "kind": "followup",
        "subject": subject, "body_text": body, "body_html": to_html(body), "to_addr": lead["contact_email"],
        "from_addr": settings.company.from_email, "message_id": f"<{first['thread_token']}.{seq}@{settings.company.reply_domain}>",
        "in_reply_to": first["message_id"], "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT,
        "lint": lint.as_dict(), "created_at": utcnow(),
    })
