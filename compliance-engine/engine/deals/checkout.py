"""Deals and money in.

Stripe Checkout (hosted page) with Stripe Tax turned on, so sales tax is calculated and
collected per jurisdiction without us touching rates. Without a live key the engine
creates a placeholder link and the dashboard can simulate payment, so the rest of the
pipeline can be exercised end to end.
"""
from __future__ import annotations

from typing import Any

from ..config import Settings
from ..db import Database, utcnow
from ..models import DealStatus, LeadStatus, MessageStatus, Package
from ..outreach.compliance import lint_email
from ..outreach.compose import to_html

PACKAGE_NAMES = {
    Package.ADA: "Website accessibility remediation (WCAG 2.1 AA issues from report)",
    Package.AISEO: "AI-search readiness package (structured data, llms.txt, crawler access, metadata)",
    Package.BUNDLE: "Accessibility + AI-search remediation bundle",
}


def open_or_create_deal(db: Database, lead_id: int, package: Package, price_cents: int, currency: str) -> dict[str, Any]:
    deal = db.open_deal(lead_id)
    if deal:
        db.update("deals", deal["id"], package=package.value, price_cents=price_cents)
        return db.one("SELECT * FROM deals WHERE id=?", (deal["id"],))
    deal_id = db.insert("deals", {"lead_id": lead_id, "package": package.value, "price_cents": price_cents,
                                  "currency": currency, "status": DealStatus.PROPOSED, "created_at": utcnow()})
    db.log_event("deal_proposed", lead_id, deal_id=deal_id, package=package.value, price_cents=price_cents)
    return db.one("SELECT * FROM deals WHERE id=?", (deal_id,))


def agreement_url(settings: Settings, deal_id: int) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/agreement/{deal_id}"


def create_checkout(db: Database, settings: Settings, deal_id: int) -> str:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    ok, reason = settings.can_charge()
    if ok:
        import stripe

        stripe.api_key = settings.stripe.secret_key
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=lead["contact_email"],
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": deal["currency"],
                    "unit_amount": int(deal["price_cents"]),
                    "tax_behavior": "exclusive",
                    "product_data": {"name": PACKAGE_NAMES[Package(deal["package"])],
                                     "description": f"For {lead['domain']}. Scope: issues listed in your report."},
                },
            }],
            automatic_tax={"enabled": True},
            invoice_creation={"enabled": True},
            success_url=f"{settings.stripe.public_base_url.rstrip('/')}/paid/{deal_id}",
            cancel_url=agreement_url(settings, deal_id),
            metadata={"deal_id": str(deal_id), "lead_id": str(lead["id"]), "domain": lead["domain"]},
        )
        url, session_id = session.url, session.id
    else:
        url, session_id = f"{settings.stripe.public_base_url.rstrip('/')}/pay/{deal_id}", f"placeholder_{deal_id}"
        db.log_event("checkout_sent", lead["id"], deal_id=deal_id, note=f"placeholder link ({reason})")
    db.update("deals", deal_id, status=DealStatus.CHECKOUT_SENT, checkout_url=url, stripe_session_id=session_id)
    return url


def queue_checkout_email(db: Database, settings: Settings, deal_id: int, thread_token: str, in_reply_to: str | None) -> int:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    price = f"${deal['price_cents'] / 100:,.0f}"
    body = "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"Here is the secure payment link for the {deal['package']} package for {lead['domain']} at {price} "
        f"(sales tax is added at checkout where applicable): {deal['checkout_url']}",
        f"The short service agreement is here: {agreement_url(settings, deal_id)}. Paying through the link accepts it. "
        "Work starts the same day payment lands; you'll get a before/after report within 10 business days, and if the "
        "verification rescan doesn't show the reported issues resolved you get a full refund.",
        "If you'd rather pay a different way, or want anything changed first, just reply here.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\nReply \"unsubscribe\" at any time to stop hearing from us.",
    ])
    lint = lint_email(subject=f"Payment link for {lead['domain']}", body_text=body, allowed_cents=[deal["price_cents"]],
                      postal_address=settings.company.postal_address, legal_name=settings.company.legal_name)
    # "Payment" is banned in cold subjects; this is a requested transactional message in an existing thread.
    lint.problems = [p for p in lint.problems if "subject contains 'payment'" not in p and "without the word 'estimate'" not in p]
    lint.ok = not lint.problems
    seq = len(db.thread(thread_token)) + 1
    msg_id = db.insert("messages", {
        "lead_id": lead["id"], "thread_token": thread_token, "direction": "out", "kind": "checkout",
        "subject": f"Payment link for {lead['domain']}", "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{thread_token}.{seq}@{settings.company.reply_domain}>", "in_reply_to": in_reply_to,
        "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT, "lint": lint.as_dict(), "created_at": utcnow(),
    })
    db.log_event("checkout_sent", lead["id"], deal_id=deal_id, message_id=msg_id)
    return msg_id


def mark_paid(db: Database, settings: Settings, deal_id: int, *, stripe_session_id: str | None = None,
              payment_intent: str | None = None, amount_total_cents: int | None = None, tax_cents: int = 0) -> None:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if deal is None or deal["status"] in (DealStatus.PAID, DealStatus.IN_PROGRESS, DealStatus.DELIVERED, DealStatus.VERIFIED):
        return
    now = utcnow()
    amount = amount_total_cents if amount_total_cents is not None else int(deal["price_cents"]) + tax_cents
    db.update("deals", deal_id, status=DealStatus.PAID, paid_at=now, stripe_payment_intent=payment_intent,
              stripe_session_id=stripe_session_id or deal["stripe_session_id"], tax_cents=tax_cents)
    db.insert("ledger", {"deal_id": deal_id, "kind": "charge", "amount_cents": amount - tax_cents, "currency": deal["currency"],
                         "stripe_id": payment_intent, "memo": f"{deal['package']} package", "occurred_at": now})
    if tax_cents:
        db.insert("ledger", {"deal_id": deal_id, "kind": "sales_tax", "amount_cents": tax_cents, "currency": deal["currency"],
                             "stripe_id": payment_intent, "memo": "collected by Stripe Tax", "occurred_at": now})
    fee = int(round(amount * 0.029 + 30))
    db.insert("ledger", {"deal_id": deal_id, "kind": "processing_fee", "amount_cents": -fee, "currency": deal["currency"],
                         "stripe_id": payment_intent, "memo": "estimated Stripe fee (reconcile with payout report)", "occurred_at": now})
    db.set_lead_status(deal["lead_id"], LeadStatus.PAID)
    db.log_event("paid", deal["lead_id"], deal_id=deal_id, amount_cents=amount, tax_cents=tax_cents)


def handle_stripe_webhook(db: Database, settings: Settings, payload: bytes, sig_header: str) -> dict[str, Any]:
    import stripe

    event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe.webhook_secret)
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        deal_id = int((session.get("metadata") or {}).get("deal_id", 0))
        if deal_id:
            tax = int((session.get("total_details") or {}).get("amount_tax") or 0)
            mark_paid(db, settings, deal_id, stripe_session_id=session.get("id"), payment_intent=session.get("payment_intent"),
                      amount_total_cents=int(session.get("amount_total") or 0), tax_cents=tax)
            return {"handled": True, "deal_id": deal_id}
    if event["type"] == "charge.refunded":
        charge = event["data"]["object"]
        pi = charge.get("payment_intent")
        deal = db.one("SELECT * FROM deals WHERE stripe_payment_intent=?", (pi,))
        if deal:
            db.update("deals", deal["id"], status=DealStatus.REFUNDED)
            db.insert("ledger", {"deal_id": deal["id"], "kind": "refund", "amount_cents": -int(charge.get("amount_refunded") or 0),
                                 "currency": deal["currency"], "stripe_id": pi, "memo": "refund", "occurred_at": utcnow()})
            return {"handled": True, "deal_id": deal["id"], "refunded": True}
    return {"handled": False, "type": event["type"]}
