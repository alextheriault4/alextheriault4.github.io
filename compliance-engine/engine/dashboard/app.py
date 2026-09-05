"""Operator dashboard + the handful of public pages prospects and clients touch.

Admin pages need the admin token (login form sets a cookie). Public pages are
unauthenticated by design: the report, unsubscribe, agreement, pay/thank-you, bundle
download (by unguessable thread token) and the Stripe webhook.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..autopilot import erase_lead_data
from ..config import Settings, get_settings
from ..db import Database, utcnow
from ..deals.checkout import handle_stripe_webhook, mark_paid
from ..exposure import money
from ..finance import ledger
from ..legal import SecretBox, is_secret
from ..models import LeadStatus, MessageStatus

TEMPLATES = Path(__file__).parent / "templates"


def create_app(settings: Settings | None = None, db: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or Database(settings.database_path)
    app = FastAPI(title="Compliance engine", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(TEMPLATES))
    templates.env.filters["money"] = money
    templates.env.filters["json"] = lambda v: json.dumps(v, indent=1) if not isinstance(v, str) else v

    def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
        base = {"request": request, "settings": settings, "mode": settings.mode, "paused": db.is_paused(),
                "breaker": db.get_kv("breaker"), "last_tick": db.get_kv("last_tick"), "company": settings.company}
        return templates.TemplateResponse(request, name, {**base, **ctx})

    def admin(request: Request) -> None:
        tok = request.cookies.get("ce_admin") or request.headers.get("x-admin-token") or request.query_params.get("token")
        if tok != settings.dashboard.admin_token:
            raise HTTPException(status_code=303, headers={"Location": "/login"})

    # ---------------- auth ----------------
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    def login(token: str = Form(...)):
        if token != settings.dashboard.admin_token:
            raise HTTPException(status_code=403, detail="bad token")
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("ce_admin", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
        return r

    # ---------------- overview ----------------
    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def index(request: Request):
        counts = db.counts_by_status()
        sent = db.one("SELECT COUNT(*) AS n FROM messages WHERE direction='out' AND kind IN ('initial','followup') AND status='sent'")["n"]
        replies = db.one("SELECT COUNT(DISTINCT lead_id) AS n FROM messages WHERE direction='in'")["n"]
        contacted = db.one("SELECT COUNT(*) AS n FROM leads WHERE status NOT IN ('new','scanned','no_contact','clean','queued','archived')")["n"]
        held = db.one("SELECT COUNT(*) AS n FROM messages WHERE status IN ('held','draft')")["n"]
        needs_human = db.leads_by_status(LeadStatus.NEEDS_HUMAN, limit=50)
        events = db.query("SELECT e.*, l.domain FROM events e LEFT JOIN leads l ON l.id=e.lead_id ORDER BY e.id DESC LIMIT 40")
        for e in events:
            e["detail"] = json.loads(e["detail"]) if e.get("detail") else {}
        fin = ledger.summary(db)
        gates = {"send email": settings.can_send_email(), "charge cards": settings.can_charge(), "apply fixes": settings.can_apply_fixes()}
        last_report = db.get_kv("last_tick_report")
        return render(request, "index.html", counts=counts, sent=sent, replies=replies, contacted=contacted, held=held,
                      needs_human=needs_human, events=events, fin=fin, gates=gates, autonomy=settings.autonomy,
                      notices=db.notices(limit=12), preflight=settings.preflight(), autopilot=settings.autopilot,
                      last_report=json.loads(last_report) if last_report else None)

    # ---------------- leads ----------------
    @app.get("/leads", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def leads(request: Request, status: str | None = None, q: str | None = None):
        sql = "SELECT l.*, s.ada_score, s.aiseo_score FROM leads l LEFT JOIN scans s ON s.id = (SELECT id FROM scans WHERE lead_id=l.id AND status='ok' AND kind='baseline' ORDER BY id DESC LIMIT 1)"
        where, params = [], []
        if status:
            where.append("l.status=?"); params.append(status)
        if q:
            where.append("(l.domain LIKE ? OR l.business_name LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = db.query(sql + " ORDER BY l.updated_at DESC LIMIT 500", tuple(params))
        return render(request, "leads.html", rows=rows, status=status, q=q or "", statuses=[s.value for s in LeadStatus])

    @app.get("/leads/{lead_id}", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def lead_detail(request: Request, lead_id: int):
        lead = db.get_lead(lead_id)
        if not lead:
            raise HTTPException(404)
        scan = db.latest_scan(lead_id)
        verification = db.latest_scan(lead_id, kind="verification")
        findings = db.findings_for_scan(scan["id"]) if scan else []
        thread = db.thread_for_lead(lead_id)
        for m in thread:
            m["lint"] = json.loads(m["lint"]) if m.get("lint") else None
        deals = db.query("SELECT * FROM deals WHERE lead_id=? ORDER BY id DESC", (lead_id,))
        fixes = db.query("SELECT f.* FROM fixes f JOIN deals d ON d.id=f.deal_id WHERE d.lead_id=? ORDER BY f.id DESC", (lead_id,))
        for f in fixes:
            f["summary"] = json.loads(f["summary"]) if f.get("summary") else {}
        events = db.query("SELECT * FROM events WHERE lead_id=? ORDER BY id DESC LIMIT 100", (lead_id,))
        for e in events:
            e["detail"] = json.loads(e["detail"]) if e.get("detail") else {}
        creds = {k: db.get_kv(f"lead:{lead_id}:{k}") for k in ("wp_user", "wp_url", "github_repo", "github_subdir")}
        return render(request, "lead.html", lead=lead, scan=scan, verification=verification, findings=findings, thread=thread,
                      deals=deals, fixes=fixes, events=events, creds=creds, statuses=[s.value for s in LeadStatus],
                      console=settings.email.provider == "console")

    @app.post("/leads/{lead_id}/status", dependencies=[Depends(admin)])
    def set_status(lead_id: int, status: str = Form(...), reason: str = Form("")):
        db.set_lead_status(lead_id, status, reason or "set from dashboard")
        if status in ("not_interested", "unsubscribed"):
            lead = db.get_lead(lead_id)
            if lead and lead.get("contact_email"):
                db.suppress(lead["contact_email"], status, lead_id)
            db.execute("UPDATE messages SET status='suppressed' WHERE lead_id=? AND direction='out' AND status IN ('queued','held','draft')", (lead_id,))
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.post("/leads/{lead_id}/creds", dependencies=[Depends(admin)])
    def set_creds(lead_id: int, wp_url: str = Form(""), wp_user: str = Form(""), wp_app_password: str = Form(""),
                  github_repo: str = Form(""), github_subdir: str = Form("")):
        box = SecretBox(settings.secrets_key)
        for k, v in (("wp_url", wp_url), ("wp_user", wp_user), ("wp_app_password", wp_app_password),
                     ("github_repo", github_repo), ("github_subdir", github_subdir)):
            if not v.strip():
                continue
            if is_secret(k):
                # Refuses outright rather than writing a client's password in the clear.
                try:
                    db.set_secret(f"lead:{lead_id}:{k}", v.strip(), box)
                except RuntimeError as e:
                    raise HTTPException(400, str(e))
            else:
                db.set_kv(f"lead:{lead_id}:{k}", v.strip())
        db.log_event("status_changed", lead_id, note="access details updated")
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.post("/leads/{lead_id}/erase", dependencies=[Depends(admin)])
    def erase_lead(lead_id: int):
        erase_lead_data(db, settings, lead_id)
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.get("/notices", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def notices(request: Request, all: int = 0):
        rows = db.notices(limit=200, unread_only=not all)
        return render(request, "notices.html", rows=rows, showing_all=bool(all))

    @app.post("/notices/read", dependencies=[Depends(admin)])
    def notices_read():
        db.mark_notices_read()
        return RedirectResponse("/notices", status_code=303)

    @app.post("/messages/{msg_id}/approve", dependencies=[Depends(admin)])
    def approve_message(msg_id: int):
        m = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
        if not m:
            raise HTTPException(404)
        db.update("messages", msg_id, approved=1, status=MessageStatus.QUEUED, hold_reason=None)
        db.log_event("status_changed", m["lead_id"], message_id=msg_id, note="approved by human")
        return RedirectResponse(f"/leads/{m['lead_id']}", status_code=303)

    @app.post("/messages/{msg_id}/discard", dependencies=[Depends(admin)])
    def discard_message(msg_id: int):
        m = db.one("SELECT * FROM messages WHERE id=?", (msg_id,))
        if not m:
            raise HTTPException(404)
        db.update("messages", msg_id, status=MessageStatus.SUPPRESSED, hold_reason="discarded by human")
        return RedirectResponse(f"/leads/{m['lead_id']}", status_code=303)

    @app.post("/leads/{lead_id}/simulate-reply", dependencies=[Depends(admin)])
    def simulate_reply(lead_id: int, text: str = Form(...)):
        from ..inbox.provider import ConsoleProvider
        from ..orchestrator import Orchestrator

        if settings.email.provider != "console":
            raise HTTPException(400, "only with the console provider")
        lead = db.get_lead(lead_id)
        thread = db.thread_for_lead(lead_id)
        if not (lead and thread):
            raise HTTPException(400, "no thread")
        prov = ConsoleProvider(settings.workdir)
        prov.simulate_reply(thread_token=thread[0]["thread_token"], from_addr=lead["contact_email"], text=text,
                            reply_domain=settings.company.reply_domain)
        Orchestrator(settings, db=db, provider=prov).stage_inbound()
        return RedirectResponse(f"/leads/{lead_id}", status_code=303)

    @app.get("/outbox", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def outbox(request: Request):
        rows = db.query("SELECT m.*, l.domain FROM messages m JOIN leads l ON l.id=m.lead_id WHERE m.direction='out' AND m.status IN ('held','draft','queued') ORDER BY m.id")
        for m in rows:
            m["lint"] = json.loads(m["lint"]) if m.get("lint") else None
        return render(request, "outbox.html", rows=rows)

    # ---------------- controls ----------------
    @app.post("/controls/{action}", dependencies=[Depends(admin)])
    def controls(action: str):
        if action == "pause":
            db.set_kv("paused", "1")
        elif action == "resume":
            db.set_kv("paused", "0")
        elif action == "reset-breaker":
            db.set_kv("breaker", ""); db.set_kv("breaker_reason", "")
        elif action == "tick":
            from ..orchestrator import Orchestrator
            Orchestrator(settings, db=db).tick()
        else:
            raise HTTPException(404)
        db.log_event("status_changed", None, control=action)
        return RedirectResponse("/", status_code=303)

    # ---------------- finance ----------------
    @app.get("/finance", response_class=HTMLResponse, dependencies=[Depends(admin)])
    def finance(request: Request):
        deals = db.query("SELECT d.*, l.domain, l.business_name FROM deals d JOIN leads l ON l.id=d.lead_id ORDER BY d.id DESC LIMIT 200")
        return render(request, "finance.html", fin=ledger.summary(db), monthly=ledger.monthly(db), tax=ledger.tax_by_region(db),
                      deals=deals, live=settings.can_charge()[0])

    @app.get("/finance/export.csv", dependencies=[Depends(admin)])
    def finance_export():
        return PlainTextResponse(ledger.export_csv(db), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=ledger.csv"})

    @app.post("/deals/{deal_id}/simulate-payment", dependencies=[Depends(admin)])
    def simulate_payment(deal_id: int):
        deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
        if not deal:
            raise HTTPException(404)
        if settings.can_charge()[0] and not str(deal.get("stripe_session_id") or "").startswith("placeholder"):
            raise HTTPException(400, "live Stripe deal; wait for the webhook")
        mark_paid(db, settings, deal_id, payment_intent="simulated")
        return RedirectResponse(f"/leads/{deal['lead_id']}", status_code=303)

    # ---------------- public pages ----------------
    def _lead_by_token(token: str) -> dict[str, Any]:
        m = db.one("SELECT lead_id FROM messages WHERE thread_token=? ORDER BY id LIMIT 1", (token,))
        lead = db.get_lead(m["lead_id"]) if m else None
        if not lead:
            raise HTTPException(404)
        return lead

    @app.get("/r/{token}", response_class=HTMLResponse)
    def public_report(request: Request, token: str):
        lead = _lead_by_token(token)
        scan = db.latest_scan(lead["id"])
        verification = db.latest_scan(lead["id"], kind="verification")
        if not scan:
            raise HTTPException(404)
        findings = db.findings_for_scan(scan["id"])
        after = db.findings_for_scan(verification["id"]) if verification else None
        return render(request, "report.html", lead=lead, scan=scan, findings=findings, verification=verification,
                      after=after, token=token, assumptions=scan["exposure"])

    @app.get("/u/{token}", response_class=HTMLResponse)
    def unsubscribe(request: Request, token: str):
        lead = _lead_by_token(token)
        if lead.get("contact_email"):
            db.suppress(lead["contact_email"], "unsubscribe", lead["id"])
        db.execute("UPDATE messages SET status='suppressed' WHERE lead_id=? AND direction='out' AND status IN ('queued','held','draft')", (lead["id"],))
        db.set_lead_status(lead["id"], LeadStatus.UNSUBSCRIBED, "unsubscribe link")
        return render(request, "unsubscribe.html", lead=lead)

    @app.post("/u/{token}")
    def unsubscribe_post(token: str):
        return unsubscribe(None, token)  # List-Unsubscribe-Post one-click

    @app.get("/bot", response_class=HTMLResponse)
    def bot_info(request: Request):
        """What our crawler is, so anyone who sees it in their logs can find out and block it."""
        return render(request, "bot.html")

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy(request: Request):
        return render(request, "privacy.html")

    @app.get("/terms", response_class=HTMLResponse)
    def terms(request: Request):
        return render(request, "terms.html")

    @app.get("/erase/{token}", response_class=HTMLResponse)
    def erase_page(request: Request, token: str):
        lead = _lead_by_token(token)
        return render(request, "erase.html", lead=lead, token=token, done=False)

    @app.post("/erase/{token}", response_class=HTMLResponse)
    def erase_confirm(request: Request, token: str):
        lead = _lead_by_token(token)
        erase_lead_data(db, settings, lead["id"])
        return render(request, "erase.html", lead=lead, token=token, done=True)

    @app.get("/agreement/{deal_id}", response_class=HTMLResponse)
    def agreement(request: Request, deal_id: int):
        deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
        if not deal:
            raise HTTPException(404)
        lead = db.get_lead(deal["lead_id"])
        return render(request, "agreement.html", deal=deal, lead=lead)

    @app.get("/pay/{deal_id}", response_class=HTMLResponse)
    def pay_placeholder(request: Request, deal_id: int):
        deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
        if not deal:
            raise HTTPException(404)
        lead = db.get_lead(deal["lead_id"])
        return render(request, "pay.html", deal=deal, lead=lead, live=settings.can_charge()[0])

    @app.get("/paid/{deal_id}", response_class=HTMLResponse)
    def paid(request: Request, deal_id: int):
        deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
        if not deal:
            raise HTTPException(404)
        return render(request, "paid.html", deal=deal, lead=db.get_lead(deal["lead_id"]))

    @app.get("/bundle/{token}")
    def bundle_download(token: str):
        lead = _lead_by_token(token)
        fix = db.one("SELECT f.* FROM fixes f JOIN deals d ON d.id=f.deal_id WHERE d.lead_id=? AND f.bundle_path IS NOT NULL ORDER BY f.id DESC LIMIT 1", (lead["id"],))
        if not fix:
            raise HTTPException(404)
        root = Path(fix["bundle_path"])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in root.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(root).as_posix())
        buf.seek(0)
        db.log_event("fix_delivered", lead["id"], note="bundle downloaded")
        return StreamingResponse(buf, media_type="application/zip",
                                 headers={"Content-Disposition": f"attachment; filename={lead['domain']}-fixes.zip"})

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")
        try:
            result = handle_stripe_webhook(db, settings, payload, sig)
        except Exception as e:  # noqa: BLE001
            db.log_event("error", None, stage="stripe_webhook", error=str(e)[:300])
            raise HTTPException(400, str(e))
        return result

    @app.get("/health")
    def health():
        return {"ok": True, "mode": settings.mode, "last_tick": db.get_kv("last_tick"), "paused": db.is_paused(), "at": utcnow()}

    return app
