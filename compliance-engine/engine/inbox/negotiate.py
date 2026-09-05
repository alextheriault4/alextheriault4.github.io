"""Reply to an engaged lead within a fixed commercial policy.

The model writes the words; the code owns the numbers. It can never quote a price
below ``min_allowed`` and it never decides on its own that a deal is closed; only an
explicit acceptance from the prospect does that.
"""
from __future__ import annotations

import json
from typing import Any

from .. import schemas
from ..config import Settings
from ..db import Database
from ..llm import LLM, LLMError, LLMRefusal
from ..models import Package
from ..outreach.compose import build_context, price_for, recommend_package

SYSTEM_PROMPT = """You are the account manager at a small agency that fixes website accessibility (WCAG 2.1 AA) and
AI-search readiness for small businesses. You are replying inside an existing email thread.

Policy you must follow:
- Prices: you may only quote the package prices given in the context, or a discount down to min_allowed_cents. Never below it.
- If they push for less than min_allowed_cents, hold at min_allowed_cents politely and explain what is included.
- Never guarantee legal compliance or immunity from lawsuits. Say we fix the specific issues in the report and re-scan to verify.
- Never use: guarantee, certified, urgent, penalty, fine, legal notice.
- What's included: every issue in the linked report fixed, a verification rescan with a before/after report, 30 days of follow-up fixes.
  Turnaround: 10 business days after payment. Payment: one flat fee via a secure Stripe checkout link, sales tax added where applicable.
  Refund policy: if the verification rescan doesn't show the reported issues resolved, full refund.
  Access needed: for WordPress, a temporary editor login or application password; for site builders (Wix, Squarespace, GoDaddy),
  either a collaborator invite or we deliver the changes with step-by-step instructions; for custom sites, a code repository or FTP access.
- Answer their actual questions directly and briefly. Under 150 words. No bullet lists, no exclamation marks.
- Set ready_to_close=true ONLY if they have clearly said yes to buying at a stated price.
- Set escalate=true if they threaten legal action, are abusive, ask for something outside the packages, or ask a question
  you cannot answer from the context. Then leave body_text empty.
- Do not add a greeting line or a sign-off; the system adds them."""

SERVICE_FACTS = {
    "included": "every issue in the report fixed, verification rescan with before/after report, 30 days of follow-up fixes",
    "turnaround": "10 business days after payment",
    "payment": "flat fee via secure Stripe checkout link; sales tax added where applicable",
    "refund": "full refund if the verification rescan does not show the reported issues resolved",
}


def min_allowed_cents(settings: Settings, list_cents: int) -> int:
    discounted = int(list_cents * (100 - settings.pricing.max_discount_pct) / 100)
    return max(settings.pricing.floor_cents, discounted)


def _thread_excerpt(thread: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    out = []
    for m in thread[-limit:]:
        body = m.get("body_text") or ""
        body = body.split("\n—\n", 1)[0]  # drop our own footers
        out.append({"from": "us" if m["direction"] == "out" else "them", "text": body[:1500]})
    return out


def respond(db: Database, settings: Settings, llm: LLM, lead: dict[str, Any], scan: dict[str, Any],
            classification: schemas.ReplyClassification, reply_text: str) -> schemas.NegotiationReply:
    ctx = build_context(settings, lead, scan)
    deal = db.open_deal(lead["id"])
    package = Package(deal["package"]) if deal else recommend_package(scan["ada_score"], scan["aiseo_score"])
    list_price = price_for(settings, package)
    current = int(deal["price_cents"]) if deal else list_price
    floor = min_allowed_cents(settings, list_price)
    context = {
        "intent": classification.intent, "summary": classification.summary, "questions": classification.questions,
        "counter_offer_cents": classification.counter_offer_cents, "wants_call": classification.wants_call,
        "reply_text": reply_text[:2000], "thread": _thread_excerpt(db.thread_for_lead(lead["id"])),
        "business_name": lead.get("business_name"), "domain": lead["domain"], "platform": lead.get("platform"),
        "package": package.value, "list_price_cents": list_price, "current_price_cents": current,
        "min_allowed_cents": floor, "floor_cents": floor,
        "package_prices_cents": {"ada": settings.pricing.ada_cents, "aiseo": settings.pricing.aiseo_cents, "bundle": settings.pricing.bundle_cents},
        "top_issues": ctx["top_issues"], "service": SERVICE_FACTS,
    }
    user = "Write the next reply in this thread.\n\n```json\n" + json.dumps(context, indent=1) + "\n```"
    try:
        reply = llm.structured(system=SYSTEM_PROMPT, user=user, schema=schemas.NegotiationReply, effort="medium")
    except LLMRefusal as e:
        return schemas.NegotiationReply(body_text="", package=package.value, proposed_price_cents=current,
                                        ready_to_close=False, escalate=True, escalate_reason=f"model refused: {e}")
    except LLMError as e:
        return schemas.NegotiationReply(body_text="", package=package.value, proposed_price_cents=current,
                                        ready_to_close=False, escalate=True, escalate_reason=f"model error: {e}")
    # Enforce the commercial policy regardless of what the model wrote.
    pkg_list = price_for(settings, Package(reply.package))
    pkg_floor = min_allowed_cents(settings, pkg_list)
    if reply.proposed_price_cents < pkg_floor:
        db.log_event("error", lead["id"], stage="negotiate", error=f"model proposed {reply.proposed_price_cents} below floor {pkg_floor}; clamped")
        reply.proposed_price_cents = pkg_floor
    if reply.proposed_price_cents > pkg_list:
        reply.proposed_price_cents = pkg_list
    if classification.intent != "accept":
        reply.ready_to_close = False
    return reply
