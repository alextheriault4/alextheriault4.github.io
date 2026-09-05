"""Risk controls.

This is not legal advice and it cannot make a lawsuit impossible - anyone can file
anything. What it does is close the specific, documented ways businesses doing exactly
this work get sued, fined, or reported:

* **Who we contact.** CAN-SPAM makes unsolicited US commercial email lawful when it is
  honest and offers a working opt-out. Canada's CASL and the EU/UK regimes do not work
  that way and carry seven-figure penalties, so non-US recipients are refused outright.
  Plaintiff-side professions and regulated verticals are excluded because they are the
  ones most likely to turn an unwanted email into a filing.
* **How we look at their site.** A crawler that identifies itself, obeys robots.txt,
  waits between requests, reads only public pages and never touches a login form is an
  ordinary web client. One that does the opposite is the fact pattern in an unauthorised
  access complaint.
* **What we say.** We are not lawyers. The engine never states that a site "violates" a
  law, never tells anyone what the law requires of them, and never promises immunity.
* **What we hold.** Client site credentials are encrypted at rest and deleted once the
  work is delivered.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .config import LegalSettings, Settings

# Phrases that would put us in the business of practising law, defaming a prospect, or
# promising an outcome we cannot deliver. Checked in addition to the marketing lint.
LEGAL_CLAIM_PHRASES = [
    "you are required by law", "the law requires you", "you must comply", "you are violating",
    "your site violates", "is illegal", "unlawful", "you are non-compliant", "you are noncompliant",
    "in violation of", "breaks the ada", "breaking the law", "legally obligated", "legally required",
    "we are attorneys", "our lawyers", "legal opinion", "as your counsel", "cease and desist",
    "statute requires", "mandated by law", "federal law requires", "you will be fined",
    "immune from", "protects you from lawsuits", "makes you lawsuit-proof", "eliminates your risk",
]

# Safe ways to say the same true thing.
SAFE_ALTERNATIVES = {
    "violates": "was flagged by the scan against",
    "illegal": "flagged",
    "non-compliant": "flagged against WCAG 2.1 AA checks",
    "required by law": "commonly expected",
}

FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com", "msn.com"}

# Rough US signals. Used to refuse anything we cannot place in the US, not to prove it.
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
    "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC", "PR", "VI", "GU", "AS", "MP",
}
NON_US_HINTS = re.compile(
    r"\b(ltd\.?|limited|gmbh|s\.?a\.?r\.?l|b\.?v\.?|pty|ulc|abn \d|vat (no|number)|siret|"
    r"registered in (england|wales|scotland|ireland|canada|australia))\b", re.I)
NON_US_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}|[A-Z]\d[A-Z]\s?\d[A-Z]\d)\b")


@dataclass
class Eligibility:
    ok: bool
    reason: str = "ok"

    def __bool__(self) -> bool:  # lets callers write `if eligible(...):`
        return self.ok


def _root_domain(domain: str) -> str:
    return (domain or "").lower().removeprefix("www.")


def check_lead(lead: dict[str, Any], settings: Settings, page_text: str = "") -> Eligibility:
    """May we contact this business at all? Called before any email is drafted."""
    lg = settings.legal
    domain = _root_domain(str(lead.get("domain") or ""))
    if not domain:
        return Eligibility(False, "no domain")

    for suffix in lg.blocked_domain_suffixes:
        if domain.endswith(suffix):
            return Eligibility(False, f"domain ends in {suffix} (government, military or education)")

    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    if lg.us_only and tld in {t.lower().lstrip(".") for t in lg.blocked_tlds}:
        return Eligibility(False, f".{tld} suggests a non-US business; only US recipients are in scope")

    country = str(lead.get("country") or "US").upper()
    if lg.us_only and country not in {c.upper() for c in lg.allowed_country_codes}:
        return Eligibility(False, f"country {country} is outside the US-only policy (CASL/GDPR are not implemented)")

    region = str(lead.get("region") or "").upper()
    if lg.us_only and region and region not in US_STATE_CODES:
        return Eligibility(False, f"region {region!r} is not a US state or territory")

    category = str(lead.get("category") or "").lower()
    name = str(lead.get("business_name") or "").lower()
    for excluded in lg.excluded_categories:
        needle = excluded.lower()
        if needle in category or re.search(rf"\b{re.escape(needle)}\b", name):
            return Eligibility(False, f"excluded category or business name matches {excluded!r}")

    if lg.us_only and page_text:
        head = page_text[:20_000]
        if NON_US_HINTS.search(head) or NON_US_POSTCODE.search(head):
            return Eligibility(False, "site text carries non-US registration or postcode markers")

    email = str(lead.get("contact_email") or "")
    if email:
        local = email.split("@", 1)[0].lower()
        if any(local.startswith(p) for p in ("legal", "privacy", "dpo", "compliance", "abuse", "postmaster", "security")):
            return Eligibility(False, f"contact address {email!r} is a legal or abuse mailbox")

    return Eligibility(True)


def check_email_body(body_text: str) -> list[str]:
    """Legal-claim problems in an outbound body. Empty list means clean."""
    low = body_text.lower()
    problems = []
    for phrase in LEGAL_CLAIM_PHRASES:
        if phrase in low:
            problems.append(f"body makes a legal claim we are not licensed to make: {phrase!r}")
    return problems


# ---------------------------------------------------------------------------
# Crawl politeness
# ---------------------------------------------------------------------------

class CrawlPolicy:
    """Obeys robots.txt, waits between requests, and remembers what it was told.

    Kept per scan run. ``allowed(url)`` is the gate for every fetch; ``wait()`` enforces
    the delay so a scan never looks like a burst.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.legal = settings.legal
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._delays: dict[str, float] = {}
        self._last_fetch: dict[str, float] = {}

    @property
    def user_agent(self) -> str:
        return self.settings.scanning.user_agent

    @property
    def agent_token(self) -> str:
        return "ComplianceEngineBot"

    def load_robots(self, origin: str, robots_txt: str | None) -> None:
        """Register the robots.txt we already fetched for this origin."""
        if robots_txt is None:
            self._parsers[origin] = None
            return
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        self._parsers[origin] = parser
        delay = None
        try:
            delay = parser.crawl_delay(self.agent_token) or parser.crawl_delay("*")
        except Exception:  # noqa: BLE001 - malformed robots.txt must never break a scan
            delay = None
        if delay:
            self._delays[origin] = max(float(delay), self.legal.crawl_delay_seconds)

    def allowed(self, url: str) -> bool:
        if not self.legal.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        parser = self._parsers.get(origin)
        if parser is None:
            return True  # no robots.txt means no restriction
        try:
            # can_fetch already applies group precedence: a rule naming our agent wins over
            # the wildcard group, so never widen it by also consulting "*".
            return bool(parser.can_fetch(self.agent_token, url))
        except Exception:  # noqa: BLE001
            return True

    def wait(self, url: str) -> None:
        origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        delay = self._delays.get(origin, self.legal.crawl_delay_seconds)
        last = self._last_fetch.get(origin)
        if last is not None:
            remaining = delay - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(min(remaining, 30.0))
        self._last_fetch[origin] = time.monotonic()


# Paths a well-behaved scanner has no business requesting: logins, admin panels, carts,
# anything that could be read as probing rather than reading.
SENSITIVE_PATH = re.compile(
    r"(wp-login|wp-admin|/admin|/login|/signin|/sign-in|/register|/checkout|/cart|/account|"
    r"/dashboard|/user/|/customer|/api/|\.env|\.git|/phpmyadmin|/backup|/config|/xmlrpc)", re.I)


def safe_to_fetch(url: str) -> bool:
    return not SENSITIVE_PATH.search(urlparse(url).path or "")


# ---------------------------------------------------------------------------
# Credentials at rest
# ---------------------------------------------------------------------------

class SecretBox:
    """Encrypts client credentials so a stolen database file is not a breach report.

    Without a key configured, storing a secret raises rather than silently writing
    plaintext - the preflight refuses live mode for the same reason.
    """

    PREFIX = "enc:v1:"

    def __init__(self, key: str):
        self.key = key or ""

    def available(self) -> bool:
        return bool(self.key)

    def _fernet(self):  # type: ignore[no-untyped-def]
        from cryptography.fernet import Fernet

        return Fernet(self.key.encode() if isinstance(self.key, str) else self.key)

    def encrypt(self, plaintext: str) -> str:
        if not self.available():
            raise RuntimeError(
                "refusing to store a client credential unencrypted: set CE_SECRETS_KEY "
                '(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")'
            )
        return self.PREFIX + self._fernet().encrypt(plaintext.encode()).decode()

    def decrypt(self, stored: str | None) -> str | None:
        if not stored:
            return None
        if not stored.startswith(self.PREFIX):
            return stored  # written before a key existed; readable but flagged by preflight
        if not self.available():
            raise RuntimeError("CE_SECRETS_KEY is not set but stored credentials are encrypted")
        from cryptography.fernet import InvalidToken

        try:
            return self._fernet().decrypt(stored[len(self.PREFIX):].encode()).decode()
        except InvalidToken as e:
            raise RuntimeError("stored credential could not be decrypted with the current CE_SECRETS_KEY") from e


SECRET_KEYS = ("wp_app_password", "github_token", "ftp_password")


def is_secret(key: str) -> bool:
    return any(k in key for k in SECRET_KEYS)
