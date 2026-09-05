"""Guardrails every outbound email passes through.

Two layers: the model is told the rules, and then the code checks anyway.
CAN-SPAM needs an honest subject, a real postal address, a working opt-out that is
honoured promptly, and no deceptive headers. On top of that we refuse the claims
that have drawn FTC action in this niche: guarantees of compliance, "certified",
invented dollar figures, manufactured urgency, and anything that reads like a
legal notice.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from typing import Iterable

FORBIDDEN_PHRASES = [
    "guarantee", "guaranteed", "fully compliant", "100% compliant", "certified", "certification", "certificate",
    "you will be sued", "you'll be sued", "will be sued", "lawsuit has been", "has been filed", "legal notice",
    "final notice", "immediate action", "act now", "urgent", "last chance", "limited time", "fine of", "fines",
    "penalty", "penalties", "protect you from", "lawsuit-proof", "immune", "government requires you",
    "required by law to hire", "your account", "verify your", "we noticed you were sued", "before it's too late",
    "don't get sued", "avoid a lawsuit", "avoid lawsuits", "compliance certificate", "ada certified",
]
SUBJECT_FORBIDDEN = ["re:", "fw:", "fwd:", "invoice", "payment", "legal", "urgent", "lawsuit", "notice", "warning",
                     "action required", "account", "complaint", "violation", "suspended", "important"]
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM])?")


@dataclass
class LintResult:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems}


def new_thread_token() -> str:
    return secrets.token_urlsafe(8).replace("-", "x").replace("_", "y").lower()


def _cents_to_variants(cents: int) -> set[str]:
    dollars = cents / 100
    out = {f"${dollars:,.0f}", f"${dollars:,.2f}", f"${int(dollars)}", f"${dollars:,.0f}".replace(",", "")}
    if dollars >= 1000 and dollars % 1000 == 0:
        out.add(f"${int(dollars // 1000)}k")
        out.add(f"${int(dollars // 1000)},000")
    return out


def lint_email(*, subject: str, body_text: str, allowed_cents: Iterable[int], require_footer: bool = True,
               postal_address: str = "", legal_name: str = "", max_words: int = 320) -> LintResult:
    problems: list[str] = []
    s = subject.strip()
    sl = s.lower()
    if not s:
        problems.append("subject empty")
    if len(s) > 78:
        problems.append("subject longer than 78 chars")
    if "!" in s:
        problems.append("subject contains '!'")
    if s.isupper() and len(s) > 5:
        problems.append("subject is all caps")
    for bad in SUBJECT_FORBIDDEN:
        if bad in sl:
            problems.append(f"subject contains '{bad}'")
    bl = body_text.lower()
    for bad in FORBIDDEN_PHRASES:
        if re.search(r"(?<![a-z])" + re.escape(bad) + r"(?![a-z])", bl):
            problems.append(f"body contains forbidden phrase '{bad}'")
    allowed = set()
    for c in allowed_cents:
        allowed |= _cents_to_variants(int(c))
    allowed_norm = {a.replace(",", "").replace(" ", "").lower() for a in allowed}
    for m in MONEY_RE.findall(body_text):
        norm = m.replace(",", "").replace(" ", "").lower()
        if norm.endswith(".00"):
            norm = norm[:-3]
        if norm not in allowed_norm:
            problems.append(f"body contains a dollar figure not produced by the exposure model: {m.strip()}")
    if MONEY_RE.search(body_text) and "estimate" not in bl:
        problems.append("body quotes dollar figures without the word 'estimate'")
    if require_footer:
        if "unsubscribe" not in bl:
            problems.append("body lacks an unsubscribe instruction")
        if postal_address and postal_address.lower() not in bl:
            problems.append("body lacks the postal address")
        if legal_name and legal_name.lower() not in bl:
            problems.append("body lacks the sender's legal name")
    core = body_text.split("\n—\n", 1)[0]  # the footer (sources, address, opt-out) doesn't count
    if len(re.findall(r"\w+", core)) > max_words:
        problems.append(f"body longer than {max_words} words")
    return LintResult(ok=not problems, problems=problems)


def footer(*, legal_name: str, postal_address: str, website: str, domain: str, category: str | None, city: str | None,
           unsubscribe_url: str, report_url: str | None, sources: list[dict] | None, has_estimates: bool) -> str:
    lines = ["—"]
    if report_url:
        lines.append(f"Full report for {domain}: {report_url}")
    if has_estimates:
        lines.append("The dollar figures above are estimates, not predictions, based on publicly reported settlement ranges "
                     "and stated traffic assumptions.")
        for src in (sources or [])[:4]:
            lines.append(f"  Source: {src['title']} - {src['url']}")
    where = f" in {city}" if city else ""
    what = f"a {category}" if category else "a business"
    lines.append(f"You're receiving this one-time business message because {domain} is publicly listed as {what}{where}. "
                 f"We won't email again after two short follow-ups.")
    lines.append(f"To opt out, reply with the word \"unsubscribe\" or visit {unsubscribe_url} — either works immediately.")
    lines.append(f"{legal_name}, {postal_address} · {website}")
    return "\n".join(lines)
