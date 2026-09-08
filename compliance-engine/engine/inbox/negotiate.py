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
from .. import plans
from ..outreach.compose import build_context

SYSTEM_PROMPT = """You are the account manager at a small agency that fixes website accessibility (WCAG 2.1 AA) and
AI-search readiness for small businesses. You are replying inside an existing email thread.

Policy you must follow:
- We sell **ongoing care**: an up-front fix plus a monthly fee to keep the site fixed, because accessibility
  drifts back as soon as new content is added. Lead with a care plan. Offer the one-off "fix_only" plan only
  if they say clearly that they will not take anything recurring.
- Prices: only the plan prices in the context. You may discount down to min_setup_cents and min_monthly_cents
  and no further. Put the up-front amount in proposed_price_cents and the monthly amount in proposed_monthly_cents.
- If they push below the floor, hold there politely and explain what the monthly fee actually buys: a rescan
  every month, regressions fixed the same week, and new pages covered as they are published.
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
    """Lowest setup price allowed for a one-off amount."""
    discounted = int(list_cents * (100 - settings.pricing.max_discount_pct) / 100)
    return max(min(settings.pricing.floor_setup_cents, list_cents), discounted)


def _thread_excerpt(thread: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    out = []
    for m in thread[-limit:]:
        body = m.get("body_text") or ""
        body = body.split("\n—\n", 1)[0]  # drop our own footers
        out.append({"from": "us" if m["direction"] == "out" else "them", "text": body[:1500]})
    return out


def _stand_down(plan: plans.Plan, setup_cents: int, monthly_cents: int, why: str) -> schemas.NegotiationReply:
    """No reply, no movement on price, and the reason recorded. Used when the model will
    not or cannot answer: the autopilot decides what happens next from ``escalate``."""
    return schemas.NegotiationReply(body_text="", package=plan.id, proposed_price_cents=setup_cents,
                                    proposed_monthly_cents=monthly_cents, ready_to_close=False,
                                    escalate=True, escalate_reason=why)


def respond(db: Database, settings: Settings, llm: LLM, lead: dict[str, Any], scan: dict[str, Any],
            classification: schemas.ReplyClassification, reply_text: str) -> schemas.NegotiationReply:
    ctx = build_context(settings, lead, scan)
    deal = db.open_deal(lead["id"])
    plan = plans.get(settings, deal["plan"] or deal["package"]) if deal else \
        plans.recommend(settings, scan["ada_score"], scan["aiseo_score"])
    current_setup = int(deal["price_cents"]) if deal else plan.setup_cents
    current_monthly = int(deal["monthly_cents"] or 0) if deal else plan.monthly_cents
    floor_setup, floor_monthly = plans.floor_for(settings, plan)
    catalogue = plans.catalogue(settings)
    context = {
        "intent": classification.intent, "summary": classification.summary, "questions": classification.questions,
        "counter_offer_cents": classification.counter_offer_cents, "wants_call": classification.wants_call,
        "reply_text": reply_text[:2000], "thread": _thread_excerpt(db.thread_for_lead(lead["id"])),
        "business_name": lead.get("business_name"), "domain": lead["domain"], "platform": lead.get("platform"),
        "plan": plan.id, "package": plan.id, "plan_name": plan.name,
        "current_setup_cents": current_setup, "current_monthly_cents": current_monthly,
        "min_setup_cents": floor_setup, "min_monthly_cents": floor_monthly,
        # Kept so older prompt text and the fake model keep working.
        "current_price_cents": current_setup or current_monthly,
        "min_allowed_cents": floor_setup or floor_monthly, "floor_cents": floor_setup or floor_monthly,
        "plans": {p.id: {"name": p.name, "setup_cents": p.setup_cents, "monthly_cents": p.monthly_cents,
                         "summary": p.price_summary(), "includes": list(p.includes)}
                  for p in catalogue.values()},
        "top_issues": ctx["top_issues"], "service": SERVICE_FACTS,
        "ada_score": scan["ada_score"], "aiseo_score": scan["aiseo_score"],
    }
    user = "Write the next reply in this thread.\n\n```json\n" + json.dumps(context, indent=1) + "\n```"
    try:
        reply = llm.structured(system=SYSTEM_PROMPT, user=user, schema=schemas.NegotiationReply, effort="medium")
    except LLMRefusal as e:
        return _stand_down(plan, current_setup, current_monthly, f"model refused: {e}")
    except LLMError as e:
        return _stand_down(plan, current_setup, current_monthly, f"model error: {e}")
    # Enforce the commercial policy regardless of what the model wrote. The model chooses
    # words and which plan to offer; the code decides what may be charged for it.
    chosen = plans.get(settings, reply.package)
    min_setup, min_monthly = plans.floor_for(settings, chosen)
    if reply.proposed_price_cents < min_setup:
        db.log_event("error", lead["id"], stage="negotiate",
                     error=f"model proposed {reply.proposed_price_cents} below the {chosen.id} floor {min_setup}; clamped")
        reply.proposed_price_cents = min_setup
    if reply.proposed_price_cents > chosen.setup_cents:
        reply.proposed_price_cents = chosen.setup_cents
    monthly = reply.proposed_monthly_cents if reply.proposed_monthly_cents is not None else chosen.monthly_cents
    if chosen.is_recurring:
        monthly = max(min_monthly, min(monthly, chosen.monthly_cents))
    else:
        monthly = 0
    reply.proposed_monthly_cents = monthly
    if classification.intent != "accept":
        reply.ready_to_close = False
    return reply
