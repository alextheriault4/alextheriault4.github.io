"""Command line entry points. ``python -m engine <command>`` or ``compliance-engine <command>``."""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

from .config import get_settings
from .db import Database
from .orchestrator import Orchestrator


def _orc() -> Orchestrator:
    return Orchestrator(get_settings())


def cmd_init(args: argparse.Namespace) -> None:
    s = get_settings()
    Database(s.database_path)
    env = Path(".env")
    if not env.exists():
        example = Path(__file__).parent.parent / ".env.example"
        if example.exists():
            env.write_text(example.read_text())
            print("wrote .env from .env.example - edit it before going live")
    print(f"database ready at {s.database_path} (mode={s.mode}, llm={s.llm.provider}, email={s.email.provider})")


def cmd_add_leads(args: argparse.Namespace) -> None:
    o = _orc()
    if args.csv:
        print(f"imported {o.import_csv(args.csv)} new leads from {args.csv}")
    if args.url:
        from .prospecting.sources import Prospect, normalise_url

        norm = normalise_url(args.url)
        if not norm:
            sys.exit("url not usable")
        p = Prospect(url=norm[0], domain=norm[1], business_name=args.name, category=args.category, city=args.city,
                     region=args.region, email=args.email, source="manual")
        print(f"added {o.add_prospects([p])} lead(s)")


def cmd_prospect(args: argparse.Namespace) -> None:
    o = _orc()
    n = o.prospect(category=args.category, city=args.city, region=args.region, limit=args.limit, source=args.source)
    print(f"added {n} new leads for '{args.category}' in {args.city}{', ' + args.region if args.region else ''}")


def cmd_scan(args: argparse.Namespace) -> None:
    o = _orc()
    if args.lead:
        o.db.set_lead_status(args.lead, "new", "manual rescan")
    print(f"scanned {o.stage_scan(limit=args.limit)} leads")


def cmd_draft(args: argparse.Namespace) -> None:
    print(f"drafted {_orc().stage_draft(limit=args.limit)} emails")


def cmd_tick(args: argparse.Namespace) -> None:
    print(json.dumps(_orc().tick(), indent=1))


def cmd_send(args: argparse.Namespace) -> None:
    """Flush the outbound queue now.

    Cold email normally waits for a weekday inside the send window, which means a test run
    in the evening or at a weekend looks like nothing happened. ``--now`` ignores that
    window (the suppression list, the allowlist and the circuit breaker still apply).
    """
    from .outreach.sequence import deliver_queued

    o = _orc()
    print(json.dumps(deliver_queued(o.db, o.settings, o.provider, ignore_window=args.now), indent=1))


def cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _orc().run_forever()


def cmd_dashboard(args: argparse.Namespace) -> None:
    import uvicorn

    from .dashboard.app import create_app

    s = get_settings()
    uvicorn.run(create_app(s), host=args.host or s.dashboard.host, port=args.port or s.dashboard.port)


def cmd_simulate_reply(args: argparse.Namespace) -> None:
    o = _orc()
    from .inbox.provider import ConsoleProvider

    if not isinstance(o.provider, ConsoleProvider):
        sys.exit("simulate-reply only works with the console email provider")
    thread = o.db.thread_for_lead(args.lead)
    if not thread:
        sys.exit("lead has no thread yet")
    lead = o.db.get_lead(args.lead)
    o.provider.simulate_reply(thread_token=thread[0]["thread_token"], from_addr=lead["contact_email"], text=args.text,
                              reply_domain=o.settings.company.reply_domain)
    print(json.dumps(o.stage_inbound()))


def cmd_simulate_payment(args: argparse.Namespace) -> None:
    from .deals.checkout import mark_paid

    o = _orc()
    mark_paid(o.db, o.settings, args.deal, payment_intent="simulated")
    print(f"deal {args.deal} marked paid")


def cmd_status(args: argparse.Namespace) -> None:
    from .autopilot import pending_refunds

    o = _orc()
    print(json.dumps({
        "mode": o.settings.mode, "live_blocked": o.settings.live_blocked_reason(),
        "autopilot": o.settings.autopilot.enabled, "llm_provider": o.settings.llm.provider,
        "paused": o.db.is_paused(), "breaker": o.db.get_kv("breaker"), "last_tick": o.db.get_kv("last_tick"),
        "self_test_allowlist": o.settings.legal.only_email_addresses or None,
        "waiting_on_you": len(o.db.leads_by_status("needs_human")), "unread_notices": len(o.db.notices()),
        "refunds_awaiting_approval": len(pending_refunds(o.db)),
        "leads": o.db.counts_by_status(),
    }, indent=1))


def cmd_pricing(args: argparse.Namespace) -> None:
    """Where the price is, how each rung performed, and what would move it next."""
    from . import pricing

    o = _orc()
    if args.set is not None:
        try:
            point = pricing.set_rung(o.db, o.settings, args.set)
        except ValueError as e:
            print(e)
            return
        print(f"price is now {point.label}")
        return
    info = pricing.explain(o.db, o.settings)
    print(f"now: {info['current']['label']}  ({info['current']['reason'] or 'the configured list price'})")
    print(f"next: {info['next_move']}\n")
    print(f"{'rung':<5}{'price':<22}{'emailed':>8}{'replied':>8}{'sold':>6}{'conv':>8}{'revenue':>10}")
    for r in info["ladder"]:
        mark = "*" if r["current"] else " "
        print(f"{mark}{r['rung']:<4}{r['label']:<22}{r['sent']:>8}{r['replied']:>8}{r['paid']:>6}"
              f"{r['conversion_pct']:>7}%{r['revenue_cents'] / 100:>10,.2f}")


def cmd_secret(args: argparse.Namespace) -> None:
    """Store a credential the engine needs, encrypted at rest.

    The only one you have to set yourself is ``github_token`` - the account that opens the
    pull requests. Client credentials arrive through the customer's own setup page.
    """
    from .legal import SECRET_KEYS, SecretBox

    o = _orc()
    box = SecretBox(o.settings.secrets_key)
    if not args.set:
        for key in SECRET_KEYS:
            print(f"{key:<20}{'set' if o.db.get_kv(key) else '-'}")
        return
    if not box.available():
        print('CE_SECRETS_KEY is unset. Generate one with:\n'
              '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        return
    value = args.value or getpass.getpass(f"{args.set}: ")
    if not value:
        print("nothing entered; not stored")
        return
    o.db.set_secret(args.set, value, box)
    print(f"{args.set} stored, encrypted")


def cmd_preflight(args: argparse.Namespace) -> None:
    """Everything that must be true before real emails and real charges are allowed."""
    s = get_settings()
    problems = s.preflight()
    if not problems:
        print("preflight: ready to go live")
        return
    print("preflight: NOT ready. Live mode stays blocked until these are fixed:\n")
    for p in problems:
        print(f"  - {p}")
    print("\nSet the CE_LEGAL__* acknowledgements only once they are actually true.")
    sys.exit(1)


def cmd_notices(args: argparse.Namespace) -> None:
    o = _orc()
    rows = o.db.notices(limit=args.limit, unread_only=not args.all)
    for n in reversed(rows):
        where = f" [{n['domain']}]" if n.get("domain") else ""
        print(f"{n['created_at'][:16].replace('T', ' ')}{where} {n['detail'].get('headline', '')}")
    if not rows:
        print("nothing new")
    if args.mark_read:
        o.db.mark_notices_read()


def cmd_refunds(args: argparse.Namespace) -> None:
    """List refunds the engine thinks are owed, and approve or decline them. Money only
    moves when you say so."""
    from .autopilot import approve_refund, decline_refund, pending_refunds

    o = _orc()
    if args.approve:
        print(json.dumps(approve_refund(o.db, o.settings, args.approve, approved_by="cli"), indent=1))
        return
    if args.decline:
        print(json.dumps(decline_refund(o.db, o.settings, args.decline, args.note), indent=1))
        return
    rows = pending_refunds(o.db)
    if not rows:
        print("no refunds waiting")
        return
    for r in rows:
        print(f"deal {r['id']}  {r['price_cents'] / 100:>9,.2f} {r['currency'].upper()}  "
              f"{r['business_name'] or r['domain']}\n    since {r['requested_at'][:16]}  {r['refund_reason']}")
    print("\napprove with:  compliance-engine refunds --approve <deal id>")
    print("decline with:  compliance-engine refunds --decline <deal id> --note 'why'")


def cmd_erase(args: argparse.Namespace) -> None:
    from .autopilot import erase_lead_data

    o = _orc()
    print(json.dumps(erase_lead_data(o.db, o.settings, args.lead), indent=1))


def cmd_export_ledger(args: argparse.Namespace) -> None:
    from .finance.ledger import export_csv

    sys.stdout.write(export_csv(_orc().db))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="compliance-engine")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the database and a .env from the example").set_defaults(fn=cmd_init)
    a = sub.add_parser("add-leads", help="import leads from CSV or add one URL")
    a.add_argument("--csv"); a.add_argument("--url"); a.add_argument("--name"); a.add_argument("--category")
    a.add_argument("--city"); a.add_argument("--region"); a.add_argument("--email"); a.set_defaults(fn=cmd_add_leads)
    a = sub.add_parser("prospect", help="find small businesses by category and city")
    a.add_argument("--category", required=True); a.add_argument("--city", required=True); a.add_argument("--region")
    a.add_argument("--limit", type=int, default=50); a.add_argument("--source", default="auto", choices=["auto", "overpass", "google"])
    a.set_defaults(fn=cmd_prospect)
    a = sub.add_parser("scan", help="scan new leads"); a.add_argument("--lead", type=int); a.add_argument("--limit", type=int, default=10); a.set_defaults(fn=cmd_scan)
    a = sub.add_parser("draft", help="draft outreach for scanned leads"); a.add_argument("--limit", type=int, default=20); a.set_defaults(fn=cmd_draft)
    sub.add_parser("tick", help="run one pass of every stage").set_defaults(fn=cmd_tick)
    a = sub.add_parser("send", help="flush the outbound queue now")
    a.add_argument("--now", action="store_true", help="ignore the weekday/business-hours send window")
    a.set_defaults(fn=cmd_send)
    sub.add_parser("run", help="run the loop forever").set_defaults(fn=cmd_run)
    a = sub.add_parser("dashboard", help="serve the dashboard"); a.add_argument("--host"); a.add_argument("--port", type=int); a.set_defaults(fn=cmd_dashboard)
    a = sub.add_parser("simulate-reply", help="(console provider) inject a reply from a lead")
    a.add_argument("--lead", type=int, required=True); a.add_argument("--text", required=True); a.set_defaults(fn=cmd_simulate_reply)
    a = sub.add_parser("simulate-payment", help="mark a placeholder deal as paid"); a.add_argument("--deal", type=int, required=True); a.set_defaults(fn=cmd_simulate_payment)
    sub.add_parser("status", help="print pipeline counts").set_defaults(fn=cmd_status)
    a = sub.add_parser("secret", help="store a credential (github_token) encrypted at rest, or list what is set")
    a.add_argument("--set", metavar="KEY", help="which credential to store, e.g. github_token")
    a.add_argument("--value", help="the value; omit to be prompted without it appearing on screen")
    a.set_defaults(fn=cmd_secret)
    a = sub.add_parser("pricing", help="what we charge, how each price performed, and what would change it")
    a.add_argument("--set", type=int, metavar="RUNG", help="move to a rung by hand (0 is the most expensive)")
    a.set_defaults(fn=cmd_pricing)
    sub.add_parser("preflight", help="check whether it is safe and legal to go live").set_defaults(fn=cmd_preflight)
    a = sub.add_parser("notices", help="what the autopilot handled for you")
    a.add_argument("--all", action="store_true"); a.add_argument("--limit", type=int, default=50)
    a.add_argument("--mark-read", action="store_true"); a.set_defaults(fn=cmd_notices)
    a = sub.add_parser("refunds", help="refunds awaiting your approval (money never moves on its own)")
    a.add_argument("--approve", type=int, metavar="DEAL_ID"); a.add_argument("--decline", type=int, metavar="DEAL_ID")
    a.add_argument("--note", default=""); a.set_defaults(fn=cmd_refunds)
    a = sub.add_parser("erase", help="delete everything held about one business")
    a.add_argument("--lead", type=int, required=True); a.set_defaults(fn=cmd_erase)
    sub.add_parser("export-ledger", help="print the ledger as CSV").set_defaults(fn=cmd_export_ledger)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
