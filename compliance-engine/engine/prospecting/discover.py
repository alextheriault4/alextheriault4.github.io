"""Pull a contact address and a platform guess out of a site's HTML."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
BAD_LOCAL = ("noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster", "abuse", "sentry", "example", "test@", "user@", "email@", "name@", "you@", "someone@")
BAD_DOMAIN = ("example.", "sentry.", "wixpress.", "wix.com", "squarespace.", "godaddy.", "domain.com", "yourdomain", "email.com", "sentry.io", "w3.org", "schema.org", "png", "jpg", "gif", "svg", "webp", "js", "css")
PREFERRED = ("info", "contact", "hello", "office", "admin", "owner", "sales", "support", "hi", "team", "frontdesk", "reception", "inquiries", "enquiries")

PLATFORM_SIGNATURES: list[tuple[str, re.Pattern[str]]] = [
    ("wordpress", re.compile(r"/wp-content/|/wp-includes/|wp-json|generator\" content=\"WordPress", re.I)),
    ("wix", re.compile(r"static\.wixstatic\.com|wix\.com|X-Wix-", re.I)),
    ("squarespace", re.compile(r"squarespace\.com|static1\.squarespace|Squarespace", re.I)),
    ("shopify", re.compile(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", re.I)),
    ("webflow", re.compile(r"webflow\.com|data-wf-page|assets\.website-files\.com", re.I)),
    ("godaddy", re.compile(r"godaddy|websites\.godaddy|img1\.wsimg\.com", re.I)),
    ("weebly", re.compile(r"weebly\.com|editmysite", re.I)),
    ("duda", re.compile(r"duda\.co|dudamobile|irp\.cdn-website\.com", re.I)),
    ("joomla", re.compile(r"/media/jui/|Joomla", re.I)),
    ("drupal", re.compile(r"Drupal\.settings|/sites/default/files", re.I)),
]


@dataclass
class DiscoveryResult:
    email: str | None
    email_source: str | None
    platform: str
    all_emails: list[str]


def detect_platform(html: str, headers: dict[str, str] | None = None) -> str:
    blob = html[:400_000]
    if headers:
        blob += "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items())
    for name, rx in PLATFORM_SIGNATURES:
        if rx.search(blob):
            return name
    return "static_or_custom"


def find_emails(html: str, site_domain: str) -> list[str]:
    candidates: list[str] = []
    for m in re.finditer(r"mailto:([^\"'?>\s]+)", html, re.I):
        candidates.append(unquote(m.group(1)))
    candidates += EMAIL_RE.findall(html)
    # obfuscated forms: "name [at] domain [dot] com"
    for m in re.finditer(r"([\w.+-]+)\s*(?:\[at\]|\(at\)|\{at\}| at )\s*([\w-]+)\s*(?:\[dot\]|\(dot\)|\{dot\}| dot )\s*(\w{2,})", html, re.I):
        candidates.append(f"{m.group(1)}@{m.group(2)}.{m.group(3)}")
    cleaned: list[str] = []
    for c in candidates:
        c = c.strip().strip(".,;:").lower()
        if not EMAIL_RE.fullmatch(c):
            continue
        local, dom = c.split("@", 1)
        if any(b in local for b in BAD_LOCAL) or any(b in dom for b in BAD_DOMAIN):
            continue
        if re.search(r"\.(png|jpe?g|gif|svg|webp|js|css)$", dom):
            continue
        if c not in cleaned:
            cleaned.append(c)
    site_root = ".".join(site_domain.split(".")[-2:])

    def rank(e: str) -> tuple[int, int, int]:
        local, dom = e.split("@", 1)
        same_domain = 0 if dom.endswith(site_root) else 1
        pref = 0 if any(local.startswith(p) for p in PREFERRED) else 1
        freemail = 1 if dom in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com") else 0
        return (same_domain, pref, freemail)

    return sorted(cleaned, key=rank)


def discover(pages: list[tuple[str, str]], site_domain: str, headers: dict[str, str] | None = None) -> DiscoveryResult:
    """``pages`` is a list of (url, html). Contact pages are searched first."""
    ordered = sorted(pages, key=lambda p: 0 if re.search(r"contact|about|reach", p[0], re.I) else 1)
    emails: list[str] = []
    source = None
    for url, html in ordered:
        found = find_emails(html, site_domain)
        for e in found:
            if e not in emails:
                emails.append(e)
        if found and source is None:
            source = url
    platform = detect_platform(pages[0][1] if pages else "", headers)
    best = None
    if emails:
        best = sorted(emails, key=lambda e: _rank_key(e, site_domain))[0]
    return DiscoveryResult(email=best, email_source=source if best else None, platform=platform, all_emails=emails)


def _rank_key(e: str, site_domain: str) -> tuple[int, int, int]:
    site_root = ".".join(site_domain.split(".")[-2:])
    local, dom = e.split("@", 1)
    return (
        0 if dom.endswith(site_root) else 1,
        0 if any(local.startswith(p) for p in PREFERRED) else 1,
        1 if dom in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com") else 0,
    )
