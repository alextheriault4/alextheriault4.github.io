"""Can we actually change this site for them?

Only pitch a business whose website we can genuinely fix once they say yes. Selling a
remediation and then emailing a zip file with "paste this into your theme editor" is how
you get refund requests and bad reviews, and it is not what the outreach promised.

So fixability is decided during the scan, from evidence, and a site we cannot change is
excluded before any email is drafted.

Three tiers:

``direct``    We can apply the change ourselves once they grant access, and granting it is
              a couple of clicks. GitHub-hosted sites (we open a pull request they merge),
              WordPress with a reachable REST API (an application password), and Git-backed
              static hosts.
``assisted``  We can produce the change but they must paste it in - Wix, Squarespace,
              GoDaddy and friends expose no editing API to third parties.
``unknown``   No usable signal. Treated as not fixable.

The easiest case is a **public GitHub repository**: we fork it, open a pull request, and
the owner clicks Merge. That needs no credentials from them at all, which is why GitHub
Pages sites are the best possible first market.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

Tier = str  # "direct" | "assisted" | "unknown"

# Response-header and body fingerprints for hosts whose sites are Git-backed.
HOST_SIGNATURES: list[tuple[str, str, re.Pattern[str]]] = [
    ("github_pages", "server", re.compile(r"github\.com", re.I)),
    ("github_pages", "x-github-request-id", re.compile(r".")),
    ("netlify", "x-nf-request-id", re.compile(r".")),
    ("netlify", "server", re.compile(r"netlify", re.I)),
    ("vercel", "x-vercel-id", re.compile(r".")),
    ("vercel", "server", re.compile(r"vercel", re.I)),
]

# Cloudflare's ``cf-ray`` header is on every site behind their CDN - a large fraction of the
# whole web, most of it Wix and Squarespace and WordPress - so it says nothing about whether
# we could edit the site. Only the Pages hostname is real evidence.
GIT_BACKED_DOMAIN_SUFFIXES = {".pages.dev": "cloudflare_pages", ".netlify.app": "netlify",
                              ".vercel.app": "vercel", ".github.io": "github_pages"}

BUILDER_PLATFORMS = {"wix", "squarespace", "godaddy", "weebly", "duda", "shopify"}


@dataclass
class Fixability:
    tier: Tier
    channel: str            # github_pr | wordpress_rest | header_snippet | none
    detail: str             # one line for the dashboard and the exclusion reason
    repo: str | None = None  # owner/name when we could work it out
    evidence: dict[str, Any] | None = None

    @property
    def can_apply(self) -> bool:
        return self.tier == "direct"

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "channel": self.channel, "detail": self.detail,
                "repo": self.repo, "evidence": self.evidence or {}}


def guess_github_repo(domain: str, html: str) -> str | None:
    """Work out the repository behind a GitHub Pages site where we can.

    ``alex.github.io`` is served from ``alex/alex.github.io`` by definition. A project page
    at ``alex.github.io/thing`` comes from ``alex/thing``. Custom domains hide the repo, but
    many sites link to it anyway.
    """
    host = (domain or "").lower().removeprefix("www.")
    if host.endswith(".github.io"):
        owner = host.removesuffix(".github.io")
        if owner and owner != "github":
            return f"{owner}/{host}"
    # A link to the source repository, which template sites very often carry.
    m = re.search(r"https?://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)", html or "")
    if m and m.group(1).lower() not in ("features", "about", "pricing", "sponsors", "topics"):
        return f"{m.group(1)}/{m.group(2).removesuffix('.git')}"
    return None


def detect_host(headers: dict[str, str] | None, domain: str = "") -> str | None:
    """Which Git-backed host is serving this, if we can tell. Absence of an answer is the
    safe answer: it means we do not pitch."""
    host = (domain or "").lower().removeprefix("www.")
    for suffix, name in GIT_BACKED_DOMAIN_SUFFIXES.items():
        if host.endswith(suffix):
            return name
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    for name, header, pattern in HOST_SIGNATURES:
        value = headers.get(header)
        if value and pattern.search(value):
            return name
    return None


def wordpress_rest_available(fetch_json: Any, origin: str) -> bool:
    """Whether the WordPress REST API answers, which is what we would write through."""
    try:
        ok, body = fetch_json(origin + "/wp-json/")
    except Exception:  # noqa: BLE001 - a probe must never break a scan
        return False
    if not ok or not body:
        return False
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and ("namespaces" in data or "routes" in data)


def assess(*, domain: str, url: str, platform: str, headers: dict[str, str] | None,
           home_html: str, wp_rest: bool = False) -> Fixability:
    """Decide how, if at all, we could change this site."""
    host = detect_host(headers, domain)

    # A site builder is checked before any host signal. Wix behind a CDN is still Wix, and
    # mistaking the CDN for the host would have us promise a change we cannot make.
    if platform in BUILDER_PLATFORMS:
        return Fixability(
            "assisted", "header_snippet",
            f"{platform.title()} exposes no editing API to third parties, so we could only hand them a snippet",
            evidence={"platform": platform, "host": host})

    if host == "github_pages":
        repo = guess_github_repo(domain, home_html)
        if repo:
            return Fixability(
                "direct", "github_pr",
                f"GitHub Pages from {repo}; we can open a pull request they merge in one click",
                repo=repo, evidence={"host": host})
        return Fixability(
            "direct", "github_pr",
            "GitHub Pages on a custom domain; we can open a pull request once they name the repository",
            evidence={"host": host})

    if platform == "wordpress" and wp_rest:
        return Fixability(
            "direct", "wordpress_rest",
            "WordPress with the REST API reachable; an application password is four clicks for them",
            evidence={"host": host, "platform": platform})

    if host in ("netlify", "vercel", "cloudflare_pages"):
        repo = guess_github_repo(domain, home_html)
        return Fixability(
            "direct", "github_pr",
            f"{host.replace('_', ' ').title()} site, normally built from a Git repository"
            + (f" ({repo})" if repo else "; they tell us the repository once"),
            repo=repo, evidence={"host": host})

    if platform == "wordpress":
        return Fixability(
            "assisted", "header_snippet",
            "WordPress but the REST API did not answer; changes would have to be pasted in",
            evidence={"platform": platform})

    if platform in BUILDER_PLATFORMS:
        return Fixability(
            "assisted", "header_snippet",
            f"{platform.title()} exposes no editing API to third parties, so we could only hand them a snippet",
            evidence={"platform": platform})

    return Fixability(
        "unknown", "none",
        f"no way in that we can detect (platform: {platform or 'unknown'})",
        evidence={"host": host, "platform": platform})


def eligible_to_pitch(fixability: Fixability | None, require_direct: bool) -> tuple[bool, str]:
    """Whether outreach may proceed, and why not when it may not."""
    if fixability is None:
        return (not require_direct), "fixability was never assessed"
    if not require_direct:
        return True, "ok"
    if fixability.can_apply:
        return True, "ok"
    return False, f"we could not change this site for them: {fixability.detail}"
