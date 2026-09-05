"""Scan one site: crawl a handful of pages, run both audits, compute scores and exposure,
snapshot HTML for the fixer, and persist everything."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from ..config import Settings
from ..db import Database, utcnow
from ..exposure import compute_exposure
from ..models import LeadStatus
from ..prospecting.discover import discover
from .ada import Finding, ada_score, run_axe
from .aiseo import aiseo_score, audit_home

PRIORITY_PATHS = ("contact", "about", "services", "menu", "team", "locations", "faq")


@dataclass
class PageSnapshot:
    url: str
    status: int | None
    raw_html: str
    rendered_html: str
    title: str
    load_ms: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ScanResult:
    url: str
    domain: str
    pages: list[PageSnapshot]
    findings: list[Finding]
    ada_score: int
    aiseo_score: int
    aiseo_facts: dict[str, Any]
    robots_txt: str | None
    contact_email: str | None
    contact_source: str | None
    platform: str
    all_emails: list[str]
    error: str | None = None

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.impact == "critical")

    def top_issues(self, n: int = 5) -> list[dict[str, Any]]:
        order = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
        seen: set[str] = set()
        out = []
        for f in sorted(self.findings, key=lambda f: (order.get(f.impact, 9), -f.count)):
            if f.rule_id in seen:
                continue
            seen.add(f.rule_id)
            out.append({"kind": f.kind, "rule_id": f.rule_id, "impact": f.impact, "plain": f.plain, "count": f.count})
            if len(out) >= n:
                break
        return out


def _same_site(base: str, href: str) -> bool:
    b, h = urlparse(base), urlparse(href)
    hb = (b.hostname or "").removeprefix("www.")
    hh = (h.hostname or "").removeprefix("www.")
    return hb == hh and h.scheme in ("http", "https")


def pick_internal_links(home_url: str, html: str, limit: int) -> list[str]:
    hrefs = re.findall(r"""<a[^>]+href=["']([^"'#?]+)["']""", html, re.I)
    seen: list[str] = []
    for h in hrefs:
        full = urljoin(home_url, h.strip())
        if not _same_site(home_url, full) or full.rstrip("/") == home_url.rstrip("/"):
            continue
        if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|zip|mp4|webp|css|js)$", full, re.I):
            continue
        if re.search(r"(login|logout|cart|checkout|account|wp-admin|feed|tag/|category/|\.xml)", full, re.I):
            continue
        if full not in seen:
            seen.append(full)
    seen.sort(key=lambda u: (0 if any(p in u.lower() for p in PRIORITY_PATHS) else 1, len(u)))
    return seen[:limit]


def _fetch_text(context: Any, url: str, timeout_ms: int) -> tuple[bool, str | None]:
    try:
        r = context.request.get(url, timeout=timeout_ms, max_redirects=3)
        if r.ok:
            ctype = (r.headers.get("content-type") or "").lower()
            body = r.text()
            if "html" in ctype and not url.endswith(".xml"):
                # servers that return a 200 HTML page for everything
                return False, None
            return True, body
        return False, None
    except PlaywrightError:
        return False, None


def scan_site(url: str, settings: Settings, browser: Browser) -> ScanResult:
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    context = browser.new_context(user_agent=settings.scanning.user_agent, ignore_https_errors=True,
                                  viewport={"width": 1366, "height": 900})
    context.set_default_timeout(settings.scanning.page_timeout_ms)
    pages: list[PageSnapshot] = []
    findings: list[Finding] = []
    try:
        page = context.new_page()
        home = _load(page, url, settings.scanning.page_timeout_ms)
        if home is None:
            return ScanResult(url, domain, [], [], 0, 0, {}, None, None, None, "unknown", [], error="home page failed to load")
        pages.append(home)
        findings += run_axe(page, home.url)

        origin = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
        robots_ok, robots_txt = _fetch_text(context, origin + "/robots.txt", settings.scanning.page_timeout_ms)
        sitemap_ok, _ = _fetch_text(context, origin + "/sitemap.xml", settings.scanning.page_timeout_ms)
        if not sitemap_ok:
            sitemap_ok, _ = _fetch_text(context, origin + "/sitemap_index.xml", settings.scanning.page_timeout_ms)
        llms_ok, _ = _fetch_text(context, origin + "/llms.txt", settings.scanning.page_timeout_ms)

        seo_findings, facts = audit_home(
            url=home.url, raw_html=home.raw_html, rendered_html=home.rendered_html,
            robots_txt=robots_txt if robots_ok else None, sitemap_ok=sitemap_ok, llms_txt_ok=llms_ok, load_ms=home.load_ms,
        )
        findings += seo_findings

        for link in pick_internal_links(home.url, home.rendered_html, settings.scanning.max_pages_per_site - 1):
            snap = _load(page, link, settings.scanning.page_timeout_ms)
            if snap is None:
                continue
            pages.append(snap)
            findings += run_axe(page, snap.url)

        disc = discover([(p.url, p.rendered_html) for p in pages], domain, home.headers)
        return ScanResult(
            url=home.url, domain=domain, pages=pages, findings=findings,
            ada_score=ada_score(findings), aiseo_score=aiseo_score(findings), aiseo_facts=facts,
            robots_txt=robots_txt if robots_ok else None, contact_email=disc.email, contact_source=disc.email_source,
            platform=disc.platform, all_emails=disc.all_emails,
        )
    finally:
        context.close()


def _load(page: Any, url: str, timeout_ms: int) -> PageSnapshot | None:
    t0 = time.monotonic()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=min(8000, timeout_ms))
        except PlaywrightTimeout:
            pass
    except PlaywrightError:
        return None
    load_ms = int((time.monotonic() - t0) * 1000)
    raw_html = ""
    headers: dict[str, str] = {}
    status = None
    if resp is not None:
        status = resp.status
        headers = {k.lower(): v for k, v in resp.headers.items()}
        try:
            raw_html = resp.text()
        except PlaywrightError:
            raw_html = ""
    if status is not None and status >= 400:
        return None
    rendered = page.content()
    return PageSnapshot(url=page.url, status=status, raw_html=raw_html, rendered_html=rendered,
                        title=page.title(), load_ms=load_ms, headers=headers)


# ------------------------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------------------------

def snapshot_dir(settings: Settings, domain: str) -> Path:
    d = settings.workdir / "snapshots" / domain
    d.mkdir(parents=True, exist_ok=True)
    return d


def persist_scan(db: Database, settings: Settings, lead: dict[str, Any], result: ScanResult, kind: str = "baseline") -> int:
    if result.error:
        scan_id = db.insert("scans", {"lead_id": lead["id"], "kind": kind, "status": "failed", "error": result.error,
                                      "created_at": utcnow()})
        db.log_event("scan_failed", lead["id"], error=result.error)
        return scan_id

    exposure = compute_exposure(ada_score=result.ada_score, aiseo_score=result.aiseo_score, region=lead.get("region"),
                                category=lead.get("category"), critical_count=result.critical_count)
    snap_dir = snapshot_dir(settings, lead["domain"])
    page_index = []
    for p in result.pages:
        h = hashlib.sha1(p.url.encode()).hexdigest()[:12]
        (snap_dir / f"{h}.raw.html").write_text(p.raw_html, encoding="utf-8")
        (snap_dir / f"{h}.rendered.html").write_text(p.rendered_html, encoding="utf-8")
        page_index.append({"url": p.url, "status": p.status, "title": p.title, "load_ms": p.load_ms, "snapshot": h})
    if result.robots_txt is not None:
        (snap_dir / "robots.txt").write_text(result.robots_txt, encoding="utf-8")

    ada_summary = {"score": result.ada_score, "by_impact": _by_impact(result.findings, "ada"),
                   "top": [i for i in result.top_issues(8) if i["kind"] == "ada"]}
    aiseo_summary = {"score": result.aiseo_score, "by_impact": _by_impact(result.findings, "aiseo"),
                     "facts": result.aiseo_facts, "top": [i for i in result.top_issues(12) if i["kind"] == "aiseo"]}
    scan_id = db.insert("scans", {
        "lead_id": lead["id"], "kind": kind, "status": "ok", "ada_score": result.ada_score, "aiseo_score": result.aiseo_score,
        "ada_summary": ada_summary, "aiseo_summary": aiseo_summary, "pages": page_index, "exposure": exposure,
        "created_at": utcnow(),
    })
    for f in result.findings:
        db.insert("findings", f.as_row(scan_id))

    updates: dict[str, Any] = {"platform": result.platform}
    if kind == "baseline":
        if result.contact_email and not lead.get("contact_email"):
            updates["contact_email"] = result.contact_email
            updates["contact_source"] = result.contact_source
        if not lead.get("business_name") and result.pages:
            updates["business_name"] = _guess_name(result.pages[0].title, result.domain)
        db.update("leads", lead["id"], **updates)
    db.log_event("scan_done", lead["id"], scan_id=scan_id, ada=result.ada_score, aiseo=result.aiseo_score,
                 pages=len(result.pages), scan_kind=kind)
    return scan_id


def _by_impact(findings: list[Finding], kind: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        if f.kind == kind:
            out[f.impact] = out.get(f.impact, 0) + 1
    return out


def _guess_name(title: str, domain: str) -> str:
    t = re.split(r"\s[|\-–—:]\s", title or "")[0].strip()
    if 2 <= len(t) <= 60 and t.lower() not in ("home", "welcome", "homepage"):
        return t
    return domain.split(".")[0].replace("-", " ").title()


def classify_after_scan(db: Database, settings: Settings, lead_id: int, scan_id: int) -> str:
    """Decide the lead's next status from the scan."""
    scan = db.one("SELECT * FROM scans WHERE id = ?", (scan_id,))
    lead = db.get_lead(lead_id)
    assert scan and lead
    if scan["status"] != "ok":
        db.set_lead_status(lead_id, LeadStatus.ARCHIVED, "scan failed")
        return LeadStatus.ARCHIVED
    if (scan["ada_score"] or 0) >= 90 and (scan["aiseo_score"] or 0) >= 85:
        db.set_lead_status(lead_id, LeadStatus.CLEAN)
        return LeadStatus.CLEAN
    if not lead.get("contact_email"):
        db.set_lead_status(lead_id, LeadStatus.NO_CONTACT)
        return LeadStatus.NO_CONTACT
    if db.is_suppressed(lead["contact_email"]):
        db.set_lead_status(lead_id, LeadStatus.UNSUBSCRIBED, "address suppressed")
        return LeadStatus.UNSUBSCRIBED
    db.set_lead_status(lead_id, LeadStatus.SCANNED)
    return LeadStatus.SCANNED
