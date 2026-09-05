"""Email transports.

``ConsoleProvider`` writes outbound mail to ``<workdir>/outbox`` and reads simulated
inbound mail from ``<workdir>/inbox``; nothing leaves the machine. ``SmtpImapProvider``
is the live transport for any mailbox that speaks SMTP + IMAP (Google Workspace,
Zoho, Fastmail, Migadu...). Both parse replies the same way.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import json
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from ..config import CompanySettings, EmailSettings
from ..db import utcnow

# Any plus-address carries the thread token: "reply+ab12cd@..." on a real sending domain,
# "you+ab12cd@gmail.com" when testing through a personal mailbox.
TOKEN_IN_ADDR = re.compile(r"[^@\s]+\+([a-z0-9]+)@", re.I)
TOKEN_IN_MSGID = re.compile(r"<([a-z0-9]+)\.(\d+)@", re.I)


@dataclass
class OutboundEmail:
    to: str
    subject: str
    text: str
    html: str | None
    message_id: str
    thread_token: str
    from_addr: str
    from_name: str
    reply_domain: str
    in_reply_to: str | None = None
    unsubscribe_url: str | None = None
    reply_local_part: str = "reply"

    @property
    def reply_to(self) -> str:
        return f"{self.reply_local_part}+{self.thread_token}@{self.reply_domain}"

    def as_mime(self) -> EmailMessage:
        m = EmailMessage()
        m["From"] = f"{self.from_name} <{self.from_addr}>"
        m["To"] = self.to
        m["Subject"] = self.subject
        m["Message-ID"] = self.message_id
        m["Reply-To"] = self.reply_to
        m["Date"] = email.utils.formatdate(localtime=False)
        if self.in_reply_to:
            m["In-Reply-To"] = self.in_reply_to
            m["References"] = self.in_reply_to
        if self.unsubscribe_url:
            m["List-Unsubscribe"] = f"<{self.unsubscribe_url}>, <mailto:{self.reply_to}?subject=unsubscribe>"
            m["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        m.set_content(self.text)
        if self.html:
            m.add_alternative(self.html, subtype="html")
        return m


@dataclass
class InboundEmail:
    from_addr: str
    to_addrs: list[str]
    subject: str
    text: str
    message_id: str | None
    in_reply_to: str | None
    references: list[str] = field(default_factory=list)
    received_at: str = field(default_factory=utcnow)
    raw_id: str | None = None

    def thread_token(self) -> str | None:
        for a in self.to_addrs:
            m = TOKEN_IN_ADDR.search(a)
            if m:
                return m.group(1).lower()
        for ref in [self.in_reply_to or "", *self.references]:
            m = TOKEN_IN_MSGID.search(ref)
            if m:
                return m.group(1).lower()
        return None

    def is_bounce(self) -> bool:
        f = self.from_addr.lower()
        return f.startswith(("mailer-daemon", "postmaster")) or "delivery status notification" in self.subject.lower() \
            or "undeliverable" in self.subject.lower()


def _decode(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:  # noqa: BLE001
        return v


def _strip_quoted(text: str) -> str:
    """Drop quoted history so the classifier sees only the new words."""
    lines = []
    for line in text.splitlines():
        if line.strip().startswith(">"):
            continue
        if re.match(r"^\s*(On .{5,120} wrote:|-----Original Message-----|From: .+|Sent from my )", line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def parse_mime(raw: bytes, raw_id: str | None = None) -> InboundEmail:
    msg = email.message_from_bytes(raw)
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and not part.get("Content-Disposition", "").startswith("attachment"):
                text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                break
        if not text:
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    break
    else:
        payload = msg.get_payload(decode=True)
        text = payload.decode(msg.get_content_charset() or "utf-8", "replace") if payload else ""
    tos = [addr for _, addr in email.utils.getaddresses(
        [_decode(msg.get("To", "")), _decode(msg.get("Cc", "")), _decode(msg.get("Delivered-To", "")), _decode(msg.get("X-Original-To", ""))]
    ) if addr]
    from_addr = email.utils.parseaddr(_decode(msg.get("From", "")))[1]
    refs = (msg.get("References") or "").split()
    return InboundEmail(
        from_addr=from_addr, to_addrs=tos, subject=_decode(msg.get("Subject")), text=_strip_quoted(text),
        message_id=msg.get("Message-ID"), in_reply_to=msg.get("In-Reply-To"), references=refs, raw_id=raw_id,
    )


class EmailProvider(Protocol):
    name: str
    def send(self, mail: OutboundEmail) -> str: ...
    def fetch_inbound(self) -> list[InboundEmail]: ...


class ConsoleProvider:
    name = "console"

    def __init__(self, workdir: Path):
        self.outbox = Path(workdir) / "outbox"
        self.inbox = Path(workdir) / "inbox"
        self.processed = self.inbox / "processed"
        for d in (self.outbox, self.inbox, self.processed):
            d.mkdir(parents=True, exist_ok=True)

    def send(self, mail: OutboundEmail) -> str:
        safe = re.sub(r"[^a-z0-9.]+", "_", mail.message_id.strip("<>").lower())
        path = self.outbox / f"{safe}.json"
        path.write_text(json.dumps({
            "to": mail.to, "from": f"{mail.from_name} <{mail.from_addr}>", "reply_to": mail.reply_to,
            "subject": mail.subject, "message_id": mail.message_id, "in_reply_to": mail.in_reply_to,
            "text": mail.text, "sent_at": utcnow(),
        }, indent=1))
        (self.outbox / f"{safe}.eml").write_bytes(mail.as_mime().as_bytes())
        return f"console:{path.name}"

    def simulate_reply(self, *, thread_token: str, from_addr: str, text: str, subject: str = "Re: your note",
                       reply_domain: str = "example.invalid") -> Path:
        """Drop a fake inbound reply into the inbox directory (tests, demos, the CLI)."""
        path = self.inbox / f"{thread_token}-{abs(hash(text)) % 10_000_000}.json"
        path.write_text(json.dumps({
            "from": from_addr, "to": [f"reply+{thread_token}@{reply_domain}"], "subject": subject, "text": text,
            "message_id": f"<sim-{path.stem}@{from_addr.split('@')[-1]}>",
        }))
        return path

    def fetch_inbound(self) -> list[InboundEmail]:
        out: list[InboundEmail] = []
        for path in sorted(self.inbox.glob("*.json")):
            data = json.loads(path.read_text())
            out.append(InboundEmail(
                from_addr=data["from"], to_addrs=list(data.get("to", [])), subject=data.get("subject", ""),
                text=_strip_quoted(data.get("text", "")), message_id=data.get("message_id"),
                in_reply_to=data.get("in_reply_to"), references=data.get("references", []), raw_id=path.name,
            ))
            path.rename(self.processed / path.name)
        for path in sorted(self.inbox.glob("*.eml")):
            out.append(parse_mime(path.read_bytes(), raw_id=path.name))
            path.rename(self.processed / path.name)
        return out


class SmtpImapProvider:
    name = "smtp"

    def __init__(self, settings: EmailSettings, company: CompanySettings):
        self.s = settings
        self.company = company

    def send(self, mail: OutboundEmail) -> str:
        mime = mail.as_mime()
        ctx = ssl.create_default_context()
        if self.s.smtp_port == 465:
            with smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, context=ctx, timeout=30) as smtp:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(mime)
        else:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                smtp.starttls(context=ctx)
                smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(mime)
        return f"smtp:{mail.message_id}"

    def fetch_inbound(self) -> list[InboundEmail]:
        out: list[InboundEmail] = []
        with imaplib.IMAP4_SSL(self.s.imap_host) as imap:
            imap.login(self.s.imap_user, self.s.imap_password)
            imap.select(self.s.imap_folder)
            status, data = imap.search(None, "UNSEEN")
            if status != "OK":
                return out
            for num in data[0].split():
                status, parts = imap.fetch(num, "(RFC822)")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                out.append(parse_mime(parts[0][1], raw_id=num.decode()))
                imap.store(num, "+FLAGS", "\\Seen")
        return out


def build_provider(settings) -> EmailProvider:  # type: ignore[no-untyped-def]
    if settings.email.provider == "smtp":
        return SmtpImapProvider(settings.email, settings.company)
    return ConsoleProvider(settings.workdir)
