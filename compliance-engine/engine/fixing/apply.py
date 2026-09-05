"""Apply a bundle to the client's site, where a channel exists.

* WordPress: page/post content via the REST API with an application password, plus a
  generated must-use plugin for the site-level pieces the REST API can't reach.
* GitHub: a pull request against the site's repository.
* Everything else: the bundle is delivered with instructions (handled by ``deliver``).
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from ..config import Settings, get_settings
from ..db import Database, utcnow
from ..legal import SecretBox
from ..models import FixStrategy
from .build import Bundle


def apply_bundle(db: Database, settings: Settings, deal_id: int, bundle: Bundle, client: httpx.Client | None = None) -> dict[str, Any]:
    deal = db.one("SELECT * FROM deals WHERE id=?", (deal_id,))
    lead = db.get_lead(deal["lead_id"])
    if bundle.strategy == FixStrategy.WORDPRESS_REST:
        return apply_wordpress(db, lead, bundle, client, settings)
    if bundle.strategy == FixStrategy.GITHUB_PR:
        return apply_github(db, settings, lead, bundle, client)
    return {"applied": False, "reason": f"strategy {bundle.strategy} is delivery-only"}


# ---------------------------------------------------------------------------
# WordPress
# ---------------------------------------------------------------------------

def _wp_auth(db: Database, lead: dict[str, Any], settings: Settings) -> tuple[str, str]:
    user = db.get_kv(f"lead:{lead['id']}:wp_user") or ""
    pw = db.get_secret(f"lead:{lead['id']}:wp_app_password", SecretBox(settings.secrets_key)) or ""
    if not (user and pw):
        raise RuntimeError("no WordPress credentials on file for this lead")
    return user, pw


def patch_wp_content(content_html: str, alt_text: dict[str, str]) -> tuple[str, int]:
    """Apply the in-content fixes (alt text, iframe titles, generic links) to a WP page's content HTML."""
    soup = BeautifulSoup(content_html, "html.parser")
    n = 0
    for img in soup.find_all("img"):
        if img.has_attr("alt"):
            continue
        src = (img.get("src") or "").strip()
        img["alt"] = alt_text.get(src, alt_text.get(src.rsplit("/", 1)[-1], ""))
        n += 1
    for fr in soup.find_all("iframe"):
        if not fr.get("title"):
            fr["title"] = "Embedded content"
            n += 1
    for a in soup.find_all("a", href=True):
        if re.fullmatch(r"\s*(click here|read more|learn more|here|more)\s*", a.get_text() or "", re.I) and not a.get("aria-label"):
            a["aria-label"] = f"{a.get_text(strip=True)}: {a['href'].rstrip('/').rsplit('/', 1)[-1] or 'details'}"
            n += 1
    return str(soup), n


def apply_wordpress(db: Database, lead: dict[str, Any], bundle: Bundle, client: httpx.Client | None = None,
                    settings: Settings | None = None) -> dict[str, Any]:
    user, pw = _wp_auth(db, lead, settings or get_settings())
    base = db.get_kv(f"lead:{lead['id']}:wp_url") or lead["url"].rstrip("/")
    base = re.sub(r"/(index\.\w+)?$", "", base)
    client = client or httpx.Client(timeout=30, trust_env=True)
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
    alt_text: dict[str, str] = {}
    for pg in bundle.pages:
        patched = (bundle.root / "pages" / pg["path"]).read_text(encoding="utf-8")
        for img in BeautifulSoup(patched, "lxml").find_all("img"):
            if img.get("src") and img.get("alt") is not None:
                alt_text[img["src"]] = img["alt"]
    updated = []
    for kind in ("pages", "posts"):
        r = client.get(f"{base}/wp-json/wp/v2/{kind}", params={"per_page": 100, "context": "edit"}, headers=headers)
        r.raise_for_status()
        for item in r.json():
            raw = (item.get("content") or {}).get("raw") or (item.get("content") or {}).get("rendered") or ""
            new, n = patch_wp_content(raw, alt_text)
            if n:
                u = client.post(f"{base}/wp-json/wp/v2/{kind}/{item['id']}", json={"content": new}, headers=headers)
                u.raise_for_status()
                updated.append({"type": kind, "id": item["id"], "changes": n})
    plugin = wp_mu_plugin(bundle)
    (bundle.root / "mu-plugin").mkdir(exist_ok=True)
    (bundle.root / "mu-plugin" / "compliance-engine.php").write_text(plugin, encoding="utf-8")
    db.log_event("fix_applied", lead["id"], strategy="wordpress_rest", updated=updated)
    return {"applied": True, "updated": updated, "mu_plugin": str(bundle.root / "mu-plugin" / "compliance-engine.php"),
            "note": "content-level fixes applied via REST; upload the mu-plugin for site-level pieces"}


def wp_mu_plugin(bundle: Bundle) -> str:
    def php_str(s: str) -> str:
        return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"
    llms = bundle.site_files.get("llms.txt", "")
    head = bundle.header_snippet or ""
    css = bundle.site_files.get("accessibility.css", "")
    return f"""<?php
/**
 * Plugin Name: Accessibility & AI-search remediation
 * Description: Serves llms.txt, adds structured data, meta description, skip link and focus styles. Generated from the remediation report.
 */
if (!defined('ABSPATH')) exit;
add_action('init', function () {{
  if (isset($_SERVER['REQUEST_URI']) && preg_match('#^/llms\\.txt$#', parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH))) {{
    header('Content-Type: text/plain; charset=utf-8');
    echo {php_str(llms)};
    exit;
  }}
}});
add_action('wp_head', function () {{
  if (is_front_page()) {{ echo {php_str(head)}; }}
  echo '<style>' . {php_str(css)} . '</style>';
}}, 1);
add_action('wp_body_open', function () {{
  echo '<a class="ce-skip-link" href="#main">Skip to main content</a>';
}});
add_filter('language_attributes', function ($output) {{
  return (strpos($output, 'lang=') === false) ? $output . ' lang="en"' : $output;
}});
add_filter('robots_txt', function ($output) {{
  return {php_str(bundle.site_files.get("robots.txt", ""))} ?: $output;
}}, 99);
"""


# ---------------------------------------------------------------------------
# GitHub pull request
# ---------------------------------------------------------------------------

def apply_github(db: Database, settings: Settings, lead: dict[str, Any], bundle: Bundle, client: httpx.Client | None = None) -> dict[str, Any]:
    repo = db.get_kv(f"lead:{lead['id']}:github_repo") or ""
    token = db.get_secret("github_token", SecretBox(settings.secrets_key)) or ""
    if not (repo and token):
        raise RuntimeError("github repo or token missing")
    subdir = (db.get_kv(f"lead:{lead['id']}:github_subdir") or "").strip("/")
    client = client or httpx.Client(timeout=30, trust_env=True)
    api = "https://api.github.com"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = client.get(f"{api}/repos/{repo}", headers=h)
    r.raise_for_status()
    default_branch = r.json()["default_branch"]
    r = client.get(f"{api}/repos/{repo}/git/ref/heads/{default_branch}", headers=h)
    r.raise_for_status()
    base_sha = r.json()["object"]["sha"]
    branch = f"accessibility-ai-search-fixes-{utcnow()[:10]}"
    client.post(f"{api}/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha}, headers=h).raise_for_status()
    files: dict[str, str] = {}
    for pg in bundle.pages:
        files[f"{subdir}/{pg['path']}".strip("/")] = (bundle.root / "pages" / pg["path"]).read_text(encoding="utf-8")
    for name, content in bundle.site_files.items():
        if name != "header-snippet.html":
            files[f"{subdir}/{name}".strip("/")] = content
    committed = []
    for path, content in files.items():
        existing = client.get(f"{api}/repos/{repo}/contents/{path}", params={"ref": branch}, headers=h)
        body: dict[str, Any] = {"message": f"Accessibility/AI-search fixes: {path}", "branch": branch,
                                "content": base64.b64encode(content.encode()).decode()}
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]
        client.put(f"{api}/repos/{repo}/contents/{path}", json=body, headers=h).raise_for_status()
        committed.append(path)
    changes_md = (bundle.root / "CHANGES.md").read_text(encoding="utf-8")
    pr = client.post(f"{api}/repos/{repo}/pulls", headers=h, json={
        "title": "Accessibility and AI-search fixes", "head": branch, "base": default_branch,
        "body": changes_md + "\n\nEach change maps to a finding in the remediation report.",
    })
    pr.raise_for_status()
    url = pr.json()["html_url"]
    db.log_event("fix_applied", lead["id"], strategy="github_pr", pr=url, files=committed)
    return {"applied": True, "pr_url": url, "files": committed}
