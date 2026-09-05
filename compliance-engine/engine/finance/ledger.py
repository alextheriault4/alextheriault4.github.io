"""Money reporting.

Stripe Tax calculates and collects sales tax at checkout. What it can't do is register
you in states where you cross a threshold or file the returns; this module produces the
numbers your accountant (or Stripe's filing partners) need for that, plus a plain P&L.
"""
from __future__ import annotations

import csv
import io
from typing import Any

from ..db import Database


def summary(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT kind, SUM(amount_cents) AS total FROM ledger GROUP BY kind")
    by_kind = {r["kind"]: int(r["total"] or 0) for r in rows}
    gross = by_kind.get("charge", 0)
    refunds = by_kind.get("refund", 0)
    fees = by_kind.get("processing_fee", 0)
    tax = by_kind.get("sales_tax", 0)
    deals = db.one("SELECT COUNT(*) AS n FROM deals WHERE status IN ('paid','in_progress','delivered','verified')")["n"]
    return {"gross_cents": gross, "refunds_cents": refunds, "fees_cents": fees, "net_cents": gross + refunds + fees,
            "sales_tax_collected_cents": tax, "paid_deals": deals, "avg_deal_cents": int(gross / deals) if deals else 0}


def monthly(db: Database) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT substr(occurred_at,1,7) AS month, kind, SUM(amount_cents) AS total FROM ledger GROUP BY month, kind ORDER BY month"
    )
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r["month"], {})[r["kind"]] = int(r["total"] or 0)
    return [{"month": m, **v, "net_cents": v.get("charge", 0) + v.get("refund", 0) + v.get("processing_fee", 0)} for m, v in out.items()]


def export_csv(db: Database) -> str:
    rows = db.query(
        "SELECT l.occurred_at, l.kind, l.amount_cents, l.currency, l.stripe_id, l.memo, d.id AS deal_id, d.package, "
        "le.domain, le.business_name, le.region FROM ledger l LEFT JOIN deals d ON d.id = l.deal_id LEFT JOIN leads le ON le.id = d.lead_id "
        "ORDER BY l.occurred_at"
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "kind", "amount", "currency", "stripe_id", "memo", "deal_id", "package", "client_domain", "client_name", "client_region"])
    for r in rows:
        w.writerow([r["occurred_at"], r["kind"], f"{r['amount_cents'] / 100:.2f}", r["currency"], r["stripe_id"] or "", r["memo"] or "",
                    r["deal_id"] or "", r["package"] or "", r["domain"] or "", r["business_name"] or "", r["region"] or ""])
    return buf.getvalue()


def tax_by_region(db: Database) -> list[dict[str, Any]]:
    return db.query(
        "SELECT COALESCE(le.region,'?') AS region, COUNT(DISTINCT d.id) AS deals, SUM(CASE WHEN l.kind='charge' THEN l.amount_cents ELSE 0 END) AS taxable_cents, "
        "SUM(CASE WHEN l.kind='sales_tax' THEN l.amount_cents ELSE 0 END) AS tax_cents FROM ledger l JOIN deals d ON d.id=l.deal_id "
        "JOIN leads le ON le.id=d.lead_id GROUP BY region ORDER BY taxable_cents DESC"
    )
