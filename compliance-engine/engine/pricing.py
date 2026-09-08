"""Pricing that moves on its own when the market says it is wrong.

A price is a hypothesis, and cold outreach tests it for free: every email that goes out at
a price and does not come back as a sale is evidence. This module turns that evidence into
a decision, so you never have to sit and wonder whether $99 was the right number.

How it works
------------
There is a **ladder** of price points, highest to lowest, configured in
``PricingSettings.ladder_setup_cents`` / ``ladder_monthly_cents``. One rung is *current*.
Every lead we write to has that rung stamped on it (``leads.price_point``), which is what
makes the whole thing safe:

* the price a prospect was quoted never changes underneath them, however the ladder moves;
* an existing subscription is never re-priced - Stripe holds the price it was created with;
* and each rung can be scored honestly afterwards, because we know exactly which emails
  went out at it and which sales came back.

``review`` runs once per tick. It waits for ``review_after_sends`` first emails to actually
be delivered at the current rung, then compares sales per hundred emails against the two
thresholds: below the lower one it steps *down* a rung, at or above the upper one it steps
*up*, and in between it holds. It moves at most one rung, and never more often than
``min_days_between_moves``, so every rung gets a clean read rather than a panic.

At the bottom of the ladder there is nowhere left to go. That is a real finding, not an
error: the engine says so on the dashboard and holds, because the answer at that point is
a different message or a different market, not a lower number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .db import Database, utcnow

CURRENT_KEY = "pricing:current"
HISTORY_KEY = "pricing:history"


@dataclass(frozen=True)
class PricePoint:
    """One rung: what we charge up front and per month, and how we got here."""

    setup_cents: int
    monthly_cents: int
    rung: int                 # index into the ladder, 0 = most expensive
    since: str = ""           # when this rung became current
    reason: str = ""          # why we moved to it

    @property
    def key(self) -> str:
        """Stable identifier stamped on leads. Encodes the actual price, so it stays
        meaningful even if the ladder in the config is later edited."""
        return f"{self.setup_cents}+{self.monthly_cents}"

    @property
    def label(self) -> str:
        def money(c: int) -> str:
            return f"${c / 100:,.0f}" if c % 100 == 0 else f"${c / 100:,.2f}"
        return f"{money(self.setup_cents)} + {money(self.monthly_cents)}/mo"

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["key"] = self.key
        d["label"] = self.label
        return d


def ladder(settings: Settings) -> list[PricePoint]:
    """The configured rungs, most expensive first. Mismatched lists are truncated to the
    shorter one rather than raising: a typo in the environment should not stop the engine."""
    p = settings.pricing
    pairs = list(zip(p.ladder_setup_cents, p.ladder_monthly_cents))
    if not pairs:
        pairs = [(p.care_setup_cents, p.care_monthly_cents)]
    return [PricePoint(setup_cents=s, monthly_cents=m, rung=i) for i, (s, m) in enumerate(pairs)]


def start_rung(settings: Settings) -> int:
    """Where a fresh install starts: the rung matching the configured list price, or the
    closest one to it if the ladder has been edited without updating the list price."""
    rungs = ladder(settings)
    want = settings.pricing.care_setup_cents
    for r in rungs:
        if r.setup_cents == want:
            return r.rung
    return min(rungs, key=lambda r: abs(r.setup_cents - want)).rung


def _load(db: Database) -> dict[str, Any] | None:
    raw = db.get_kv(CURRENT_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _save(db: Database, point: PricePoint) -> None:
    db.set_kv(CURRENT_KEY, json.dumps(point.as_dict()))
    try:
        hist = json.loads(db.get_kv(HISTORY_KEY) or "[]")
    except json.JSONDecodeError:
        hist = []
    hist.append(point.as_dict())
    db.set_kv(HISTORY_KEY, json.dumps(hist[-40:]))


def current(db: Database, settings: Settings) -> PricePoint:
    """The rung in force right now, initialising it on first use."""
    rungs = ladder(settings)
    stored = _load(db)
    if stored:
        rung = int(stored.get("rung", 0))
        rung = max(0, min(rung, len(rungs) - 1))
        return PricePoint(setup_cents=int(stored["setup_cents"]), monthly_cents=int(stored["monthly_cents"]),
                          rung=rung, since=stored.get("since", ""), reason=stored.get("reason", ""))
    start = rungs[start_rung(settings)]
    point = PricePoint(setup_cents=start.setup_cents, monthly_cents=start.monthly_cents, rung=start.rung,
                       since=utcnow(), reason="the configured list price")
    _save(db, point)
    return point


def with_point(settings: Settings, point: PricePoint) -> Settings:
    """A copy of the settings priced at this rung.

    The negotiation floor follows the rung down, so a discount is always measured against
    what this prospect was actually quoted rather than against a list price they never saw.
    """
    priced = settings.pricing.model_copy(update={
        "care_setup_cents": point.setup_cents,
        "fix_only_cents": point.setup_cents,
        "care_monthly_cents": point.monthly_cents,
        "floor_setup_cents": min(settings.pricing.floor_setup_cents, point.setup_cents),
        "floor_monthly_cents": min(settings.pricing.floor_monthly_cents, point.monthly_cents),
    })
    return settings.model_copy(update={"pricing": priced})


def point_from_key(key: str, settings: Settings) -> PricePoint | None:
    """Rebuild a point from a stamp on a lead, even if that rung has left the ladder."""
    try:
        setup, monthly = (int(x) for x in (key or "").split("+", 1))
    except (ValueError, AttributeError):
        return None
    for r in ladder(settings):
        if r.setup_cents == setup and r.monthly_cents == monthly:
            return r
    return PricePoint(setup_cents=setup, monthly_cents=monthly, rung=-1, reason="a rung no longer on the ladder")


def settings_for_lead(db: Database, settings: Settings, lead_id: int) -> Settings:
    """Settings priced the way this lead has been quoted.

    Called before anything that mentions money to a specific prospect. The first call
    stamps the current rung on the lead; every later call reuses it, which is what
    guarantees a price we put in writing never moves.
    """
    if not settings.pricing.adaptive:
        return settings
    row = db.one("SELECT price_point FROM leads WHERE id = ?", (lead_id,)) or {}
    stamped = row.get("price_point")
    point = point_from_key(stamped, settings) if stamped else None
    if point is None:
        point = current(db, settings)
        db.update("leads", lead_id, price_point=point.key)
    return with_point(settings, point)


def performance(db: Database, key: str) -> dict[str, Any]:
    """How one rung actually did: emails delivered, replies, and sales."""
    sent = db.one(
        "SELECT COUNT(DISTINCT l.id) AS n FROM leads l JOIN messages m ON m.lead_id = l.id "
        "WHERE l.price_point = ? AND m.direction = 'out' AND m.kind IN ('initial','followup') "
        "AND m.status = 'sent'", (key,))["n"]
    replied = db.one(
        "SELECT COUNT(DISTINCT l.id) AS n FROM leads l JOIN messages m ON m.lead_id = l.id "
        "WHERE l.price_point = ? AND m.direction = 'in'", (key,))["n"]
    paid = db.one(
        "SELECT COUNT(DISTINCT d.id) AS n FROM deals d JOIN leads l ON l.id = d.lead_id "
        "WHERE l.price_point = ? AND d.paid_at IS NOT NULL", (key,))["n"]
    revenue = db.one(
        "SELECT COALESCE(SUM(d.price_cents), 0) AS c FROM deals d JOIN leads l ON l.id = d.lead_id "
        "WHERE l.price_point = ? AND d.paid_at IS NOT NULL", (key,))["c"]
    return {
        "key": key, "sent": sent, "replied": replied, "paid": paid, "revenue_cents": revenue,
        "conversion_pct": round(100.0 * paid / sent, 2) if sent else 0.0,
        "reply_pct": round(100.0 * replied / sent, 2) if sent else 0.0,
        # Revenue per email sent is the number that actually decides whether a move helped:
        # a cheaper price that sells three times as often is the better price.
        "revenue_per_send_cents": round(revenue / sent) if sent else 0,
    }


def _days_since(iso: str, now: datetime) -> float:
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return 10_000.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).total_seconds() / 86_400.0


def review(db: Database, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    """Decide whether today's price should change. Returns what was decided and why."""
    now = now or datetime.now(timezone.utc)
    p = settings.pricing
    if not p.adaptive:
        return {"moved": False, "reason": "adaptive pricing is switched off"}

    point = current(db, settings)
    stats = performance(db, point.key)
    rungs = ladder(settings)
    out: dict[str, Any] = {"moved": False, "point": point.as_dict(), "stats": stats}

    if stats["sent"] < p.review_after_sends:
        out["reason"] = (f"{point.label} has had {stats['sent']} of the {p.review_after_sends} emails "
                         f"it needs before the result means anything")
        return out

    waited = _days_since(point.since, now)
    if waited < p.min_days_between_moves:
        out["reason"] = (f"{point.label} has only been running {waited:.0f} days; "
                         f"prices move at most every {p.min_days_between_moves}")
        return out

    conv = stats["conversion_pct"]
    if conv < p.step_down_below_conversion_pct:
        lower = [r for r in rungs if r.rung > point.rung]
        if not lower:
            out["reason"] = (f"{point.label} sold {stats['paid']} times in {stats['sent']} emails and there is no "
                             f"lower price left on the ladder - the problem is the message or the market, not the price")
            db.log_event("pricing_floor", None, **out["stats"], label=point.label)
            return out
        return _move(db, lower[0], stats, now,
                     f"{point.label} sold {stats['paid']} times in {stats['sent']} emails "
                     f"({conv:.2f}%, below {p.step_down_below_conversion_pct}%)", out)

    if conv >= p.step_up_at_conversion_pct and point.rung > 0:
        return _move(db, rungs[point.rung - 1], stats, now,
                     f"{point.label} sold {stats['paid']} times in {stats['sent']} emails "
                     f"({conv:.2f}%, at or above {p.step_up_at_conversion_pct}%), so there is room to charge more", out)

    out["reason"] = f"{point.label} is converting at {conv:.2f}%, which is where it should be"
    return out


def _move(db: Database, target: PricePoint, stats: dict[str, Any], now: datetime,
          because: str, out: dict[str, Any]) -> dict[str, Any]:
    moved = PricePoint(setup_cents=target.setup_cents, monthly_cents=target.monthly_cents, rung=target.rung,
                       since=now.isoformat(timespec="seconds"), reason=because)
    _save(db, moved)
    db.log_event("pricing_changed", None, to=moved.label, rung=moved.rung, reason=because, evidence=stats)
    out.update({"moved": True, "point": moved.as_dict(), "reason": because,
                "new_label": moved.label, "was": out["point"]["label"]})
    return out


def set_rung(db: Database, settings: Settings, rung: int, reason: str = "set by hand") -> PricePoint:
    """Move to a rung deliberately. Used by the CLI; the automatic review uses ``review``."""
    rungs = ladder(settings)
    if not 0 <= rung < len(rungs):
        raise ValueError(f"no rung {rung}; the ladder has {len(rungs)} (0 is the most expensive)")
    target = rungs[rung]
    point = PricePoint(setup_cents=target.setup_cents, monthly_cents=target.monthly_cents,
                       rung=target.rung, since=utcnow(), reason=reason)
    _save(db, point)
    db.log_event("pricing_changed", None, to=point.label, rung=point.rung, reason=reason)
    return point


def history(db: Database) -> list[dict[str, Any]]:
    try:
        return list(reversed(json.loads(db.get_kv(HISTORY_KEY) or "[]")))
    except json.JSONDecodeError:
        return []


def explain(db: Database, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    """Everything the dashboard and the CLI show: where the price is, how it is doing,
    what would move it, and how every rung tried so far has performed."""
    now = now or datetime.now(timezone.utc)
    point = current(db, settings)
    p = settings.pricing
    rows = []
    for r in ladder(settings):
        stats = performance(db, r.key)
        rows.append({**stats, "label": r.label, "rung": r.rung, "current": r.rung == point.rung,
                     "setup_cents": r.setup_cents, "monthly_cents": r.monthly_cents})
    stats = performance(db, point.key)
    needed = max(0, p.review_after_sends - stats["sent"])
    if not p.adaptive:
        next_move = "adaptive pricing is switched off; the price only changes when you change it"
    elif needed:
        next_move = f"{needed} more emails at this price before it is judged"
    else:
        days_left = max(0.0, p.min_days_between_moves - _days_since(point.since, now))
        if days_left >= 1:
            next_move = f"enough evidence; the next move can happen in {days_left:.0f} days"
        else:
            next_move = f"under review every tick: below {p.step_down_below_conversion_pct}% it steps down, " \
                        f"at {p.step_up_at_conversion_pct}% or better it steps up"
    return {"current": point.as_dict(), "stats": stats, "ladder": rows, "next_move": next_move,
            "adaptive": p.adaptive, "history": history(db),
            "since_days": round(_days_since(point.since, now)) if point.since else 0}
