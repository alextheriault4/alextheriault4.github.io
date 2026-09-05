"""AI-search readiness audit.

"AI SEO" here means: can ChatGPT, Claude, Perplexity, Google's AI answers and the
like actually find, read, and confidently describe this business? The checks are
concrete and fixable: crawler access, machine-readable business facts (JSON-LD),
llms.txt, sitemap, real server-rendered text, sane titles and descriptions.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .ada import Finding

AI_CRAWLERS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "anthropic-ai", "Claude-Web",
               "PerplexityBot", "Google-Extended", "Bingbot", "Applebot-Extended", "CCBot", "Amazonbot", "Bytespider"]

WEIGHTS = {"critical": 14, "serious": 8, "moderate": 4, "minor": 2}

PLAIN: dict[str, str] = {
    "robots-missing": "there's no robots.txt, so crawlers have to guess what they may index",
    "ai-crawlers-blocked": "robots.txt blocks AI assistants' crawlers, so they can't learn about the business",
    "all-crawlers-blocked": "robots.txt blocks all crawlers, so the site is invisible to search and AI",
    "sitemap-missing": "there's no sitemap, so crawlers may miss pages",
    "llms-txt-missing": "there's no llms.txt summary for AI assistants",
    "structured-data-missing": "the site has no structured data telling AI assistants what the business is, where it is, and how to contact it",
    "structured-data-no-localbusiness": "structured data exists but doesn't describe the business itself (no LocalBusiness/Organization)",
    "faq-schema-missing": "no FAQ markup, so AI answers can't quote the business's own answers",
    "title-missing": "the home page has no title",
    "title-weak": "the home page title is too short, too long, or doesn't say what or where the business is",
    "meta-description-missing": "there's no meta description for search and AI summaries to use",
    "meta-description-weak": "the meta description is too short or too long",
    "h1-missing": "the home page has no H1 heading",
    "h1-multiple": "the home page has several H1 headings, which muddies the topic",
    "canonical-missing": "no canonical URL, so duplicates split ranking signals",
    "og-missing": "no Open Graph tags, so shared links render with no preview",
    "not-https": "the site isn't served over HTTPS",
    "viewport-missing": "the page isn't mobile-friendly (no viewport meta)",
    "thin-content": "the home page has very little readable text for crawlers to work with",
    "js-only-content": "most of the page text only exists after JavaScript runs, which many AI crawlers don't execute",
    "no-nap": "the business phone or address isn't in the page text where crawlers can read it",
    "slow-load": "the page takes a long time to load",
    "lang-missing": "the page doesn't declare its language",
}


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def parse_robots(robots_txt: str | None) -> dict[str, Any]:
    if robots_txt is None:
        return {"exists": False, "blocked_ai": [], "blocks_all": False, "sitemaps": []}
    blocked_ai: list[str] = []
    blocks_all = False
    sitemaps: list[str] = []
    current_agents: list[str] = []
    for raw in robots_txt.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = [s.strip() for s in line.split(":", 1)]
        k = key.lower()
        if k == "user-agent":
            current_agents.append(val)
        elif k == "disallow":
            if val == "/":
                for a in current_agents:
                    if a == "*":
                        blocks_all = True
                    for ai in AI_CRAWLERS:
                        if a.lower() == ai.lower() and ai not in blocked_ai:
                            blocked_ai.append(ai)
        elif k == "sitemap":
            sitemaps.append(val)
        elif k == "allow":
            pass
        if k not in ("user-agent",):
            # a blank-line-separated group ends when a new user-agent starts; approximate by resetting on Sitemap
            if k == "sitemap":
                current_agents = []
    return {"exists": True, "blocked_ai": blocked_ai, "blocks_all": blocks_all, "sitemaps": sitemaps}


def extract_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                if "@graph" in it and isinstance(it["@graph"], list):
                    out.extend(x for x in it["@graph"] if isinstance(x, dict))
                else:
                    out.append(it)
    return out


def _types(items: list[dict[str, Any]]) -> set[str]:
    types: set[str] = set()
    for it in items:
        t = it.get("@type")
        if isinstance(t, list):
            types.update(str(x) for x in t)
        elif t:
            types.add(str(t))
    return types


BUSINESS_TYPES = {"LocalBusiness", "Organization", "Store", "Restaurant", "Dentist", "MedicalBusiness", "LegalService",
                  "Attorney", "HomeAndConstructionBusiness", "Plumber", "Electrician", "HVACBusiness", "AutoRepair",
                  "BeautySalon", "HairSalon", "HealthAndBeautyBusiness", "ProfessionalService", "FinancialService",
                  "AccountingService", "RealEstateAgent", "VeterinaryCare", "Physician", "FoodEstablishment",
                  "ExerciseGym", "Florist", "Hotel", "LodgingBusiness", "RoofingContractor", "Locksmith", "InsuranceAgency"}


def audit_home(
    *, url: str, raw_html: str, rendered_html: str, robots_txt: str | None, sitemap_ok: bool, llms_txt_ok: bool,
    load_ms: int | None,
) -> tuple[list[Finding], dict[str, Any]]:
    soup = BeautifulSoup(rendered_html, "lxml")
    raw_soup = BeautifulSoup(raw_html, "lxml")
    findings: list[Finding] = []

    def add(rule: str, impact: str, **extra: Any) -> None:
        findings.append(Finding("aiseo", rule, impact, PLAIN[rule], url, sample=[extra] if extra else []))

    robots = parse_robots(robots_txt)
    if not robots["exists"]:
        add("robots-missing", "moderate")
    elif robots["blocks_all"]:
        add("all-crawlers-blocked", "critical")
    elif robots["blocked_ai"]:
        add("ai-crawlers-blocked", "serious", blocked=robots["blocked_ai"])
    if not sitemap_ok and not robots["sitemaps"]:
        add("sitemap-missing", "moderate")
    if not llms_txt_ok:
        add("llms-txt-missing", "moderate")

    jsonld = extract_jsonld(soup)
    types = _types(jsonld)
    if not jsonld:
        add("structured-data-missing", "serious")
    elif not (types & BUSINESS_TYPES):
        add("structured-data-no-localbusiness", "serious", types=sorted(types))
    if "FAQPage" not in types:
        add("faq-schema-missing", "minor")

    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    if not title:
        add("title-missing", "serious")
    elif len(title) < 15 or len(title) > 70 or title.lower() in ("home", "homepage", "welcome", "index"):
        add("title-weak", "moderate", title=title)

    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc = (md.get("content") or "").strip() if md else ""
    if not desc:
        add("meta-description-missing", "serious")
    elif len(desc) < 50 or len(desc) > 320:
        add("meta-description-weak", "minor", length=len(desc))

    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    if not h1s:
        add("h1-missing", "moderate")
    elif len(h1s) > 1:
        add("h1-multiple", "minor", count=len(h1s))

    if not soup.find("link", attrs={"rel": lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])]}):
        add("canonical-missing", "minor")
    if not soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}):
        add("og-missing", "minor")
    if not url.lower().startswith("https://"):
        add("not-https", "serious")
    if not soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}):
        add("viewport-missing", "moderate")
    html_tag = soup.find("html")
    if html_tag is None or not (html_tag.get("lang") or "").strip():
        add("lang-missing", "minor")

    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    rendered_text = soup.get_text(" ", strip=True)
    for s in raw_soup(["script", "style", "noscript"]):
        s.decompose()
    raw_text = raw_soup.get_text(" ", strip=True)
    rw, rr = _word_count(raw_text), _word_count(rendered_text)
    if rr < 150:
        add("thin-content", "moderate", words=rr)
    if rr >= 150 and rw < 0.3 * rr:
        add("js-only-content", "serious", raw_words=rw, rendered_words=rr)

    phone = re.search(r"(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}", rendered_text)
    address = re.search(r"\b\d{1,6}\s+[A-Za-z0-9.'\- ]{2,40}\s(St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Way|Ct|Court|Pl|Place|Hwy|Highway|Pkwy|Parkway|Suite|Ste)\b", rendered_text)
    if not phone and not address:
        add("no-nap", "moderate")

    if load_ms is not None and load_ms > 5000:
        add("slow-load", "moderate", load_ms=load_ms)

    facts = {
        "title": title, "meta_description": desc, "h1": h1s[:3], "jsonld_types": sorted(types),
        "robots": robots, "sitemap_ok": sitemap_ok, "llms_txt_ok": llms_txt_ok, "word_count": rr, "raw_word_count": rw,
        "phone_found": bool(phone), "address_found": bool(address), "load_ms": load_ms,
    }
    return findings, facts


def aiseo_score(findings: list[Finding]) -> int:
    penalty = sum(WEIGHTS.get(f.impact, 2) for f in findings if f.kind == "aiseo")
    return max(0, int(round(100 - penalty)))
