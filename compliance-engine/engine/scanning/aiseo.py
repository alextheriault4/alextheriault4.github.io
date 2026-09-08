"""Search and AI-discoverability detection.

Answers one question per check: can a search engine or an AI assistant reach this page,
read it, work out what the business is, and quote it accurately? Results are keyed to the
checklist in ``engine/standards/checks.py``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from playwright.sync_api import Page

from ..standards import CheckResult

AI_CRAWLERS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "Claude-Web",
               "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot", "Amazonbot", "Bytespider",
               "meta-externalagent"]
SEARCH_CRAWLERS = ["Googlebot", "Bingbot", "DuckDuckBot"]

BUSINESS_TYPES = {
    "LocalBusiness", "Organization", "Store", "Restaurant", "Dentist", "MedicalBusiness", "LegalService",
    "Attorney", "HomeAndConstructionBusiness", "Plumber", "Electrician", "HVACBusiness", "AutoRepair",
    "BeautySalon", "HairSalon", "HealthAndBeautyBusiness", "ProfessionalService", "FinancialService",
    "AccountingService", "RealEstateAgent", "VeterinaryCare", "Physician", "FoodEstablishment",
    "ExerciseGym", "Florist", "Hotel", "LodgingBusiness", "RoofingContractor", "Locksmith",
    "InsuranceAgency", "ChildCare", "Bakery", "CafeOrCoffeeShop", "BarOrPub", "NailSalon", "DaySpa",
}

PHONE_RE = re.compile(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}")
ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.'\- ]{2,40}\s(St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|"
    r"Way|Ct|Court|Pl|Place|Hwy|Highway|Pkwy|Parkway|Suite|Ste|Unit)\b", re.I)

WEB_VITALS_JS = r"""() => new Promise(resolve => {
  const out = { lcp: null, cls: 0 };
  try {
    new PerformanceObserver(list => {
      const entries = list.getEntries();
      if (entries.length) out.lcp = entries[entries.length - 1].startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) if (!e.hadRecentInput) out.cls += e.value;
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}
  setTimeout(() => {
    if (out.lcp === null) {
      const nav = performance.getEntriesByType('navigation')[0];
      out.lcp = nav ? nav.domContentLoadedEventEnd : null;
    }
    const res = performance.getEntriesByType('resource');
    out.transferBytes = res.reduce((n, r) => n + (r.transferSize || 0), 0);
    out.requestCount = res.length;
    resolve(out);
  }, 1200);
})"""


def measure_web_vitals(page: Page) -> dict[str, Any]:
    try:
        return page.evaluate(WEB_VITALS_JS)
    except Exception:  # noqa: BLE001 - a missing metric must never fail a scan
        return {"lcp": None, "cls": 0, "transferBytes": 0, "requestCount": 0}


def parse_robots(robots_txt: str | None) -> dict[str, Any]:
    """What robots.txt actually permits, decided by a real parser rather than by eye.

    Group precedence matters here: a wildcard ``Disallow: /`` followed by a specific
    ``Allow`` for Googlebot does not block Googlebot, and hand-rolled line scanning gets
    that wrong in both directions.
    """
    if robots_txt is None:
        return {"exists": False, "blocked_ai": [], "blocked_search": [], "blocks_all": False, "sitemaps": []}
    parser = RobotFileParser()
    try:
        parser.parse(robots_txt.splitlines())
    except Exception:  # noqa: BLE001 - malformed robots.txt is a finding, not a crash
        return {"exists": True, "blocked_ai": [], "blocked_search": [], "blocks_all": False,
                "sitemaps": [], "malformed": True}

    def blocked(agent: str) -> bool:
        try:
            return not parser.can_fetch(agent, "/")
        except Exception:  # noqa: BLE001
            return False

    sitemaps = [line.split(":", 1)[1].strip() for line in robots_txt.splitlines()
                if line.strip().lower().startswith("sitemap:")]
    return {
        "exists": True,
        "blocked_ai": [a for a in AI_CRAWLERS if blocked(a)],
        "blocked_search": [a for a in SEARCH_CRAWLERS if blocked(a)],
        "blocks_all": blocked("*") and blocked("Googlebot"),
        "sitemaps": sitemaps,
    }


def extract_jsonld(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], int]:
    """Parsed JSON-LD blocks, and how many failed to parse."""
    out: list[dict[str, Any]] = []
    broken = 0
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            if raw.strip():
                broken += 1
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                if isinstance(it.get("@graph"), list):
                    out.extend(x for x in it["@graph"] if isinstance(x, dict))
                else:
                    out.append(it)
    return out, broken


def _types(items: list[dict[str, Any]]) -> set[str]:
    types: set[str] = set()
    for it in items:
        t = it.get("@type")
        if isinstance(t, list):
            types.update(str(x) for x in t)
        elif t:
            types.add(str(t))
    return types


def _find(items: list[dict[str, Any]], *keys: str) -> bool:
    """Whether any business-type node carries one of these properties."""
    for it in items:
        t = it.get("@type")
        t_set = {str(x) for x in (t if isinstance(t, list) else [t])} if t else set()
        if t_set & BUSINESS_TYPES and any(it.get(k) for k in keys):
            return True
    return False


def audit_page(*, url: str, raw_html: str, rendered_html: str, is_home: bool, robots: dict[str, Any],
               sitemap_ok: bool, llms_txt_ok: bool, vitals: dict[str, Any], status_code: int | None,
               internal_link_count: int = 0) -> tuple[list[CheckResult], dict[str, Any]]:
    soup = BeautifulSoup(rendered_html, "lxml")
    raw_soup = BeautifulSoup(raw_html or "", "lxml")
    results: list[CheckResult] = []

    def add(check_id: str, ok: bool | None, detail: str = "", count: int = 0,
            evidence: list[dict[str, Any]] | None = None) -> None:
        status = "needs_review" if ok is None else ("pass" if ok else "fail")
        results.append(CheckResult(check_id, status, count=count, detail=detail,
                                   pages=[url], evidence=evidence or []))

    # ------------------------------------------------------------ crawlability
    if is_home:
        add("robots-exists", robots["exists"],
            "" if robots["exists"] else "no robots.txt at the site root")
        if robots["exists"]:
            add("crawlers-allowed", not (robots["blocks_all"] or robots["blocked_search"]),
                f"robots.txt blocks {', '.join(robots['blocked_search']) or 'all crawlers'}"
                if (robots["blocks_all"] or robots["blocked_search"]) else "")
            add("ai-crawlers-allowed", not robots["blocked_ai"],
                f"robots.txt blocks {', '.join(robots['blocked_ai'])}" if robots["blocked_ai"] else "",
                count=len(robots["blocked_ai"]))
        else:
            # No robots.txt means nothing is blocked; that part is fine.
            add("crawlers-allowed", True)
            add("ai-crawlers-allowed", True)
        add("sitemap", sitemap_ok or bool(robots["sitemaps"]),
            "" if (sitemap_ok or robots["sitemaps"]) else "no sitemap.xml, and none referenced in robots.txt")
        add("llms-txt", llms_txt_ok, "" if llms_txt_ok else "no /llms.txt summary for AI assistants")

    robots_meta = " ".join(
        (m.get("content") or "") for m in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)})
    ).lower()
    add("indexable", "noindex" not in robots_meta,
        "the page carries a noindex directive" if "noindex" in robots_meta else "")
    add("no-ai-blocking-meta", not re.search(r"nosnippet|noarchive|noai|noimageai", robots_meta),
        "meta robots blocks snippets or AI use" if re.search(r"nosnippet|noarchive|noai|noimageai", robots_meta) else "")
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        add("https", None, "local address; HTTPS not assessable")  # never penalise a dev server
        results[-1].status = "not_applicable"
    else:
        add("https", url.lower().startswith("https://"),
            "" if url.lower().startswith("https://") else "served over plain HTTP")

    canonical = soup.find("link", attrs={"rel": lambda v: v and "canonical" in
                                         [x.lower() for x in (v if isinstance(v, list) else [v])]})
    add("canonical", canonical is not None, "" if canonical else "no canonical URL declared")

    # ---------------------------------------------------------- structured data
    jsonld, broken = extract_jsonld(soup)
    types = _types(jsonld)
    if is_home:
        has_business = bool(types & BUSINESS_TYPES)
        add("structured-data", has_business,
            "" if has_business else ("structured data exists but none of it describes the business"
                                     if jsonld else "no structured data at all"),
            evidence=[{"types": sorted(types)}] if types else [])
        add("structured-data-valid", broken == 0 and (bool(jsonld) or not has_business),
            f"{broken} JSON-LD block(s) failed to parse" if broken else "", count=broken)
        # Structured contact details can only exist if the business publishes contact
        # details at all. When it doesn't, that single missing fact is reported once, by
        # nap-visible, rather than counted twice.
        page_text_now = soup.get_text(" ", strip=True)
        publishes_contact = bool(PHONE_RE.search(page_text_now) or ADDRESS_RE.search(page_text_now))
        if publishes_contact:
            has_nap = _find(jsonld, "address") and _find(jsonld, "telephone")
            add("nap-structured", has_nap,
                "" if has_nap else "the phone and address on the page are not in the structured data")
        else:
            add("nap-structured", None, "no contact details published anywhere to mark up")
            results[-1].status = "not_applicable"
        add("opening-hours", _find(jsonld, "openingHoursSpecification", "openingHours"),
            "" if _find(jsonld, "openingHoursSpecification", "openingHours") else "opening hours are not machine readable")
        add("social-profiles", _find(jsonld, "sameAs"),
            "" if _find(jsonld, "sameAs") else "no sameAs links to the business's other profiles")
        add("faq-schema", "FAQPage" in types, "" if "FAQPage" in types else "no FAQ markup")
    if not is_home:
        add("breadcrumbs", "BreadcrumbList" in types,
            "" if "BreadcrumbList" in types else "no breadcrumb structured data on an inner page")

    # ------------------------------------------------------------------ content
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    good_title = bool(title) and 15 <= len(title) <= 70 and title.lower() not in ("home", "homepage", "welcome", "index")
    add("title-tag", good_title,
        ("no title tag" if not title else f"title is {len(title)} characters ('{title[:40]}')") if not good_title else "",
        evidence=[{"title": title}])

    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc = (md.get("content") or "").strip() if md else ""
    add("meta-description", bool(desc) and 50 <= len(desc) <= 320,
        "no meta description" if not desc else (f"description is {len(desc)} characters" if not (50 <= len(desc) <= 320) else ""))

    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    add("h1", len(h1s) == 1, "no H1 heading" if not h1s else (f"{len(h1s)} H1 headings" if len(h1s) > 1 else ""),
        count=len(h1s))

    if is_home:  # the page people actually share
        og = soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}) is not None
        add("open-graph", og, "" if og else "no Open Graph tags for link previews")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    words = len(re.findall(r"\w+", text))
    add("content-depth", words >= 250 if is_home else words >= 120,
        f"only {words} words of readable text" if (words < (250 if is_home else 120)) else "", count=words)

    phone = bool(PHONE_RE.search(text))
    address = bool(ADDRESS_RE.search(text))
    add("nap-visible", phone and address,
        "" if (phone and address) else
        f"{'phone' if not phone else ''}{' and ' if not phone and not address else ''}{'address' if not address else ''} not in the page text")

    path = urlparse(url).path or "/"
    add("descriptive-urls", bool(re.fullmatch(r"[a-z0-9/_.\-]*", path.lower())) and "?" not in url,
        f"URL path is not readable: {path}" if not re.fullmatch(r"[a-z0-9/_.\-]*", path.lower()) else "")

    if is_home:
        add("internal-links", internal_link_count >= 2,
            f"only {internal_link_count} internal link(s) from the home page" if internal_link_count < 2 else "",
            count=internal_link_count)

    # -------------------------------------------------------------- performance
    lcp = vitals.get("lcp")
    if lcp is not None:
        add("lcp", lcp <= 2500, f"largest content painted at {int(lcp)}ms" if lcp > 2500 else "", count=int(lcp))
    cls = float(vitals.get("cls") or 0)
    add("cls", cls <= 0.1, f"layout shift score {cls:.2f}" if cls > 0.1 else "")
    transfer = int(vitals.get("transferBytes") or 0)
    if transfer:
        add("page-weight", transfer <= 3_000_000,
            f"{transfer / 1_000_000:.1f} MB transferred" if transfer > 3_000_000 else "", count=transfer)

    viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    add("mobile-friendly", viewport is not None, "" if viewport else "no mobile viewport meta tag")

    imgs = soup.find_all("img")
    if imgs:
        sized = sum(1 for i in imgs if i.get("width") and i.get("height"))
        lazy = sum(1 for i in imgs if (i.get("loading") or "").lower() == "lazy")
        add("image-optimisation", sized >= len(imgs) * 0.6 or lazy >= len(imgs) * 0.5,
            f"{len(imgs) - sized} image(s) have no width/height and {len(imgs) - lazy} are not lazy-loaded"
            if not (sized >= len(imgs) * 0.6 or lazy >= len(imgs) * 0.5) else "", count=len(imgs))

    # ------------------------------------------------------------- ai readiness
    for tag in raw_soup(["script", "style", "noscript"]):
        tag.decompose()
    raw_words = len(re.findall(r"\w+", raw_soup.get_text(" ", strip=True)))
    if words >= 100:
        add("server-rendered", raw_words >= 0.4 * words,
            f"only {raw_words} of {words} words exist before JavaScript runs" if raw_words < 0.4 * words else "",
            count=raw_words)

    lowered = text.lower()
    # Whether the business is legible to an assistant is a property of the site as a whole,
    # judged on the page it would actually land on. An inner page like an accessibility
    # statement is not supposed to restate the trade and the opening hours.
    signals = 0 if not is_home else sum([
        bool(re.search(r"\b(we|our team|family[- ]owned|established|since \d{4})\b", lowered)),
        bool(re.search(r"\b(services?|we offer|we provide|specializ|special is)\b", lowered)),
        bool(re.search(r"\b(serving|based in|located in|area|county|neighborhood|neighbourhood)\b", lowered)),
        bool(re.search(r"\b(hours|open|monday|tuesday|appointment|walk[- ]in)\b", lowered)),
        bool(re.search(r"\?", text)),  # question-and-answer style content
    ])
    if is_home:
        add("answer-ready-content", signals >= 3,
            f"the home page states only {signals} of 5 basic facts an assistant needs" if signals < 3 else "",
            count=signals)

    if is_home:
        has_trade = bool(re.search(r"\b(dentist|plumb|electric|roof|salon|clinic|law|attorney|restaurant|cafe|"
                                   r"bakery|garage|mechanic|vet|gym|spa|contractor|landscap|clean|hvac|"
                                   r"chiropract|accountant|insurance|realtor|florist)\w*\b", lowered))
        has_place = bool(re.search(r"\b(in|near|serving|around)\s+[A-Z][a-z]+", text))
        add("entity-clarity", has_trade and has_place,
            "" if (has_trade and has_place) else "the trade and the town are not both stated in plain text")

    year = datetime.now(timezone.utc).year
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(\d{4})", text, re.I)]
    if years:
        add("freshness", max(years) >= year - 1,
            f"the footer still says {max(years)}" if max(years) < year - 1 else "", count=max(years))

    facts = {
        "title": title, "meta_description": desc, "h1": h1s[:3], "jsonld_types": sorted(types),
        "word_count": words, "raw_word_count": raw_words, "phone_found": phone, "address_found": address,
        "lcp_ms": int(lcp) if lcp else None, "cls": round(cls, 3), "transfer_bytes": transfer,
        "robots": robots, "sitemap_ok": sitemap_ok, "llms_txt_ok": llms_txt_ok, "status_code": status_code,
        "text_sample": text[:20_000],
    }
    return results, facts
