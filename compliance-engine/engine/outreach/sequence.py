"""Send what's queued, when the rules allow, and schedule follow-ups."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Settings
from ..db import Database, utcnow
from ..inbox.provider import EmailProvider, OutboundEmail
from ..models import LeadStatus, MessageStatus
from .compose import compose_followup, unsubscribe_url


def in_send_window(settings: Settings, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(settings.outreach.timezone))
    if local.weekday() >= 5:
        return False
    return settings.outreach.send_window_start_hour <= local.hour < settings.outreach.send_window_end_hour


def breaker_tripped(db: Database, settings: Settings) -> str | None:
    """Stop all sending if bounces or complaints climb. Returns the reason or None."""
    if db.get_kv("breaker", "") == "tripped":
        return db.get_kv("breaker_reason", "breaker tripped")
    recent = db.query(
        "SELECT status FROM messages WHERE direction='out' AND kind IN ('initial','followup') AND status IN ('sent','failed') ORDER BY id DESC LIMIT 200"
    )
    if len(recent) < settings.outreach.min_sample_for_breaker:
        return None
    bounces = db.one("SELECT COUNT(*) AS n FROM leads WHERE status='bounced'")["n"]
    complaints = db.one("SELECT COUNT(*) AS n FROM suppression WHERE reason='complaint'")["n"]
    sent_total = db.one("SELECT COUNT(*) AS n FROM messages WHERE direction='out' AND status='sent'")["n"] or 1
    if bounces / sent_total > settings.outreach.max_bounce_rate:
        reason = f"bounce rate {bounces}/{sent_total} above {settings.outreach.max_bounce_rate}"
    elif complaints / sent_total > settings.outreach.max_complaint_rate:
        reason = f"complaint rate {complaints}/{sent_total} above {settings.outreach.max_complaint_rate}"
    else:
        return None
    db.set_kv("breaker", "tripped")
    db.set_kv("breaker_reason", reason)
    db.log_event("breaker_tripped", None, reason=reason)
    return reason


def _outbound(settings: Settings, msg: dict[str, Any]) -> OutboundEmail:
    return OutboundEmail(
        to=msg["to_addr"], subject=msg["subject"], text=msg["body_text"], html=msg.get("body_html"),
        message_id=msg["message_id"], thread_token=msg["thread_token"], from_addr=settings.company.from_email,
        from_name=settings.company.from_name, reply_domain=settings.company.reply_domain, in_reply_to=msg.get("in_reply_to"),
        unsubscribe_url=unsubscribe_url(settings, msg["thread_token"]) if msg["kind"] in ("initial", "followup") else None,
    )


def deliver_queued(db: Database, settings: Settings, provider: EmailProvider, now: datetime | None = None,
                   ignore_window: bool = False) -> dict[str, int]:
    """Send every queued outbound message the gates allow. Idempotent; safe to call every tick."""
    stats = {"sent": 0, "held": 0, "suppressed": 0, "failed": 0, "skipped": 0}
    now = now or datetime.now(timezone.utc)
    if db.is_paused():
        return stats
    transport_ok, transport_reason = settings.can_send_email()
    reason = breaker_tripped(db, settings)
    queued = db.query("SELECT * FROM messages WHERE direction='out' AND status='queued' ORDER BY id")
    day = now.strftime("%Y-%m-%d")
    sent_today = db.sent_today_count(day)
    for msg in queued:
        lead = db.get_lead(msg["lead_id"])
        if lead is None:
            continue
        if db.is_suppressed(msg["to_addr"]):
            db.update("messages", msg["id"], status=MessageStatus.SUPPRESSED)
            stats["suppressed"] += 1
            continue
        cold = msg["kind"] in ("initial", "followup")
        if cold and reason:
            db.update("messages", msg["id"], hold_reason=reason)
            stats["held"] += 1
            continue
        if cold and not ignore_window and not in_send_window(settings, now):
            stats["skipped"] += 1
            continue
        if cold and sent_today >= settings.outreach.daily_send_cap:
            stats["skipped"] += 1
            continue
        if not transport_ok:
            db.update("messages", msg["id"], status=MessageStatus.HELD, hold_reason=transport_reason)
            db.log_event("email_held", lead["id"], message_id=msg["id"], reason=transport_reason)
            stats["held"] += 1
            continue
        if not (settings.auto_flag_for(msg["kind"]) or msg.get("approved")) and settings.email.provider != "console":
            hold = f"autonomy switch for '{msg['kind']}' is off; approve in dashboard"
            db.update("messages", msg["id"], status=MessageStatus.HELD, hold_reason=hold)
            db.log_event("email_held", lead["id"], message_id=msg["id"], reason=hold)
            stats["held"] += 1
            continue
        try:
            provider_id = provider.send(_outbound(settings, msg))
        except Exception as e:  # noqa: BLE001 - transport errors must never kill the loop
            db.update("messages", msg["id"], status=MessageStatus.FAILED, hold_reason=str(e)[:500])
            db.log_event("error", lead["id"], stage="send", error=str(e)[:500])
            stats["failed"] += 1
            continue
        db.update("messages", msg["id"], status=MessageStatus.SENT, sent_at=utcnow(), provider_id=provider_id)
        db.log_event("email_sent", lead["id"], message_id=msg["id"], kind=msg["kind"], provider=provider.name)
        stats["sent"] += 1
        if cold:
            sent_today += 1
            n_follow = int(lead.get("followups_sent") or 0)
            if msg["kind"] == "followup":
                n_follow += 1
            days = settings.outreach.followup_days
            nxt = (now + timedelta(days=days[n_follow])).isoformat(timespec="seconds") if n_follow < len(days) else None
            db.update("leads", lead["id"], followups_sent=n_follow, next_action_at=nxt)
            if lead["status"] in (LeadStatus.QUEUED, LeadStatus.SCANNED):
                db.set_lead_status(lead["id"], LeadStatus.CONTACTED)
    return stats


def schedule_followups(db: Database, settings: Settings, now: datetime | None = None) -> int:
    """Queue the next follow-up for contacted leads that haven't replied."""
    now_iso = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    due = db.query(
        "SELECT * FROM leads WHERE status='contacted' AND next_action_at IS NOT NULL AND next_action_at <= ? ORDER BY next_action_at",
        (now_iso,),
    )
    n = 0
    for lead in due:
        pending = db.one("SELECT 1 FROM messages WHERE lead_id=? AND direction='out' AND status IN ('queued','held','draft')", (lead["id"],))
        if pending:
            continue
        msg_id = compose_followup(db, settings, lead["id"])
        if msg_id is None:
            db.update("leads", lead["id"], next_action_at=None)
            continue
        n += 1
    return n
