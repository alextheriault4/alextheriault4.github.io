"""Draft the first email and the follow-ups."""
from __future__ import annotations

import json
from typing import Any

from .. import autopilot, plans, schemas
from ..config import Settings
from ..db import Database, utcnow
from ..exposure import money
from ..legal import check_lead
from ..llm import LLM, LLMCapacityError, LLMError, LLMRefusal
from ..models import LeadStatus, MessageStatus, Package
from .compliance import footer, lint_email, new_thread_token

SYSTEM_PROMPT = """You write short, honest first-contact emails from a small web-accessibility and AI-search agency to
small-business owners. You are given the scan of their actual website and a small set of dollar figures.

What we sell: an up-front fix, then a monthly fee to keep it fixed. Accessibility drifts back the moment
new content is added, so lead with the plan in the context and describe the monthly part as what stops the
problem coming back - a rescan every month, regressions corrected, new pages covered.

Hard rules:
- Use ONLY dollar figures that appear in the context JSON, written exactly as given. Never invent numbers.
- You may quote the two percentage scores from the context. Describe them as an automated check of the
  points that apply to their site. Never say or imply that a score means they are or are not legally compliant.
- When you mention a dollar figure, make clear it is an estimate and say what it is based on.
- Never guarantee compliance, never say "certified", never say or imply they will be sued or fined, never manufacture urgency.
- Never use the words: guarantee, certified, urgent, penalty, fine, final notice, legal notice, act now.
- Plain language, second person, specific to what the scan found. No hype, no exclamation marks, no bullet lists.
- The whole email body (your five paragraphs together) must be under 180 words. The subject must be under 60 characters and must not start with "Re:".
- Do not write a greeting or a sign-off; the system adds those.
Return the structured fields only."""


def build_context(settings: Settings, lead: dict[str, Any], scan: dict[str, Any]) -> dict[str, Any]:
    exp = scan["exposure"]
    ada = scan["ada_summary"] or {}
    seo = scan["aiseo_summary"] or {}
    plan = plans.recommend(settings, scan["ada_score"], scan["aiseo_score"])
    others = plans.alternatives(settings, plan)

    def top_from(summary: dict[str, Any], area: str) -> list[dict[str, Any]]:
        rows = []
        for f in summary.get("failures", []):
            # A short, concrete phrase for the email: what was actually found, falling back
            # to the check's name. The full explanation belongs in the report, not the pitch.
            detail = (f.get("detail") or "").strip().rstrip(".")
            plain = f.get("failure_phrase") or f["title"].lower()
            rows.append({"kind": area, "rule_id": f["id"], "title": f["title"], "plain": plain,
                         "detail": detail, "weight": f.get("weight", 0), "count": f.get("count", 0),
                         "why": f.get("why", ""),
                         "impact": "critical" if f.get("weight", 0) >= 9 else
                                   "serious" if f.get("weight", 0) >= 6 else "moderate"})
        return rows

    top = top_from(ada, "ada") + top_from(seo, "seo")
    top.sort(key=lambda i: -i["weight"])
    return {
        "domain": lead["domain"], "business_name": lead.get("business_name"), "category": lead.get("category"),
        "city": lead.get("city"), "region": lead.get("region"), "platform": lead.get("platform"),
        "ada_score": scan["ada_score"], "aiseo_score": scan["aiseo_score"],
        "ada_band": ada.get("band", ""), "seo_band": seo.get("band", ""),
        "ada_passed": ada.get("passed"), "ada_applicable": ada.get("checks_applicable"),
        "seo_passed": seo.get("passed"), "seo_applicable": seo.get("checks_applicable"),
        "fixable_count": (ada.get("fixable_count") or 0) + (seo.get("fixable_count") or 0),
        "top_issues": top[:4],
        "exposure": {
            "ada_low_cents": exp["ada_low_cents"], "ada_typical_cents": exp["ada_typical_cents"],
            "ada_low": money(exp["ada_low_cents"]), "ada_typical": money(exp["ada_typical_cents"]),
            "lawsuits_per_year": exp["lawsuits_per_year"], "unruh_applies": exp["unruh_applies"],
            "aiseo_annual_low": money(exp["aiseo_annual_low_cents"]), "aiseo_annual_high": money(exp["aiseo_annual_high_cents"]),
            "aiseo_annual_low_cents": exp["aiseo_annual_low_cents"], "aiseo_annual_high_cents": exp["aiseo_annual_high_cents"],
        },
        "plan": {"id": plan.id, "name": plan.name, "summary": plan.price_summary(), "blurb": plan.blurb,
                 "setup_cents": plan.setup_cents, "monthly_cents": plan.monthly_cents,
                 "setup": money(plan.setup_cents), "monthly": money(plan.monthly_cents),
                 "includes": list(plan.includes), "recurring": plan.is_recurring},
        "alternatives": [{"id": p.id, "name": p.name, "summary": p.price_summary(),
                          "setup_cents": p.setup_cents, "monthly_cents": p.monthly_cents} for p in others],
        # Kept for older prompts and stored contexts.
        "recommended_package": plan.id, "price": plan.price_summary(),
        "price_cents": plan.setup_cents or plan.monthly_cents,
        "turnaround": "10 business days", "company": settings.company.name,
    }


def allowed_figures(ctx: dict[str, Any]) -> list[int]:
    """Every dollar amount the email is permitted to contain."""
    e = ctx["exposure"]
    figures = [e["ada_low_cents"], e["ada_typical_cents"], e["aiseo_annual_low_cents"], e["aiseo_annual_high_cents"]]
    figures += [ctx["plan"]["setup_cents"], ctx["plan"]["monthly_cents"]]
    for alt in ctx.get("alternatives", []):
        figures += [alt["setup_cents"], alt["monthly_cents"]]
    return [f for f in figures if f]


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


DEFAULT_SUBJECT = "A few fixable issues on {domain}"


def compose_initial(db: Database, settings: Settings, llm: LLM, lead_id: int) -> int | None:
    """Draft the first email for a scanned lead.

    A draft that fails the compliance lint is not a problem for a human: the lint's own
    complaints go back to the model, and if that still doesn't produce a clean email we
    send a fixed template built only from pre-approved sentences and figures. The only
    outcomes are "queued" and "deferred because there was no model capacity".
    """
    lead = db.get_lead(lead_id)
    scan = db.latest_scan(lead_id)
    if not lead or not scan or not lead.get("contact_email"):
        return None
    if db.is_suppressed(lead["contact_email"]):
        db.set_lead_status(lead_id, LeadStatus.UNSUBSCRIBED, "address suppressed")
        return None
    eligible = check_lead(lead, settings, (scan.get("aiseo_summary") or {}).get("facts", {}).get("text_sample", ""))
    if not eligible.ok:
        db.set_lead_status(lead_id, LeadStatus.EXCLUDED, eligible.reason)
        db.log_event("excluded", lead_id, reason=eligible.reason)
        return None

    ctx = build_context(settings, lead, scan)
    token = new_thread_token()
    base_user = "Write the first email for this business.\n\n```json\n" + json.dumps(ctx, indent=1) + "\n```"
    allowed = allowed_figures(ctx)

    def build(subject: str, paragraphs: list[str]) -> tuple[str, str, Any]:
        body = assemble_body(settings, lead, scan, paragraphs, token, has_estimates=True)
        return subject, body, lint_email(subject=subject, body_text=body, allowed_cents=allowed,
                                         postal_address=settings.company.postal_address,
                                         legal_name=settings.company.legal_name)

    subject = body = None
    lint = None
    attempts = settings.autopilot.lint_repair_attempts if autopilot.enabled(settings) else 0
    user = base_user
    for attempt in range(attempts + 1):
        try:
            draft = llm.structured(system=SYSTEM_PROMPT, user=user, schema=schemas.OutreachDraft, effort="medium")
        except LLMCapacityError as e:
            autopilot.defer(db, settings, lead_id, "compose_initial", e)
            return None
        except (LLMRefusal, LLMError) as e:
            db.log_event("error", lead_id, stage="compose_initial", error=str(e)[:300], attempt=attempt)
            break  # fall through to the template
        subject, body, lint = build(draft.subject.strip(), [
            draft.opening, draft.findings_paragraph, draft.exposure_paragraph,
            draft.offer_paragraph, draft.call_to_action,
        ])
        if lint.ok:
            break
        db.log_event("email_lint_failed", lead_id, problems=lint.problems, attempt=attempt)
        if attempt < attempts:
            user = base_user + "\n\n" + autopilot.repair_prompt(lint.problems)

    if lint is None or not lint.ok:
        # The fixed template: dull sentences, pre-approved figures, passes by construction.
        subject, body, lint = build(DEFAULT_SUBJECT.format(domain=lead["domain"]),
                                    autopilot.safe_outreach_paragraphs(ctx))
        if lint.ok and autopilot.enabled(settings):
            autopilot.resolve(db, settings, lead_id, "draft_failed_lint",
                              "; ".join((lint.problems or ["model draft rejected"])[:3]),
                              f"Sent the standard template to {lead['domain']} instead of the generated draft")

    msg_id = db.insert("messages", {
        "lead_id": lead_id, "thread_token": token, "direction": "out", "kind": "initial",
        "subject": subject, "body_text": body, "body_html": to_html(body), "to_addr": lead["contact_email"],
        "from_addr": settings.company.from_email, "message_id": f"<{token}.1@{settings.company.reply_domain}>",
        "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT, "lint": lint.as_dict(), "created_at": utcnow(),
    })
    if lint.ok:
        db.set_lead_status(lead_id, LeadStatus.QUEUED)
        db.log_event("email_drafted", lead_id, message_id=msg_id, package=ctx["recommended_package"])
    else:
        # Only reachable if the fixed template itself fails, which means a misconfiguration
        # (missing postal address, say) rather than anything about this lead.
        autopilot.escalate(db, settings, lead_id, "even the standard template fails the lint: "
                           + "; ".join(lint.problems))
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
