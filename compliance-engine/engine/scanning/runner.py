"""Scan one site against the checklist.

Crawls politely, runs both detectors on each page, merges the per-page results into one
result per check, scores them, computes exposure, snapshots the HTML for the fixer, and
persists everything.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from ..config import Settings
from ..db import Database, utcnow
from ..exposure import compute_exposure
from ..fixability import Fixability, assess, eligible_to_pitch, wordpress_rest_available
from ..legal import CrawlPolicy, check_lead, safe_to_fetch
from ..models import LeadStatus
from ..prospecting.discover import discover
from ..standards import CHECKLIST_VERSION, CheckResult, Scorecard, headline, score
from .ada import PageAudit, merge_audits, run_axe
from .aiseo import audit_page, measure_web_vitals, parse_robots

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
    results: list[CheckResult]
    ada: Scorecard | None
    seo: Scorecard | None
    facts: dict[str, Any]
    robots_txt: str | None
    contact_email: str | None
    contact_source: str | None
    platform: str
    all_emails: list[str]
    fixability: Fixability | None = None
    error: str | None = None

    @property
    def ada_score(self) -> int:
        return self.ada.percent if self.ada else 0

    @property
    def aiseo_score(self) -> int:
        return self.seo.percent if self.seo else 0

    @property
    def critical_count(self) -> int:
        return len(self.ada.critical_failures) + len(self.seo.critical_failures) if self.ada and self.seo else 0

    def top_issues(self, n: int = 5) -> list[dict[str, Any]]:
        """The failures worth naming in an email: heaviest first, and things we can fix."""
        rows = (self.ada.failures if self.ada else []) + (self.seo.failures if self.seo else [])
        rows.sort(key=lambda r: (-r.check.weight, not r.check.auto_fixable))
        out = []
        for r in rows[:n]:
            detail = (r.detail or "").strip().rstrip(".")
            out.append({
                "kind": r.check.area, "rule_id": r.check_id, "title": r.check.title,
                "impact": "critical" if r.check.weight >= 9 else "serious" if r.check.weight >= 6 else "moderate",
                "plain": r.check.failure_phrase,
                "detail": detail, "count": r.count, "auto_fixable": r.check.auto_fixable,
            })
        return out


def _same_site(base: str, href: str) -> bool:
    b, h = urlparse(base), urlparse(href)
    return (b.hostname or "").removeprefix("www.") == (h.hostname or "").removeprefix("www.") \
        and h.scheme in ("http", "https")


def pick_internal_links(home_url: str, html: str, limit: int) -> list[str]:
    hrefs = re.findall(r"""<a[^>]+href=["']([^"'#?]+)["']""", html, re.I)
    seen: list[str] = []
    for h in hrefs:
        full = urljoin(home_url, h.strip())
        if not _same_site(home_url, full) or full.rstrip("/") == home_url.rstrip("/"):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|svg|zip|mp4|webp|css|js)$", full, re.I):
            continue
        if re.search(r"(login|logout|cart|checkout|account|wp-admin|feed|tag/|category/|\.xml)", full, re.I):
            continue
        if full not in seen:
            seen.append(full)
    seen.sort(key=lambda u: (0 if any(p in u.lower() for p in PRIORITY_PATHS) else 1, len(u)))
    return seen[:limit]


def _fetch_text(context: Any, url: str, timeout_ms: int) -> tuple[bool, str | None]:
    """Fetch a plain-text site file, rejecting the HTML error pages many hosts return instead."""
    try:
        r = context.request.get(url, timeout=timeout_ms, max_redirects=3)
        if not r.ok:
            return False, None
        body = r.text()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" in ctype or body.lstrip().lower().startswith(("<!doctype", "<html")):
            # Some hosts serve robots.txt as text/html; accept it if it looks like the real thing.
            if url.endswith("robots.txt") and re.search(r"^\s*(user-agent|sitemap)\s*:", body, re.I | re.M):
                return True, body
            return False, None
        return True, body
    except PlaywrightError:
        return False, None


def scan_site(url: str, settings: Settings, browser: Browser) -> ScanResult:
    """Read a site the way a polite crawler does, and score it against the checklist."""
    domain = (urlparse(url).hostname or "").removeprefix("www.")
    agent = settings.scanning.user_agent_for(settings.company.website, settings.legal.bot_info_path)
    context = browser.new_context(user_agent=agent, ignore_https_errors=True,
                                  viewport={"width": 1366, "height": 900})
    context.set_default_timeout(settings.scanning.page_timeout_ms)
    policy = CrawlPolicy(settings)
    pages: list[PageSnapshot] = []
    audits: list[PageAudit] = []
    results: list[CheckResult] = []

    def failed(reason: str, robots_txt: str | None = None) -> ScanResult:
        return ScanResult(url, domain, [], [], None, None, {}, robots_txt, None, None, "unknown", [], error=reason)

    try:
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        robots_ok, robots_txt = _fetch_text(context, origin + "/robots.txt", settings.scanning.page_timeout_ms)
        policy.load_robots(origin, robots_txt if robots_ok else None)
        if not policy.allowed(url):
            return failed("robots.txt disallows this crawler; site skipped", robots_txt if robots_ok else None)

        page = context.new_page()
        policy.wait(url)
        home = _load(page, url, settings.scanning.page_timeout_ms)
        if home is None:
            return failed("home page failed to load", robots_txt if robots_ok else None)
        vitals = measure_web_vitals(page)
        pages.append(home)
        audits.append(run_axe(page, home.url))

        origin_now = f"{urlparse(home.url).scheme}://{urlparse(home.url).netloc}"
        if origin_now != origin:  # redirected to another host; re-ask that host's robots.txt
            origin = origin_now
            robots_ok, robots_txt = _fetch_text(context, origin + "/robots.txt", settings.scanning.page_timeout_ms)
            policy.load_robots(origin, robots_txt if robots_ok else None)
        robots = parse_robots(robots_txt if robots_ok else None)
        sitemap_ok, _ = _fetch_text(context, origin + "/sitemap.xml", settings.scanning.page_timeout_ms)
        if not sitemap_ok:
            sitemap_ok, _ = _fetch_text(context, origin + "/sitemap_index.xml", settings.scanning.page_timeout_ms)
        llms_ok, _ = _fetch_text(context, origin + "/llms.txt", settings.scanning.page_timeout_ms)

        links = pick_internal_links(home.url, home.rendered_html, settings.scanning.max_pages_per_site - 1)
        seo_results, facts = audit_page(
            url=home.url, raw_html=home.raw_html, rendered_html=home.rendered_html, is_home=True,
            robots=robots, sitemap_ok=sitemap_ok, llms_txt_ok=llms_ok, vitals=vitals,
            status_code=home.status, internal_link_count=len(links),
        )
        results += seo_results

        broken = 0
        for link in links:
            if not safe_to_fetch(link) or not policy.allowed(link):
                continue
            policy.wait(link)
            snap = _load(page, link, settings.scanning.page_timeout_ms)
            if snap is None:
                broken += 1
                continue
            pages.append(snap)
            audits.append(run_axe(page, snap.url))
            sub_results, _ = audit_page(
                url=snap.url, raw_html=snap.raw_html, rendered_html=snap.rendered_html, is_home=False,
                robots=robots, sitemap_ok=sitemap_ok, llms_txt_ok=llms_ok,
                vitals=measure_web_vitals(page), status_code=snap.status,
            )
            results += sub_results
        results.append(CheckResult("broken-links", "pass" if broken == 0 else "fail", count=broken,
                                   detail=f"{broken} internal link(s) failed to load" if broken else "",
                                   pages=[home.url]))

        results += merge_audits(audits)
        results = _dedupe(results)
        ada_card, seo_card = score(results, "ada"), score(results, "seo")
        disc = discover([(p.url, p.rendered_html) for p in pages], domain, home.headers)
        # Can we actually change this site for them? Decided here, from evidence, so the
        # answer is known before anyone is emailed.
        wp_rest = disc.platform == "wordpress" and wordpress_rest_available(
            lambda u: _fetch_text(context, u, settings.scanning.page_timeout_ms), origin)
        fixability = assess(domain=domain, url=home.url, platform=disc.platform, headers=home.headers,
                            home_html=home.rendered_html, wp_rest=wp_rest)
        return ScanResult(
            url=home.url, domain=domain, pages=pages, results=results, ada=ada_card, seo=seo_card, facts=facts,
            robots_txt=robots_txt if robots_ok else None, contact_email=disc.email,
            contact_source=disc.email_source, platform=disc.platform, all_emails=disc.all_emails,
            fixability=fixability,
        )
    finally:
        context.close()


def _dedupe(results: list[CheckResult]) -> list[CheckResult]:
    """One result per check; the worst status across pages wins."""
    rank = {"fail": 3, "needs_review": 2, "pass": 1, "not_applicable": 0}
    best: dict[str, CheckResult] = {}
    for r in results:
        cur = best.get(r.check_id)
        if cur is None:
            best[r.check_id] = r
        elif rank[r.status] > rank[cur.status]:
            r.pages = list(dict.fromkeys(cur.pages + r.pages))
            best[r.check_id] = r
        elif r.status == cur.status:
            cur.count += r.count
            cur.pages = list(dict.fromkeys(cur.pages + r.pages))
            cur.evidence.extend(r.evidence)
            cur.detail = cur.detail or r.detail
    return list(best.values())


def _load(page: Any, url: str, timeout_ms: int) -> PageSnapshot | None:
    import time

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
    raw_html, headers, status = "", {}, None
    if resp is not None:
        status = resp.status
        headers = {k.lower(): v for k, v in resp.headers.items()}
        try:
            raw_html = resp.text()
        except PlaywrightError:
            raw_html = ""
    if status is not None and status >= 400:
        return None
    return PageSnapshot(url=page.url, status=status, raw_html=raw_html, rendered_html=page.content(),
                        title=page.title(), load_ms=load_ms, headers=headers)


# ------------------------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------------------------

def snapshot_dir(settings: Settings, domain: str) -> Path:
    d = settings.workdir / "snapshots" / domain
    d.mkdir(parents=True, exist_ok=True)
    return d


def persist_scan(db: Database, settings: Settings, lead: dict[str, Any], result: ScanResult,
                 kind: str = "baseline") -> int:
    if result.error:
        scan_id = db.insert("scans", {"lead_id": lead["id"], "kind": kind, "status": "failed",
                                      "checklist_version": CHECKLIST_VERSION,
                                      "error": result.error, "created_at": utcnow()})
        db.log_event("scan_failed", lead["id"], error=result.error)
        return scan_id

    assert result.ada and result.seo
    exposure = compute_exposure(ada_score=result.ada.percent, aiseo_score=result.seo.percent,
                                region=lead.get("region"), category=lead.get("category"),
                                critical_count=result.critical_count)
    snap_dir = snapshot_dir(settings, lead["domain"])
    page_index = []
    for p in result.pages:
        h = hashlib.sha1(p.url.encode()).hexdigest()[:12]
        (snap_dir / f"{h}.raw.html").write_text(p.raw_html, encoding="utf-8")
        (snap_dir / f"{h}.rendered.html").write_text(p.rendered_html, encoding="utf-8")
        page_index.append({"url": p.url, "status": p.status, "title": p.title, "load_ms": p.load_ms, "snapshot": h})
    if result.robots_txt is not None:
        (snap_dir / "robots.txt").write_text(result.robots_txt, encoding="utf-8")

    ada_summary = {**result.ada.as_dict(), "score": result.ada.percent}
    seo_summary = {**result.seo.as_dict(), "score": result.seo.percent, "facts": result.facts}
    scan_id = db.insert("scans", {
        "lead_id": lead["id"], "kind": kind, "status": "ok",
        "ada_score": result.ada.percent, "aiseo_score": result.seo.percent,
        "ada_summary": ada_summary, "aiseo_summary": seo_summary,
        "pages": page_index, "exposure": exposure, "checklist_version": CHECKLIST_VERSION,
        "created_at": utcnow(),
    })
    for r in result.results:
        c = r.check
        db.insert("findings", {
            "scan_id": scan_id, "kind": c.area, "rule_id": r.check_id,
            "impact": "critical" if c.weight >= 9 else "serious" if c.weight >= 6 else
                      "moderate" if c.weight >= 4 else "minor",
            "description": c.title, "help_url": None,
            "page_url": (r.pages or [result.url])[0], "count": r.count,
            "sample": {"status": r.status, "detail": r.detail, "weight": c.weight,
                       "standard": c.standard, "auto_fixable": c.auto_fixable,
                       "evidence": r.evidence[:3]},
        })

    if kind == "baseline":
        updates: dict[str, Any] = {"platform": result.platform}
        if result.fixability:
            updates["fixability"] = result.fixability.tier
            updates["fix_channel"] = result.fixability.channel
            updates["fix_detail"] = result.fixability.detail
            if result.fixability.repo:
                updates["repo"] = result.fixability.repo
                # The fixer reads the repository from here, so a repo we worked out during
                # the scan means the customer is never asked for it.
                db.set_kv(f"lead:{lead['id']}:github_repo", result.fixability.repo)
        if result.contact_email and not lead.get("contact_email"):
            updates["contact_email"] = result.contact_email
            updates["contact_source"] = result.contact_source
        if not lead.get("business_name") and result.pages:
            updates["business_name"] = _guess_name(result.pages[0].title, lead["domain"])
        db.update("leads", lead["id"], **updates)
    db.log_event("scan_done", lead["id"], scan_id=scan_id, ada=result.ada.percent,
                 aiseo=result.seo.percent, pages=len(result.pages), scan_kind=kind,
                 **headline(result.ada, result.seo))
    return scan_id


def _guess_name(title: str, domain: str) -> str:
    t = re.split(r"\s[|\-–—:]\s", title or "")[0].strip()
    if 2 <= len(t) <= 60 and t.lower() not in ("home", "welcome", "homepage"):
        return t
    return domain.split(".")[0].replace("-", " ").title()


def classify_after_scan(db: Database, settings: Settings, lead_id: int, scan_id: int,
                        page_text: str = "") -> str:
    """Decide the lead's next status from the scan."""
    scan = db.one("SELECT * FROM scans WHERE id = ?", (scan_id,))
    lead = db.get_lead(lead_id)
    assert scan and lead
    if scan["status"] != "ok":
        db.set_lead_status(lead_id, LeadStatus.ARCHIVED, "scan failed")
        return LeadStatus.ARCHIVED
    eligible = check_lead(lead, settings, page_text)
    if not eligible.ok:
        db.set_lead_status(lead_id, LeadStatus.EXCLUDED, eligible.reason)
        db.log_event("excluded", lead_id, reason=eligible.reason)
        return LeadStatus.EXCLUDED
    # Only pitch a site we could genuinely change once they say yes.
    ok, why = eligible_to_pitch(
        Fixability(lead.get("fixability") or "unknown", lead.get("fix_channel") or "none",
                   lead.get("fix_detail") or ""),
        settings.prospecting.require_fixable)
    if not ok:
        db.set_lead_status(lead_id, LeadStatus.NOT_FIXABLE, why)
        db.log_event("not_fixable", lead_id, reason=why, channel=lead.get("fix_channel"))
        return LeadStatus.NOT_FIXABLE
    if (scan["ada_score"] or 0) >= settings.pricing.clean_ada_percent and \
       (scan["aiseo_score"] or 0) >= settings.pricing.clean_seo_percent:
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
