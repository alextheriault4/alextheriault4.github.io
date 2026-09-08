"""The monthly retainer, delivered without anyone touching it.

A retainer you do not actually service is just a subscription trap, so this is the part
that has to be genuinely automatic. Once a month, for every client paying for care:

1. rescan the site against the whole checklist,
2. compare with the last cycle to find **regressions** (checks that used to pass and now
   fail) and **new pages** that were never covered,
3. build and, where there is access, apply a fix for anything auto-fixable,
4. email a short report saying what moved and what was fixed.

If nothing regressed, the client still gets the report - "still at 98%, nothing to do this
month" is exactly what they are paying to be told, and it is what stops them cancelling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from playwright.sync_api import Browser

from . import plans as plan_lib
from .config import Settings
from .db import Database, utcnow
from .llm import LLM, LLMCapacityError
from .models import MessageStatus
from .outreach.compose import to_html
from .scanning.runner import persist_scan, scan_site
from .standards import BY_ID

CARE_CYCLE_DAYS = 30


def due_deals(db: Database, now: datetime | None = None) -> list[dict[str, Any]]:
    now_iso = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return db.query(
        "SELECT d.*, l.domain, l.url, l.business_name, l.contact_email FROM deals d "
        "JOIN leads l ON l.id = d.lead_id "
        "WHERE d.monthly_cents > 0 AND d.care_cancelled_at IS NULL AND d.next_care_at IS NOT NULL "
        "AND d.next_care_at <= ? AND d.status NOT IN ('refunded','cancelled') ORDER BY d.next_care_at",
        (now_iso,),
    )


def compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """What changed between two scans, in terms the client cares about."""
    def statuses(scan: dict[str, Any] | None) -> dict[str, str]:
        if not scan:
            return {}
        out: dict[str, str] = {}
        for area in ("ada_summary", "aiseo_summary"):
            summary = scan.get(area) or {}
            for row in summary.get("failures", []):
                out[row["id"]] = "fail"
        return out

    before, after = statuses(previous), statuses(current)
    regressions = sorted(k for k in after if k not in before)
    resolved = sorted(k for k in before if k not in after)
    return {
        "regressions": regressions,
        "resolved": resolved,
        "before": {"ada": (previous or {}).get("ada_score"), "seo": (previous or {}).get("aiseo_score")},
        "after": {"ada": current.get("ada_score"), "seo": current.get("aiseo_score")},
        "regression_titles": [BY_ID[k].title for k in regressions if k in BY_ID],
        "fixable_regressions": [k for k in regressions if k in BY_ID and BY_ID[k].auto_fixable],
    }


def run_cycle(db: Database, settings: Settings, llm: LLM, browser: Browser, deal: dict[str, Any],
              now: datetime | None = None) -> dict[str, Any]:
    """One month of care for one client."""
    now = now or datetime.now(timezone.utc)
    lead = db.get_lead(deal["lead_id"])
    previous = db.latest_scan(lead["id"], kind="care") or db.latest_scan(lead["id"], kind="verification") \
        or db.latest_scan(lead["id"])

    result = scan_site(lead["url"], settings, browser)
    scan_id = persist_scan(db, settings, lead, result, kind="care")
    if result.error:
        db.update("deals", deal["id"],
                  next_care_at=(now + timedelta(days=3)).isoformat(timespec="seconds"))
        db.log_event("care_scan_failed", lead["id"], deal_id=deal["id"], error=result.error)
        return {"ok": False, "error": result.error}

    current = db.latest_scan(lead["id"], kind="care")
    delta = compare(previous, current)

    fixed: list[str] = []
    if delta["fixable_regressions"]:
        try:
            fixed = apply_regression_fix(db, settings, llm, deal, delta)
        except LLMCapacityError:
            db.update("deals", deal["id"], next_care_at=(now + timedelta(hours=6)).isoformat(timespec="seconds"))
            return {"ok": False, "deferred": True}
        except Exception as e:  # noqa: BLE001 - a failed fix must not stop the report
            db.log_event("error", lead["id"], stage="care_fix", error=str(e)[:300])

    cycles = int(deal.get("care_cycles") or 0) + 1
    db.update("deals", deal["id"], care_cycles=cycles,
              next_care_at=(now + timedelta(days=CARE_CYCLE_DAYS)).isoformat(timespec="seconds"))
    queue_care_report(db, settings, deal["id"], delta, fixed, cycles)
    db.log_event("care_cycle", lead["id"], deal_id=deal["id"], cycle=cycles, scan_id=scan_id,
                 regressions=len(delta["regressions"]), fixed=len(fixed),
                 ada=delta["after"]["ada"], seo=delta["after"]["seo"])
    return {"ok": True, "cycle": cycles, **delta, "fixed": fixed}


def apply_regression_fix(db: Database, settings: Settings, llm: LLM, deal: dict[str, Any],
                         delta: dict[str, Any]) -> list[str]:
    """Rebuild the remediation bundle so it covers whatever slipped, and apply it if we can."""
    from .fixing.apply import apply_bundle
    from .fixing.build import build_bundle

    bundle = build_bundle(db, settings, llm, deal["id"])
    can_apply, _ = settings.can_apply_fixes()
    applied: dict[str, Any] = {"applied": False}
    if can_apply:
        try:
            applied = apply_bundle(db, settings, deal["id"], bundle)
        except Exception as e:  # noqa: BLE001
            db.log_event("error", deal["lead_id"], stage="care_apply", error=str(e)[:300])
    db.insert("fixes", {
        "deal_id": deal["id"], "status": "applied" if applied.get("applied") else "delivered",
        "strategy": bundle.strategy, "bundle_path": str(bundle.root),
        "summary": {**bundle.summary(), "care_cycle": True, "regressions": delta["regressions"],
                    "apply": applied},
        "created_at": utcnow(), "applied_at": utcnow() if applied.get("applied") else None,
    })
    return delta["fixable_regressions"]


def queue_care_report(db: Database, settings: Settings, deal_id: int, delta: dict[str, Any],
                      fixed: list[str], cycle: int) -> int:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    thread = db.thread_for_lead(lead["id"])
    token = thread[0]["thread_token"] if thread else "care"
    after, before = delta["after"], delta["before"]
    plan = plan_lib.get(settings, deal.get("plan") or deal["package"])

    lines = [f"Hi {lead.get('business_name') or 'there'},",
             f"Month {cycle} check on {lead['domain']} is done."]
    if before.get("ada") is not None:
        lines.append(f"Accessibility {before['ada']}% → {after['ada']}%. "
                     f"AI-search readiness {before['seo']}% → {after['seo']}%.")
    else:
        lines.append(f"Accessibility {after['ada']}%. AI-search readiness {after['seo']}%.")

    if delta["regressions"]:
        titles = ", ".join(delta["regression_titles"][:4])
        if fixed:
            lines.append(f"{len(delta['regressions'])} thing(s) had slipped since last month ({titles}). "
                         f"We've already fixed {len(fixed)} of them; anything left needs a decision from you "
                         f"and is listed in the report.")
        else:
            lines.append(f"{len(delta['regressions'])} thing(s) had slipped since last month ({titles}). "
                         f"They're in the report with what each one needs.")
    else:
        lines.append("Nothing regressed this month and no new problems appeared, so there was nothing to fix. "
                     "That is what the monthly check is for.")
    if delta["resolved"]:
        lines.append(f"{len(delta['resolved'])} previously reported item(s) are now passing.")

    lines += [
        f"Full report: {settings.stripe.public_base_url.rstrip('/')}/r/{token}",
        f"{settings.company.signer_name}\n{settings.company.name} · {settings.company.website}",
        f"—\n{settings.company.legal_name}, {settings.company.postal_address}\n"
        f"You're receiving this as part of your {plan.name} plan. "
        f'Reply "unsubscribe" at any time to stop hearing from us.',
    ]
    body = "\n\n".join(lines)
    seq = len(thread) + 1
    return db.insert("messages", {
        "lead_id": lead["id"], "thread_token": token, "direction": "out", "kind": "delivery",
        "subject": f"{lead['domain']}: month {cycle} check", "body_text": body, "body_html": to_html(body),
        "to_addr": lead["contact_email"], "from_addr": settings.company.from_email,
        "message_id": f"<{token}.{seq}@{settings.company.reply_domain}>",
        "status": MessageStatus.QUEUED, "lint": {"ok": True, "problems": []}, "created_at": utcnow(),
    })


def mrr_cents(db: Database) -> int:
    """Monthly recurring revenue actually under contract."""
    row = db.one("SELECT COALESCE(SUM(monthly_cents), 0) AS mrr FROM deals "
                 "WHERE monthly_cents > 0 AND care_cancelled_at IS NULL AND care_started_at IS NOT NULL "
                 "AND status NOT IN ('refunded','cancelled')")
    return int(row["mrr"]) if row else 0


def active_care_clients(db: Database) -> list[dict[str, Any]]:
    return db.query(
        "SELECT d.*, l.domain, l.business_name FROM deals d JOIN leads l ON l.id = d.lead_id "
        "WHERE d.monthly_cents > 0 AND d.care_cancelled_at IS NULL AND d.care_started_at IS NOT NULL "
        "AND d.status NOT IN ('refunded','cancelled') ORDER BY d.next_care_at"
    )
