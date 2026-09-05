"""Command line entry points. ``python -m engine <command>`` or ``compliance-engine <command>``."""
from __future__ import annotations

import argparse
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
    o = _orc()
    print(json.dumps({"mode": o.settings.mode, "paused": o.db.is_paused(), "breaker": o.db.get_kv("breaker"),
                      "last_tick": o.db.get_kv("last_tick"), "leads": o.db.counts_by_status()}, indent=1))


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
    sub.add_parser("run", help="run the loop forever").set_defaults(fn=cmd_run)
    a = sub.add_parser("dashboard", help="serve the dashboard"); a.add_argument("--host"); a.add_argument("--port", type=int); a.set_defaults(fn=cmd_dashboard)
    a = sub.add_parser("simulate-reply", help="(console provider) inject a reply from a lead")
    a.add_argument("--lead", type=int, required=True); a.add_argument("--text", required=True); a.set_defaults(fn=cmd_simulate_reply)
    a = sub.add_parser("simulate-payment", help="mark a placeholder deal as paid"); a.add_argument("--deal", type=int, required=True); a.set_defaults(fn=cmd_simulate_payment)
    sub.add_parser("status", help="print pipeline counts").set_defaults(fn=cmd_status)
    sub.add_parser("export-ledger", help="print the ledger as CSV").set_defaults(fn=cmd_export_ledger)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
