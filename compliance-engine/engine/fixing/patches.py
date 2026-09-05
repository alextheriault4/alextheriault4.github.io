"""Deterministic HTML remediation.

Every transform is keyed to a finding the scan produced, so the client can see exactly
which reported issue each change resolves. Nothing here is an "overlay": the source
markup is changed. Model calls are limited to writing words (alt text, meta copy, the
business description) - the structure is code.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

from .. import schemas
from ..llm import LLM

ICON_CLASS = re.compile(r"(icon|fa-|glyph|svg|material)", re.I)


@dataclass
class Change:
    rule_id: str
    description: str
    count: int = 1


@dataclass
class PatchResult:
    html: str
    changes: list[Change] = field(default_factory=list)

    def add(self, rule_id: str, description: str, count: int = 1) -> None:
        if count:
            self.changes.append(Change(rule_id, description, count))


def _src_key(img: Tag) -> str:
    return (img.get("src") or img.get("data-src") or "").strip()


def patch_page(html: str, *, page_url: str, is_home: bool, lang: str, meta: schemas.MetaCopy | None,
               profile: schemas.BusinessProfile | None, alt_text: dict[str, str], canonical_url: str | None,
               site_name: str) -> PatchResult:
    soup = BeautifulSoup(html, "lxml")
    res = PatchResult(html="")
    head = soup.head or soup.new_tag("head")
    if not soup.head:
        (soup.html or soup).insert(0, head)

    # -- language / charset / viewport / title -------------------------------------
    html_tag = soup.find("html")
    if html_tag is not None and not (html_tag.get("lang") or "").strip():
        html_tag["lang"] = lang
        res.add("html-has-lang", f"Declared page language as '{lang}'")
    if not head.find("meta", attrs={"charset": True}):
        head.insert(0, soup.new_tag("meta", charset="utf-8"))
    vp = head.find("meta", attrs={"name": re.compile("^viewport$", re.I)})
    if vp is None:
        head.append(soup.new_tag("meta", attrs={"name": "viewport", "content": "width=device-width, initial-scale=1"}))
        res.add("viewport-missing", "Added a mobile viewport meta tag")
    elif re.search(r"user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b", vp.get("content") or "", re.I):
        vp["content"] = "width=device-width, initial-scale=1"
        res.add("meta-viewport", "Re-enabled pinch zoom in the viewport meta tag")
    title = soup.title
    if meta and is_home:
        if title is None:
            title = soup.new_tag("title")
            head.insert(0, title)
            res.add("document-title", "Added a page title")
        elif (title.string or "").strip().lower() in ("", "home", "homepage", "welcome", "index") or len((title.string or "")) < 15:
            res.add("title-weak", f"Rewrote the weak title '{(title.string or '').strip()}'")
        else:
            title = None
        if title is not None:
            title.string = meta.title
        if not head.find("meta", attrs={"name": re.compile("^description$", re.I)}):
            head.append(soup.new_tag("meta", attrs={"name": "description", "content": meta.description}))
            res.add("meta-description-missing", "Added a meta description")
        if not head.find("meta", attrs={"property": re.compile("^og:", re.I)}):
            for prop, val in (("og:title", meta.title), ("og:description", meta.description), ("og:type", "website"),
                              ("og:url", canonical_url or page_url), ("og:site_name", site_name)):
                head.append(soup.new_tag("meta", attrs={"property": prop, "content": val}))
            res.add("og-missing", "Added Open Graph tags")
    elif title is None:
        t = soup.new_tag("title")
        t.string = site_name
        head.insert(0, t)
        res.add("document-title", "Added a page title")
    if canonical_url and not head.find("link", attrs={"rel": lambda v: v and "canonical" in (v if isinstance(v, list) else [v])}):
        head.append(soup.new_tag("link", attrs={"rel": "canonical", "href": canonical_url}))
        res.add("canonical-missing", "Added a canonical link")

    # -- structured data -----------------------------------------------------------
    if profile and is_home and not soup.find("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        head.append(_jsonld_tag(soup, profile, canonical_url or page_url))
        res.add("structured-data-missing", f"Added schema.org {profile.business_type} structured data")
        if profile.faq:
            head.append(_faq_tag(soup, profile))
            res.add("faq-schema-missing", f"Added FAQPage structured data with {len(profile.faq)} questions")

    # -- images ----------------------------------------------------------------
    n = 0
    for img in soup.find_all("img"):
        if img.has_attr("alt"):
            continue
        key = _src_key(img)
        alt = alt_text.get(key)
        if alt is None:
            alt = alt_text.get(key.rsplit("/", 1)[-1], "")
        if img.get("role") == "presentation" or (img.parent and img.parent.name == "a" and not alt):
            # A logo link with no text: give it the site name so the link has a name.
            if img.parent and img.parent.name == "a" and not img.parent.get_text(strip=True):
                alt = alt or site_name
        img["alt"] = alt
        n += 1
    res.add("image-alt", "Added alt text to images", n)
    for inp in soup.find_all("input", attrs={"type": re.compile("^image$", re.I)}):
        if not inp.get("alt"):
            inp["alt"] = inp.get("value") or "Submit"
            res.add("input-image-alt", "Added alt text to an image button")

    # -- links and buttons with no accessible name --------------------------
    n = 0
    for a in soup.find_all("a", href=True):
        if a.get("aria-label") or a.get_text(strip=True) or a.find("img", alt=True):
            continue
        label = _label_from_href(a["href"])
        if label:
            a["aria-label"] = label
            n += 1
    res.add("link-name", "Added accessible names to icon-only links", n)
    n = 0
    for b in soup.find_all("button"):
        if b.get("aria-label") or b.get_text(strip=True) or b.get("title"):
            continue
        cls = " ".join(b.get("class") or [])
        guess = "Submit" if (b.get("type") or "submit").lower() == "submit" and b.find_parent("form") else None
        if not guess:
            for word, lab in (("search", "Search"), ("menu", "Open menu"), ("close", "Close"), ("send", "Send"),
                              ("next", "Next"), ("prev", "Previous"), ("play", "Play"), ("cart", "Cart")):
                if word in cls.lower() or word in " ".join(i.get("class", []) for i in b.find_all("i")).lower():
                    guess = lab
                    break
        b["aria-label"] = guess or "Button"
        n += 1
    res.add("button-name", "Added accessible names to icon-only buttons", n)

    # -- form labels --------------------------------------------------------
    n = 0
    for field_ in soup.find_all(["input", "select", "textarea"]):
        t = (field_.get("type") or "text").lower()
        if t in ("hidden", "submit", "button", "image", "reset"):
            continue
        fid = field_.get("id")
        if fid and soup.find("label", attrs={"for": fid}):
            continue
        if field_.get("aria-label") or field_.get("aria-labelledby") or field_.find_parent("label"):
            continue
        label = field_.get("placeholder") or field_.get("name") or field_.get("title") or t
        field_["aria-label"] = str(label).replace("_", " ").replace("-", " ").strip().capitalize()
        n += 1
    res.add("label", "Added labels to unlabeled form fields", n)

    # -- frames ---------------------------------------------------------------
    n = 0
    for fr in soup.find_all("iframe"):
        if not fr.get("title"):
            src = fr.get("src") or ""
            fr["title"] = "Map" if "map" in src else "Video" if re.search(r"youtube|vimeo", src) else "Embedded content"
            n += 1
    res.add("frame-title", "Added titles to embedded frames", n)

    # -- landmarks, skip link, headings ------------------------------------------
    body = soup.body
    if body is not None:
        main = soup.find("main") or soup.find(attrs={"role": "main"})
        if main is None:
            main = _wrap_main(soup, body)
            if main is not None:
                res.add("landmark-one-main", "Wrapped page content in a <main> landmark")
        if main is not None and not main.get("id"):
            main["id"] = "main-content"
        links = body.find_all("a", href=True)
        has_skip = any(re.search(r"skip", a.get_text() or "", re.I) and (a.get("href") or "").startswith("#") for a in links)
        if not has_skip and len(links) > 15 and main is not None:
            skip = soup.new_tag("a", href=f"#{main.get('id')}", attrs={"class": "ce-skip-link"})
            skip.string = "Skip to main content"
            body.insert(0, skip)
            res.add("skip-link", "Added a 'skip to main content' link")
        if not soup.find("h1"):
            cand = soup.find(re.compile("^h[2-6]$"))
            if cand is not None:
                cand.name = "h1"
                res.add("h1-missing", f"Promoted '{cand.get_text(strip=True)[:40]}' to the page's H1")
        n = 0
        for h in soup.find_all(re.compile("^h[1-6]$")):
            if not h.get_text(strip=True) and not h.find("img"):
                h.decompose()
                n += 1
        res.add("empty-heading", "Removed empty headings", n)
        res.add("heading-order", "Re-levelled headings so they don't skip levels", normalise_headings(soup))
        n = 0
        for a in soup.find_all("a", href=True):
            if re.fullmatch(r"\s*(click here|read more|learn more|here|more)\s*", a.get_text() or "", re.I):
                a["aria-label"] = f"{a.get_text(strip=True)}: {_label_from_href(a['href']) or 'details'}"
                n += 1
        res.add("generic-link-text", "Gave generic 'click here' links descriptive accessible names", n)
        for m in soup.find_all(["video", "audio"], autoplay=True):
            if not m.has_attr("muted"):
                m["muted"] = ""
                res.add("autoplay-media", "Muted autoplaying media")

    res.html = str(soup)
    return res


LANDMARK_HINT = re.compile(r"(^|[\s_-])(nav|menu|header|masthead|topbar)([\s_-]|$)", re.I)
FOOTER_HINT = re.compile(r"(^|[\s_-])(footer|colophon|bottom)([\s_-]|$)", re.I)


def _wrap_main(soup: BeautifulSoup, body: Tag) -> Tag | None:
    """Give the page real landmarks: nav-ish blocks become <nav>, footer-ish become <footer>,
    everything else in <body> is wrapped in one <main>."""
    children = [c for c in body.find_all(recursive=False) if isinstance(c, Tag)]
    if not children:
        return None
    rest: list[Tag] = []
    for c in children:
        if c.name in ("script", "style", "noscript", "link", "meta"):
            continue
        ident = " ".join([*(c.get("class") or []), c.get("id") or ""])
        if c.name in ("header", "nav", "footer", "aside", "main"):
            continue
        if c.get("role") in ("banner", "navigation", "contentinfo", "complementary", "main"):
            continue
        if c.name == "div" and LANDMARK_HINT.search(ident) and len(c.find_all("a", href=True)) >= 3:
            c.name = "nav"
            if not c.get("aria-label"):
                c["aria-label"] = "Main"
            continue
        if c.name == "div" and FOOTER_HINT.search(ident):
            c.name = "footer"
            continue
        if c.name == "a" and re.search(r"skip", c.get_text() or "", re.I):
            continue
        rest.append(c)
    if not rest:
        return None
    main = soup.new_tag("main")
    rest[0].insert_before(main)
    for c in rest:
        main.append(c.extract())
    return main


def normalise_headings(soup: BeautifulSoup) -> int:
    """Make heading levels descend one step at a time (h1 → h2 → h3), never skipping."""
    prev = 0
    changed = 0
    for h in soup.find_all(re.compile("^h[1-6]$")):
        level = int(h.name[1])
        if prev and level > prev + 1:
            h.name = f"h{prev + 1}"
            level = prev + 1
            changed += 1
        prev = level
    return changed


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _parse_color(v: str | None) -> tuple[int, int, int] | None:
    if not v:
        return None
    m = re.match(r"#([0-9a-f]{6})", v.strip(), re.I)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", v)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def _luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        c1 = c / 255
        return c1 / 12.92 if c1 <= 0.03928 else ((c1 + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def fix_contrast_colour(fg: tuple[int, int, int], bg: tuple[int, int, int], target: float = 4.5) -> tuple[int, int, int]:
    """Push the text colour toward black or white (whichever the background is not) until it meets the ratio."""
    toward = (0, 0, 0) if _luminance(bg) > 0.5 else (255, 255, 255)
    cur = fg
    for step in range(1, 41):
        t = step / 40
        cur = tuple(int(round(fg[i] + (toward[i] - fg[i]) * t)) for i in range(3))  # type: ignore[assignment]
        if contrast_ratio(cur, bg) >= target:
            break
    return cur  # type: ignore[return-value]


def contrast_css(findings: list[dict[str, Any]]) -> tuple[str, int]:
    """Targeted colour overrides for every contrast failure axe reported, darkest-necessary shade only."""
    rules: list[str] = []
    seen: set[str] = set()
    for f in findings:
        if f.get("rule_id") != "color-contrast":
            continue
        for node in f.get("sample") or []:
            data = node.get("data") or {}
            sel = ", ".join(node.get("target") or [])
            fg, bg = _parse_color(data.get("fgColor")), _parse_color(data.get("bgColor"))
            if not sel or not fg or not bg or sel in seen:
                continue
            seen.add(sel)
            target = float(data.get("expectedContrastRatio", "4.5:1").split(":")[0] or 4.5)
            new = fix_contrast_colour(fg, bg, target)
            rules.append(f"{sel}{{color:{_hex(new)} !important}} /* was {_hex(fg)} on {_hex(bg)} */")
    return "\n".join(rules) + ("\n" if rules else ""), len(rules)


def _label_from_href(href: str) -> str | None:
    h = href.lower()
    for word, lab in (("facebook", "Facebook"), ("instagram", "Instagram"), ("twitter", "Twitter"), ("x.com", "X"),
                      ("linkedin", "LinkedIn"), ("youtube", "YouTube"), ("tiktok", "TikTok"), ("yelp", "Yelp"),
                      ("mailto:", "Email us"), ("tel:", "Call us"), ("maps", "Map"), ("pinterest", "Pinterest")):
        if word in h:
            return lab
    slug = re.sub(r"[?#].*$", "", h).rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug).replace("-", " ").replace("_", " ").strip()
    return slug.capitalize() if slug and slug != "index" else "Home" if slug in ("", "index") else None


def _jsonld_tag(soup: BeautifulSoup, p: schemas.BusinessProfile, url: str) -> Tag:
    data: dict[str, Any] = {"@context": "https://schema.org", "@type": p.business_type or "LocalBusiness", "name": p.name,
                            "description": p.description, "url": url}
    if p.phone:
        data["telephone"] = p.phone
    if p.street_address or p.locality:
        data["address"] = {k: v for k, v in {"@type": "PostalAddress", "streetAddress": p.street_address,
                                              "addressLocality": p.locality, "addressRegion": p.region,
                                              "postalCode": p.postal_code}.items() if v}
    if p.services:
        data["makesOffer"] = [{"@type": "Offer", "itemOffered": {"@type": "Service", "name": s}} for s in p.services]
    tag = soup.new_tag("script", type="application/ld+json")
    tag.string = json.dumps(data, indent=1)
    return tag


def _faq_tag(soup: BeautifulSoup, p: schemas.BusinessProfile) -> Tag:
    data = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q.question, "acceptedAnswer": {"@type": "Answer", "text": q.answer}} for q in p.faq]}
    tag = soup.new_tag("script", type="application/ld+json")
    tag.string = json.dumps(data, indent=1)
    return tag


def accessibility_css() -> str:
    return """/* Added by the accessibility remediation. Safe defaults; adjust colours to the brand. */
.ce-skip-link{position:absolute;left:-999px;top:0;background:#111;color:#fff;padding:.5rem 1rem;z-index:10000;text-decoration:none}
.ce-skip-link:focus{left:0}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,[tabindex]:focus-visible{outline:3px solid #005fcc;outline-offset:2px}
nav a,footer a{display:inline-block;min-height:24px;min-width:24px;line-height:24px}
"""


def robots_txt(existing: str | None, sitemap_url: str) -> tuple[str, list[Change]]:
    changes: list[Change] = []
    text = existing or ""
    if not existing:
        text = "User-agent: *\nAllow: /\n"
        changes.append(Change("robots-missing", "Created robots.txt"))
    lines = text.splitlines()
    cleaned: list[str] = []
    skip_block = False
    ai = {"gptbot", "chatgpt-user", "oai-searchbot", "claudebot", "anthropic-ai", "claude-web", "perplexitybot",
          "google-extended", "applebot-extended", "bingbot", "amazonbot", "ccbot"}
    removed = 0
    for line in lines:
        m = re.match(r"\s*user-agent\s*:\s*(.+)", line, re.I)
        if m:
            skip_block = m.group(1).strip().lower() in ai
            if skip_block:
                removed += 1
                continue
        if skip_block:
            if re.match(r"\s*(disallow|allow|crawl-delay)\s*:", line, re.I):
                continue
            skip_block = False
        cleaned.append(line)
    if removed:
        changes.append(Change("ai-crawlers-blocked", f"Removed {removed} rule blocks that were disallowing AI crawlers", removed))
    text = "\n".join(cleaned).rstrip() + "\n"
    if not re.search(r"^\s*sitemap\s*:", text, re.I | re.M):
        text += f"Sitemap: {sitemap_url}\n"
        changes.append(Change("sitemap-missing", "Pointed robots.txt at the sitemap"))
    return text, changes


def llms_txt(p: schemas.BusinessProfile, site_url: str, pages: list[dict[str, str]]) -> str:
    lines = [f"# {p.name}", "", f"> {p.description.strip()}", ""]
    if p.services:
        lines += ["## Services", *[f"- {s}" for s in p.services], ""]
    contact = [x for x in (p.phone, ", ".join(v for v in (p.street_address, p.locality, p.region, p.postal_code) if v)) if x]
    if contact:
        lines += ["## Contact", *[f"- {c}" for c in contact], ""]
    lines += ["## Pages", *[f"- [{pg.get('title') or pg['url']}]({pg['url']})" for pg in pages[:20]], ""]
    if p.faq:
        lines += ["## Frequently asked questions", *[f"- **{q.question}** {q.answer}" for q in p.faq], ""]
    return "\n".join(lines)


def sitemap_xml(pages: list[dict[str, str]]) -> str:
    urls = "".join(f"<url><loc>{_xml(pg['url'])}</loc></url>" for pg in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Word-writing helpers (the only model calls in the fixer)
# ---------------------------------------------------------------------------

ALT_SYSTEM = "You write alt text for images on a small-business website. Be concrete and brief (under 12 words). " \
             "Use an empty string for purely decorative images (spacers, dividers, background textures). Never start with 'image of'."
META_SYSTEM = "You write page titles and meta descriptions for small-business websites. Plain, specific, no hype, no exclamation marks."
PROFILE_SYSTEM = "You extract a factual business profile from a website's own text for schema.org markup and an llms.txt summary. " \
                 "Only state facts present in the text. Choose the most specific schema.org LocalBusiness subtype that fits. " \
                 "Write up to 5 FAQ pairs answerable from the text; skip FAQs if the text doesn't support them."


def write_alt_text(llm: LLM, images: list[str], business: dict[str, Any]) -> dict[str, str]:
    if not images:
        return {}
    ctx = {"business_name": business.get("business_name"), "category": business.get("category"), "images": images[:60]}
    batch = llm.structured(system=ALT_SYSTEM, user="Write alt text for these image paths.\n\n```json\n" + json.dumps(ctx) + "\n```",
                           schema=schemas.AltTextBatch, effort="low")
    return {i.src: i.alt for i in batch.items}


def write_meta(llm: LLM, business: dict[str, Any], page_text: str) -> schemas.MetaCopy:
    ctx = {**business, "page_text": page_text[:3000]}
    return llm.structured(system=META_SYSTEM, user="Write the home page title and description.\n\n```json\n" + json.dumps(ctx) + "\n```",
                          schema=schemas.MetaCopy, effort="low")


def extract_profile(llm: LLM, business: dict[str, Any], site_text: str) -> schemas.BusinessProfile:
    ctx = {**business, "site_text": site_text[:12000]}
    return llm.structured(system=PROFILE_SYSTEM, user="Extract the business profile.\n\n```json\n" + json.dumps(ctx) + "\n```",
                          schema=schemas.BusinessProfile, effort="medium")
