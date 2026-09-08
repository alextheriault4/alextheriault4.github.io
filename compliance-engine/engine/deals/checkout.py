"""Deals and money in.

Stripe Checkout with Stripe Tax, in two shapes:

* **subscription** for the care plans - a one-off setup line for the remediation plus a
  recurring monthly line, on one checkout page and one card entry;
* **payment** for the one-off remediation.

Without a live key the engine creates a placeholder link and the dashboard can simulate
payment, so the whole pipeline still runs end to end.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import onboarding
from .. import plans as plan_lib
from ..config import Settings
from ..db import Database, utcnow
from ..exposure import money
from ..models import DealStatus, LeadStatus, MessageStatus
from ..outreach.compliance import lint_email
from ..outreach.compose import to_html

CARE_CYCLE_DAYS = 30


def open_or_create_deal(db: Database, lead_id: int, plan: plan_lib.Plan, setup_cents: int,
                        monthly_cents: int, currency: str) -> dict[str, Any]:
    deal = db.open_deal(lead_id)
    if deal:
        db.update("deals", deal["id"], package=plan.id, plan=plan.id,
                  price_cents=setup_cents, monthly_cents=monthly_cents)
        return db.one("SELECT * FROM deals WHERE id=?", (deal["id"],))
    deal_id = db.insert("deals", {
        "lead_id": lead_id, "package": plan.id, "plan": plan.id, "price_cents": setup_cents,
        "monthly_cents": monthly_cents, "currency": currency, "status": DealStatus.PROPOSED,
        "created_at": utcnow(),
    })
    db.log_event("deal_proposed", lead_id, deal_id=deal_id, plan=plan.id,
                 setup_cents=setup_cents, monthly_cents=monthly_cents)
    return db.one("SELECT * FROM deals WHERE id=?", (deal_id,))


def agreement_url(settings: Settings, deal_id: int) -> str:
    return f"{settings.stripe.public_base_url.rstrip('/')}/agreement/{deal_id}"


def create_checkout(db: Database, settings: Settings, deal_id: int) -> str:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    plan = plan_lib.get(settings, deal.get("plan") or deal["package"])
    monthly = int(deal.get("monthly_cents") or 0)
    setup = int(deal["price_cents"])
    ok, reason = settings.can_charge()

    if ok:
        import stripe

        stripe.api_key = settings.stripe.secret_key
        line_items: list[dict[str, Any]] = []
        if setup:
            line_items.append({"quantity": 1, "price_data": {
                "currency": deal["currency"], "unit_amount": setup, "tax_behavior": "exclusive",
                "product_data": {"name": f"{plan.name} - initial remediation",
                                 "description": f"One-off fix of the issues reported for {lead['domain']}."},
            }})
        if monthly:
            line_items.append({"quantity": 1, "price_data": {
                "currency": deal["currency"], "unit_amount": monthly, "tax_behavior": "exclusive",
                "recurring": {"interval": "month"},
                "product_data": {"name": f"{plan.name} - monthly care",
                                 "description": f"Monthly rescan, regression fixes and report for {lead['domain']}."},
            }})
        session = stripe.checkout.Session.create(
            mode="subscription" if monthly else "payment",
            customer_email=lead["contact_email"],
            line_items=line_items,
            automatic_tax={"enabled": True},
            success_url=f"{settings.stripe.public_base_url.rstrip('/')}/paid/{deal_id}",
            cancel_url=agreement_url(settings, deal_id),
            metadata={"deal_id": str(deal_id), "lead_id": str(lead["id"]), "domain": lead["domain"],
                      "plan": plan.id},
            **({"subscription_data": {"metadata": {"deal_id": str(deal_id), "domain": lead["domain"]}}}
               if monthly else {"invoice_creation": {"enabled": True}}),
        )
        url, session_id = session.url, session.id
    else:
        url, session_id = f"{settings.stripe.public_base_url.rstrip('/')}/pay/{deal_id}", f"placeholder_{deal_id}"
        db.log_event("checkout_sent", lead["id"], deal_id=deal_id, note=f"placeholder link ({reason})")
    db.update("deals", deal_id, status=DealStatus.CHECKOUT_SENT, checkout_url=url, stripe_session_id=session_id)
    return url


def queue_checkout_email(db: Database, settings: Settings, deal_id: int, thread_token: str,
                         in_reply_to: str | None) -> int:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    plan = plan_lib.get(settings, deal.get("plan") or deal["package"])
    setup, monthly = int(deal["price_cents"]), int(deal.get("monthly_cents") or 0)
    if monthly and setup:
        price_line = (f"{money(setup)} to fix everything in the report, then {money(monthly)} a month to keep it "
                      f"that way. Both are on the one checkout page; the monthly part starts today and you can "
                      f"cancel it any time in one click from the receipt.")
    elif monthly:
        price_line = f"{money(monthly)} a month, cancellable any time in one click from the receipt."
    else:
        price_line = f"{money(setup)}, one payment, nothing recurring."
    body = "\n\n".join([
        f"Hi {lead.get('business_name') or 'there'},",
        f"Here is the secure payment link for {lead['domain']} ({plan.name}): {deal['checkout_url']}",
        f"{price_line} Sales tax is added at checkout where it applies.",
        f"The service agreement is here: {agreement_url(settings, deal_id)}. Paying through the link accepts it. "
        "Work starts the same day payment lands, you'll have the before/after report within 10 business days, "
        "and if the verification rescan doesn't show the reported issues resolved you get a full refund.",
        "If you'd rather pay another way, or want anything changed first, just reply here.",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\n"
        f'Reply "unsubscribe" at any time to stop hearing from us.',
    ])
    lint = lint_email(subject=f"Payment link for {lead['domain']}", body_text=body,
                      allowed_cents=[setup, monthly], postal_address=settings.company.postal_address,
                      legal_name=settings.company.legal_name)
    # This is a transactional message the recipient asked for, inside an existing thread.
    lint.problems = [p for p in lint.problems
                     if "subject contains 'payment'" not in p and "without the word 'estimate'" not in p]
    lint.ok = not lint.problems
    seq = len(db.thread(thread_token)) + 1
    msg_id = db.insert("messages", {
        "lead_id": lead["id"], "thread_token": thread_token, "direction": "out", "kind": "checkout",
        "subject": f"Payment link for {lead['domain']}", "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{thread_token}.{seq}@{settings.company.reply_domain}>", "in_reply_to": in_reply_to,
        "status": MessageStatus.QUEUED if lint.ok else MessageStatus.DRAFT,
        "lint": lint.as_dict(), "created_at": utcnow(),
    })
    db.log_event("checkout_sent", lead["id"], deal_id=deal_id, message_id=msg_id, plan=plan.id)
    return msg_id


def mark_paid(db: Database, settings: Settings, deal_id: int, *, stripe_session_id: str | None = None,
              payment_intent: str | None = None, amount_total_cents: int | None = None,
              tax_cents: int = 0, subscription_id: str | None = None) -> None:
    """First payment received: start the work, and start the care clock if it's a retainer."""
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    if deal is None or deal["status"] in (DealStatus.PAID, DealStatus.IN_PROGRESS,
                                          DealStatus.DELIVERED, DealStatus.VERIFIED):
        return
    now = utcnow()
    monthly = int(deal.get("monthly_cents") or 0)
    amount = amount_total_cents if amount_total_cents is not None else int(deal["price_cents"]) + tax_cents
    fields: dict[str, Any] = {
        "status": DealStatus.PAID, "paid_at": now, "stripe_payment_intent": payment_intent,
        "stripe_session_id": stripe_session_id or deal["stripe_session_id"], "tax_cents": tax_cents,
    }
    if monthly:
        fields["stripe_subscription_id"] = subscription_id or deal.get("stripe_subscription_id")
        fields["care_started_at"] = now
        fields["next_care_at"] = (datetime.now(timezone.utc) + timedelta(days=CARE_CYCLE_DAYS)).isoformat(timespec="seconds")
    db.update("deals", deal_id, **fields)
    db.insert("ledger", {"deal_id": deal_id, "kind": "charge", "amount_cents": amount - tax_cents,
                         "currency": deal["currency"], "stripe_id": payment_intent,
                         "memo": f"{deal.get('plan') or deal['package']} initial payment", "occurred_at": now})
    if tax_cents:
        db.insert("ledger", {"deal_id": deal_id, "kind": "sales_tax", "amount_cents": tax_cents,
                             "currency": deal["currency"], "stripe_id": payment_intent,
                             "memo": "collected by Stripe Tax", "occurred_at": now})
    fee = int(round(amount * 0.029 + 30))
    db.insert("ledger", {"deal_id": deal_id, "kind": "processing_fee", "amount_cents": -fee,
                         "currency": deal["currency"], "stripe_id": payment_intent,
                         "memo": "estimated Stripe fee (reconcile with payout report)", "occurred_at": now})
    db.set_lead_status(deal["lead_id"], LeadStatus.PAID)
    db.log_event("paid", deal["lead_id"], deal_id=deal_id, amount_cents=amount, tax_cents=tax_cents,
                 recurring=bool(monthly))
    # Tell them straight away how we get in - the easiest way their platform allows.
    onboarding.queue_welcome(db, settings, deal_id)


def record_recurring_payment(db: Database, settings: Settings, subscription_id: str, *,
                             amount_cents: int, tax_cents: int, invoice_id: str | None) -> dict[str, Any]:
    """A monthly care invoice was paid."""
    deal = db.one("SELECT * FROM deals WHERE stripe_subscription_id = ?", (subscription_id,))
    if deal is None:
        return {"handled": False, "reason": "no deal for that subscription"}
    if db.one("SELECT 1 FROM ledger WHERE stripe_id = ? AND kind = 'charge'", (invoice_id,)):
        return {"handled": True, "duplicate": True}  # Stripe retries webhooks
    now = utcnow()
    db.insert("ledger", {"deal_id": deal["id"], "kind": "charge", "amount_cents": amount_cents - tax_cents,
                         "currency": deal["currency"], "stripe_id": invoice_id,
                         "memo": "monthly care", "occurred_at": now})
    if tax_cents:
        db.insert("ledger", {"deal_id": deal["id"], "kind": "sales_tax", "amount_cents": tax_cents,
                             "currency": deal["currency"], "stripe_id": invoice_id,
                             "memo": "collected by Stripe Tax", "occurred_at": now})
    fee = int(round(amount_cents * 0.029 + 30))
    db.insert("ledger", {"deal_id": deal["id"], "kind": "processing_fee", "amount_cents": -fee,
                         "currency": deal["currency"], "stripe_id": invoice_id,
                         "memo": "estimated Stripe fee", "occurred_at": now})
    db.log_event("care_payment", deal["lead_id"], deal_id=deal["id"], amount_cents=amount_cents)
    return {"handled": True, "deal_id": deal["id"]}


def cancel_care(db: Database, settings: Settings, subscription_id: str) -> dict[str, Any]:
    """The client cancelled the retainer. Stop the care cycle; keep the record."""
    deal = db.one("SELECT * FROM deals WHERE stripe_subscription_id = ?", (subscription_id,))
    if deal is None:
        return {"handled": False}
    db.update("deals", deal["id"], care_cancelled_at=utcnow(), next_care_at=None)
    db.add_notice(deal["lead_id"], f"Monthly care cancelled for deal {deal['id']}",
                  subscription_id=subscription_id, cycles=deal.get("care_cycles"))
    db.log_event("care_cancelled", deal["lead_id"], deal_id=deal["id"])
    return {"handled": True, "deal_id": deal["id"]}


def handle_stripe_webhook(db: Database, settings: Settings, payload: bytes, sig_header: str) -> dict[str, Any]:
    import stripe

    event = stripe.Webhook.construct_event(payload, sig_header, settings.stripe.webhook_secret)
    kind = event["type"]
    obj = event["data"]["object"]

    if kind == "checkout.session.completed":
        deal_id = int((obj.get("metadata") or {}).get("deal_id", 0))
        if deal_id:
            tax = int((obj.get("total_details") or {}).get("amount_tax") or 0)
            mark_paid(db, settings, deal_id, stripe_session_id=obj.get("id"),
                      payment_intent=obj.get("payment_intent"),
                      amount_total_cents=int(obj.get("amount_total") or 0), tax_cents=tax,
                      subscription_id=obj.get("subscription"))
            return {"handled": True, "deal_id": deal_id}

    if kind == "invoice.paid":
        sub = obj.get("subscription")
        # The first invoice is already recorded by checkout.session.completed.
        if sub and (obj.get("billing_reason") or "") != "subscription_create":
            return record_recurring_payment(
                db, settings, sub, amount_cents=int(obj.get("amount_paid") or 0),
                tax_cents=int(obj.get("tax") or 0), invoice_id=obj.get("id"))

    if kind == "customer.subscription.deleted":
        return cancel_care(db, settings, obj.get("id"))

    if kind == "charge.refunded":
        pi = obj.get("payment_intent")
        deal = db.one("SELECT * FROM deals WHERE stripe_payment_intent=?", (pi,))
        if deal:
            db.update("deals", deal["id"], status=DealStatus.REFUNDED, next_care_at=None)
            db.insert("ledger", {"deal_id": deal["id"], "kind": "refund",
                                 "amount_cents": -int(obj.get("amount_refunded") or 0),
                                 "currency": deal["currency"], "stripe_id": pi, "memo": "refund",
                                 "occurred_at": utcnow()})
            return {"handled": True, "deal_id": deal["id"], "refunded": True}

    return {"handled": False, "type": kind}
