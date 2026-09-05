"""After payment: build, apply or deliver, then rescan until the numbers move."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from playwright.sync_api import Browser

from ..config import Settings
from ..db import Database, utcnow
from ..llm import LLM
from ..models import DealStatus, FixStrategy, LeadStatus, MessageStatus
from ..outreach.compose import to_html
from ..scanning.runner import persist_scan, scan_site
from .apply import apply_bundle
from .build import build_bundle

VERIFY_EVERY_DAYS = 3
VERIFY_FOR_DAYS = 45


def bundle_url(settings: Settings, token: str) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/bundle/{token}"


def start_fix(db: Database, settings: Settings, llm: LLM, deal_id: int) -> int:
    """Build the bundle for a paid deal, apply it where possible, queue the delivery email."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    baseline = db.latest_scan(lead["id"])
    fix_id = db.insert("fixes", {"deal_id": deal_id, "status": "planned", "created_at": utcnow(),
                                 "before_ada": baseline["ada_score"] if baseline else None,
                                 "before_aiseo": baseline["aiseo_score"] if baseline else None})
    db.update("deals", deal_id, status=DealStatus.IN_PROGRESS)
    try:
        bundle = build_bundle(db, settings, llm, deal_id)
    except Exception as e:  # noqa: BLE001
        db.update("fixes", fix_id, status="failed", error=str(e)[:500])
        db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, f"fix build failed: {e}")
        db.log_event("error", lead["id"], stage="build_bundle", error=str(e)[:500])
        return fix_id
    db.update("fixes", fix_id, status="built", strategy=bundle.strategy, bundle_path=str(bundle.root), summary=bundle.summary())
    db.log_event("fix_planned", lead["id"], fix_id=fix_id, **bundle.summary())

    applied: dict[str, Any] = {"applied": False}
    can_apply, why = settings.can_apply_fixes()
    if bundle.strategy in (FixStrategy.WORDPRESS_REST, FixStrategy.GITHUB_PR):
        if can_apply:
            try:
                applied = apply_bundle(db, settings, deal_id, bundle)
            except Exception as e:  # noqa: BLE001
                applied = {"applied": False, "error": str(e)[:500]}
                db.log_event("error", lead["id"], stage="apply", error=str(e)[:500])
        else:
            applied = {"applied": False, "reason": why}
    status = "applied" if applied.get("applied") else "delivered"
    db.update("fixes", fix_id, status=status, applied_at=utcnow() if applied.get("applied") else None,
              summary={**bundle.summary(), "apply": applied})
    queue_delivery_email(db, settings, deal_id, bundle.summary(), applied)
    db.update("deals", deal_id, status=DealStatus.DELIVERED, delivered_at=utcnow())
    db.set_lead_status(lead["id"], LeadStatus.DELIVERED)
    nxt = datetime.now(timezone.utc) + timedelta(days=VERIFY_EVERY_DAYS)
    db.update("leads", lead["id"], next_action_at=nxt.isoformat(timespec="seconds"))
    db.log_event("fix_delivered", lead["id"], fix_id=fix_id, applied=applied.get("applied", False))
    return fix_id


def queue_delivery_email(db: Database, settings: Settings, deal_id: int, summary: dict[str, Any], applied: dict[str, Any]) -> int:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    thread = db.thread_for_lead(lead["id"])
    token = thread[0]["thread_token"]
    last_in = next((m for m in reversed(thread) if m["direction"] == "in"), None)
    n = summary.get("total_changes", 0)
    if applied.get("applied"):
        how = ("We've applied the changes directly" + (f"; the pull request is here: {applied['pr_url']}" if applied.get("pr_url") else
               " through your WordPress site. One small plugin file still needs uploading; instructions are in the bundle."))
    else:
        how = "The changes are packaged with step-by-step instructions for your platform here: " + bundle_url(settings, token) + \
              ". If you'd rather we apply them, reply with access details and we'll do it."
    body = "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"The remediation for {lead['domain']} is ready: {n} changes across {len(summary.get('pages', []))} pages plus "
        f"{', '.join(summary.get('site_files', [])) or 'site files'}. Every change is listed against the report finding it resolves.",
        how,
        "Once the changes are live we rescan automatically and send you the before/after report. If anything looks off, reply here; "
        "follow-up fixes are included for 30 days.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\nReply \"unsubscribe\" at any time to stop hearing from us.",
    ])
    seq = len(thread) + 1
    return db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "delivery",
        "subject": f"Your website changes for {lead['domain']} are ready", "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{token}.{seq}@{settings.company.reply_domain}>", "in_reply_to": last_in["message_id"] if last_in else None,
        "status": MessageStatus.QUEUED, "lint": {"ok": True, "problems": []}, "created_at": utcnow(),
    })


def verify_deal(db: Database, settings: Settings, browser: Browser, deal_id: int, url: str | None = None) -> dict[str, Any]:
    """Rescan the live site and compare with the baseline. Returns the comparison."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    fix = db.one("SELECT * FROM fixes WHERE deal_id=? ORDER BY id DESC LIMIT 1", (deal_id,))
    result = scan_site(url or lead["url"], settings, browser)
    scan_id = persist_scan(db, settings, lead, result, kind="verification")
    if result.error:
        return {"verified": False, "error": result.error}
    before_ada, before_seo = fix["before_ada"] or 0, fix["before_aiseo"] or 0
    ada_goal = deal["package"] in ("ada", "bundle")
    seo_goal = deal["package"] in ("aiseo", "bundle")
    # "Resolved" = a real jump, a decent absolute score, and nothing critical left in the area we were paid for.
    critical_left = {f.kind for f in result.findings if f.impact == "critical"}
    improved = ((not ada_goal or (result.ada_score >= max(before_ada + 15, 70) and "ada" not in critical_left)) and
                (not seo_goal or (result.aiseo_score >= max(before_seo + 15, 70) and "aiseo" not in critical_left)))
    db.update("fixes", fix["id"], after_ada=result.ada_score, after_aiseo=result.aiseo_score)
    cmp = {"verified": improved, "scan_id": scan_id, "before": {"ada": before_ada, "aiseo": before_seo},
           "after": {"ada": result.ada_score, "aiseo": result.aiseo_score}}
    if improved:
        db.update("fixes", fix["id"], status="verified", verified_at=utcnow())
        db.update("deals", deal_id, status=DealStatus.VERIFIED)
        db.set_lead_status(lead["id"], LeadStatus.VERIFIED)
        db.update("leads", lead["id"], next_action_at=None)
        db.log_event("fix_verified", lead["id"], **cmp)
        queue_report_email(db, settings, deal_id, cmp)
    else:
        started = datetime.fromisoformat(fix["created_at"])
        if datetime.now(timezone.utc) - started > timedelta(days=VERIFY_FOR_DAYS):
            db.set_lead_status(lead["id"], LeadStatus.NEEDS_HUMAN, "delivered fix never verified on the live site after 45 days")
            db.update("leads", lead["id"], next_action_at=None)
        else:
            nxt = datetime.now(timezone.utc) + timedelta(days=VERIFY_EVERY_DAYS)
            db.update("leads", lead["id"], next_action_at=nxt.isoformat(timespec="seconds"))
    return cmp


def queue_report_email(db: Database, settings: Settings, deal_id: int, cmp: dict[str, Any]) -> int:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    thread = db.thread_for_lead(lead["id"])
    token = thread[0]["thread_token"]
    body = "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"The verification rescan of {lead['domain']} is done. Accessibility score: {cmp['before']['ada']} → {cmp['after']['ada']}. "
        f"AI-search readiness: {cmp['before']['aiseo']} → {cmp['after']['aiseo']}. The full before/after report: "
        f"{settings.stripe.public_base_url.rstrip('/')}/r/{token}",
        "Anything that still needs attention is listed there; follow-up fixes are included for the next 30 days, just reply.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\nReply \"unsubscribe\" at any time to stop hearing from us.",
    ])
    seq = len(thread) + 1
    return db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "delivery",
        "subject": f"Before/after report for {lead['domain']}", "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{token}.{seq}@{settings.company.reply_domain}>", "status": MessageStatus.QUEUED,
        "lint": {"ok": True, "problems": []}, "created_at": utcnow(),
    })
