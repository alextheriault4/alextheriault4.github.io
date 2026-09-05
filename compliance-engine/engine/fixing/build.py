"""Build a remediation bundle for a paid deal from the scan snapshots."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .. import schemas
from ..config import Settings
from ..db import Database, utcnow
from ..llm import LLM
from ..models import FixStrategy
from . import patches

BUILDER_PLATFORMS = {"wix", "squarespace", "godaddy", "weebly", "duda", "webflow", "shopify"}


@dataclass
class Bundle:
    root: Path
    pages: list[dict[str, Any]] = field(default_factory=list)
    site_files: dict[str, str] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)
    strategy: str = FixStrategy.BUNDLE
    header_snippet: str = ""
    remaining: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_rule: dict[str, int] = {}
        for c in self.changes:
            by_rule[c["rule_id"]] = by_rule.get(c["rule_id"], 0) + int(c["count"])
        return {"pages": [p["url"] for p in self.pages], "site_files": sorted(self.site_files), "changes_by_rule": by_rule,
                "total_changes": sum(by_rule.values()), "strategy": self.strategy, "remaining": self.remaining}


def choose_strategy(db: Database, lead: dict[str, Any]) -> str:
    if db.get_kv(f"lead:{lead['id']}:wp_app_password") and (lead.get("platform") == "wordpress"):
        return FixStrategy.WORDPRESS_REST
    if db.get_kv(f"lead:{lead['id']}:github_repo") and db.get_kv("github_token"):
        return FixStrategy.GITHUB_PR
    if (lead.get("platform") or "") in BUILDER_PLATFORMS:
        return FixStrategy.HEADER_SNIPPET
    return FixStrategy.BUNDLE


def _page_path(url: str) -> str:
    p = urlparse(url).path or "/"
    if p.endswith("/"):
        p += "index.html"
    if not re.search(r"\.[a-z0-9]{2,5}$", p, re.I):
        p += ".html"
    return p.lstrip("/")


def build_bundle(db: Database, settings: Settings, llm: LLM, deal_id: int) -> Bundle:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    scan = db.latest_scan(lead["id"])
    if scan is None:
        raise RuntimeError("no baseline scan on file")
    snap_dir = settings.workdir / "snapshots" / lead["domain"]
    root = settings.workdir / "fixes" / lead["domain"] / str(deal_id)
    (root / "pages").mkdir(parents=True, exist_ok=True)
    bundle = Bundle(root=root, strategy=choose_strategy(db, lead))
    business = {"business_name": lead.get("business_name"), "category": lead.get("category"), "city": lead.get("city"),
                "region": lead.get("region"), "domain": lead["domain"]}
    home_url = scan["pages"][0]["url"]
    origin = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"
    package = deal["package"]
    do_ada = package in ("ada", "bundle")
    do_seo = package in ("aiseo", "bundle")

    # Gather text and images across pages for the word-writing calls.
    raw_pages: list[tuple[dict[str, Any], str]] = []
    images: list[str] = []
    site_text_parts: list[str] = []
    for pg in scan["pages"]:
        raw = (snap_dir / f"{pg['snapshot']}.raw.html")
        html = raw.read_text(encoding="utf-8") if raw.exists() and raw.stat().st_size > 200 else \
            (snap_dir / f"{pg['snapshot']}.rendered.html").read_text(encoding="utf-8")
        raw_pages.append((pg, html))
        soup = BeautifulSoup(html, "lxml")
        for s in soup(["script", "style"]):
            s.decompose()
        site_text_parts.append(soup.get_text(" ", strip=True))
        for img in soup.find_all("img"):
            if not img.has_attr("alt"):
                src = (img.get("src") or img.get("data-src") or "").strip()
                if src and src not in images:
                    images.append(src)
    site_text = "\n".join(site_text_parts)

    alt_text = patches.write_alt_text(llm, images, business) if (do_ada and images) else {}
    profile = patches.extract_profile(llm, business, site_text) if do_seo else None
    meta = patches.write_meta(llm, business, site_text_parts[0] if site_text_parts else "") if do_seo else None
    lang = "en"

    page_index = []
    for i, (pg, html) in enumerate(raw_pages):
        is_home = i == 0
        res = patches.patch_page(
            html, page_url=pg["url"], is_home=is_home, lang=lang, meta=meta if do_seo else None,
            profile=profile if do_seo else None, alt_text=alt_text if do_ada else {},
            canonical_url=pg["url"] if do_seo else None, site_name=lead.get("business_name") or lead["domain"],
        )
        if not do_ada:
            res.changes = [c for c in res.changes if c.rule_id in patches_seo_rules()]
        if not do_seo:
            res.changes = [c for c in res.changes if c.rule_id not in patches_seo_rules()]
        rel = _page_path(pg["url"])
        out = root / "pages" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(res.html, encoding="utf-8")
        (root / "pages" / (rel + ".orig")).write_text(html, encoding="utf-8")
        bundle.pages.append({"url": pg["url"], "path": rel, "title": pg.get("title") or "", "sha": hashlib.sha1(res.html.encode()).hexdigest()[:10]})
        page_index.append({"url": pg["url"], "title": pg.get("title") or ""})
        for c in res.changes:
            bundle.changes.append({"file": rel, "rule_id": c.rule_id, "description": c.description, "count": c.count})

    if do_ada:
        css = patches.accessibility_css()
        contrast, n_contrast = patches.contrast_css(db.findings_for_scan(scan["id"]))
        bundle.site_files["accessibility.css"] = css + contrast
        bundle.changes.append({"file": "accessibility.css", "rule_id": "focus-visible", "description": "Visible keyboard focus styles and skip-link styling", "count": 1})
        bundle.changes.append({"file": "accessibility.css", "rule_id": "target-size", "description": "Minimum 24px tap targets for navigation and footer links", "count": 1})
        if n_contrast:
            bundle.changes.append({"file": "accessibility.css", "rule_id": "color-contrast", "description": "Adjusted text colours that failed contrast to the nearest passing shade", "count": n_contrast})
        for pg in bundle.pages:
            path = root / "pages" / pg["path"]
            html = path.read_text(encoding="utf-8")
            if "accessibility.css" not in html:
                path.write_text(html.replace("</head>", '<link rel="stylesheet" href="/accessibility.css">\n</head>', 1), encoding="utf-8")
    bundle.remaining = _remaining_items(db.findings_for_scan(scan["id"]), {c["rule_id"] for c in bundle.changes})
    if do_seo and profile is not None:
        robots_existing = (snap_dir / "robots.txt").read_text() if (snap_dir / "robots.txt").exists() else None
        robots, rchanges = patches.robots_txt(robots_existing, f"{origin}/sitemap.xml")
        bundle.site_files["robots.txt"] = robots
        bundle.changes += [{"file": "robots.txt", "rule_id": c.rule_id, "description": c.description, "count": c.count} for c in rchanges]
        bundle.site_files["llms.txt"] = patches.llms_txt(profile, origin, page_index)
        bundle.changes.append({"file": "llms.txt", "rule_id": "llms-txt-missing", "description": "Wrote an llms.txt summary for AI assistants", "count": 1})
        if not scan["aiseo_summary"]["facts"].get("sitemap_ok"):
            bundle.site_files["sitemap.xml"] = patches.sitemap_xml(page_index)
            bundle.changes.append({"file": "sitemap.xml", "rule_id": "sitemap-missing", "description": "Generated a sitemap", "count": 1})
        bundle.header_snippet = _header_snippet(meta, profile, origin)
        bundle.site_files["header-snippet.html"] = bundle.header_snippet

    for name, content in bundle.site_files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "CHANGES.md").write_text(_changes_md(lead, deal, bundle), encoding="utf-8")
    (root / "INSTRUCTIONS.md").write_text(_instructions_md(lead, bundle), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"deal_id": deal_id, "domain": lead["domain"], "built_at": utcnow(),
                                                    **bundle.summary()}, indent=1), encoding="utf-8")
    return bundle


NEEDS_INPUT = {
    "thin-content": "The home page has very little text. Add a few paragraphs describing the business, services and area served.",
    "no-nap": "Put the business phone number and street address in visible page text (footer is fine).",
    "not-https": "Serve the site over HTTPS (your host usually offers a free certificate).",
    "slow-load": "The page loads slowly; compress large images and remove unused scripts.",
    "video-caption": "Videos need captions; upload a caption file or use your video host's caption feature.",
    "js-only-content": "Most text only appears after JavaScript runs. Ask your developer/platform for server-side rendering or a static export.",
    "all-crawlers-blocked": "robots.txt currently blocks every crawler; confirm you want that changed before publishing the new robots.txt.",
}


def _remaining_items(findings: list[dict[str, Any]], fixed_rules: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in findings:
        r = f["rule_id"]
        if r in seen or r in fixed_rules:
            continue
        if r in NEEDS_INPUT:
            seen.add(r)
            out.append({"rule_id": r, "impact": f.get("impact"), "advice": NEEDS_INPUT[r]})
    return out


def patches_seo_rules() -> set[str]:
    return {"title-weak", "title-missing", "meta-description-missing", "og-missing", "canonical-missing", "structured-data-missing",
            "faq-schema-missing", "robots-missing", "ai-crawlers-blocked", "sitemap-missing", "llms-txt-missing", "h1-missing"}


def _header_snippet(meta: schemas.MetaCopy | None, profile: schemas.BusinessProfile | None, origin: str) -> str:
    soup = BeautifulSoup("<div></div>", "lxml")
    parts = ["<!-- Paste into the site's <head> (Wix: Settings > Custom code; Squarespace: Settings > Advanced > Code injection) -->"]
    if meta:
        parts.append(f'<meta name="description" content="{meta.description.replace(chr(34), "&quot;")}">')
    if profile:
        parts.append(str(patches._jsonld_tag(soup, profile, origin)))
        if profile.faq:
            parts.append(str(patches._faq_tag(soup, profile)))
    parts.append("<style>" + patches.accessibility_css() + "</style>")
    return "\n".join(parts) + "\n"


def _changes_md(lead: dict[str, Any], deal: dict[str, Any], b: Bundle) -> str:
    lines = [f"# Changes for {lead['domain']} (deal {deal['id']}, {deal['package']} package)", ""]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for c in b.changes:
        by_file.setdefault(c["file"], []).append(c)
    for f, cs in by_file.items():
        lines.append(f"## {f}")
        for c in cs:
            n = f" ({c['count']}x)" if c["count"] > 1 else ""
            lines.append(f"- [{c['rule_id']}] {c['description']}{n}")
        lines.append("")
    if b.remaining:
        lines += ["## Needs your input (content or hosting decisions we can't make for you)", ""]
        for r in b.remaining:
            lines.append(f"- [{r['rule_id']}] {r['advice']}")
        lines.append("")
    return "\n".join(lines)


def _instructions_md(lead: dict[str, Any], b: Bundle) -> str:
    platform = lead.get("platform") or "unknown"
    generic = [
        f"# How to apply these changes to {lead['domain']}", "",
        f"Detected platform: **{platform}**. Strategy: **{b.strategy}**.", "",
        "## Files", "- `pages/`: patched copies of the pages we scanned (the `.orig` files are what we started from, so you can diff).",
        "- `accessibility.css`: focus styles and skip-link styling. Link it from every page or paste it into your main stylesheet.",
        "- `robots.txt`, `sitemap.xml`, `llms.txt`: upload to the site root.",
        "- `header-snippet.html`: metadata + structured data to paste into the site `<head>` when you can't edit page files directly.",
        "- `CHANGES.md`: every change mapped to the report finding it resolves.", "",
    ]
    per_platform = {
        "wordpress": ["## WordPress", "1. Image alt text, labels and headings are applied to page content via the REST API when you give us an application password (Users > Profile > Application Passwords).",
                      "2. Upload `mu-plugin/compliance-engine.php` to `wp-content/mu-plugins/` (create the folder if needed). It serves llms.txt, adds the structured data, meta description, skip link and focus styles to every page.",
                      "3. Or install Yoast/RankMath and paste the title and description from `header-snippet.html`."],
        "wix": ["## Wix", "1. Settings > Custom code > paste `header-snippet.html` into Head, all pages.", "2. Add alt text from `CHANGES.md` in the editor (select image > Settings > alt text).", "3. Settings > SEO > robots.txt editor: paste `robots.txt`. Wix cannot host llms.txt; we'll host it for you and link it from the head snippet."],
        "squarespace": ["## Squarespace", "1. Settings > Advanced > Code Injection > Header: paste `header-snippet.html`.", "2. Alt text: edit each image > Image alt text (list in `CHANGES.md`).", "3. Marketing > SEO: paste the title and description.", "4. Upload `llms.txt` via Settings > Files and link it from the head snippet."],
        "static_or_custom": ["## Static / custom site", "1. Replace each page with the patched copy in `pages/` (or apply the diff against `.orig`).", "2. Upload `accessibility.css`, `robots.txt`, `sitemap.xml`, `llms.txt` to the site root.", "3. If the site is in Git, we can open a pull request instead: give us the repository URL."],
    }
    lines = generic + per_platform.get(platform, per_platform["static_or_custom"])
    lines += ["", "When you're done (or after we apply it), reply to our email and we'll run the verification rescan and send the before/after report."]
    return "\n".join(lines) + "\n"
