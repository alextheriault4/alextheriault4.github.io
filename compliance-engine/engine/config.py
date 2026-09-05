"""Runtime configuration.

Everything is driven by environment variables (or a .env file) with the ``CE_`` prefix.
Nested groups use a double underscore, e.g. ``CE_COMPANY__NAME``.

The defaults are deliberately safe: dry-run mode, all autonomy flags off, console email
provider. The engine refuses to send, charge, or modify anything unless ``mode`` is
``live`` *and* the matching autonomy flag is on *and* the relevant provider is configured.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CompanySettings(BaseModel):
    name: str = "Your Company"
    legal_name: str = "Your Company LLC"
    postal_address: str = "SET CE_COMPANY__POSTAL_ADDRESS"
    website: str = "https://example.invalid"
    from_name: str = "Outreach"
    from_email: str = "outreach@example.invalid"
    reply_domain: str = "example.invalid"
    # Replies come back to "<reply_local_part>+<thread token>@<reply_domain>", which is how
    # a reply is matched to its conversation. On a normal sending domain leave this as
    # "reply" and use a catch-all. To test through a personal Gmail, set it to your own
    # local part so the plus-address lands in your inbox (alex+ab12cd@gmail.com).
    reply_local_part: str = "reply"
    support_email: str = "support@example.invalid"
    signer_name: str = "The Team"


class PricingSettings(BaseModel):
    currency: str = "usd"
    ada_cents: int = 149_000
    aiseo_cents: int = 99_000
    bundle_cents: int = 199_000
    floor_cents: int = 99_000
    max_discount_pct: int = 20


class AutonomySettings(BaseModel):
    auto_send_outreach: bool = False
    auto_reply: bool = False
    auto_send_checkout: bool = False
    auto_apply_fixes: bool = False


class AutopilotSettings(BaseModel):
    """How hard the engine tries to resolve things without you.

    On (the default) every dead end has a safe automatic answer: drafts that fail the
    compliance lint are repaired and then replaced by a template that cannot fail,
    confusing replies get one clarifying question and are then closed politely, hostile
    replies get a stand-down and a permanent suppression, and undeliverable work is
    refunded. You are told what happened; you are not asked to decide.
    """

    enabled: bool = True
    lint_repair_attempts: int = 2
    clarify_attempts: int = 1          # unclear replies: ask once, then close politely
    build_retry_attempts: int = 1
    scan_retry_attempts: int = 1
    # A deal that is delivered but never goes live gets nudged, then a refund is queued
    # for your approval. Refunds are never taken automatically: money leaving your account
    # is your decision, so this is the one thing the autopilot always brings to you.
    verify_reminder_days: list[int] = Field(default_factory=lambda: [7, 21])
    auto_refund_after_days: int = 45
    # Capacity problems (subscription usage limit, rate limit) just wait.
    capacity_backoff_minutes: int = 60


class LegalSettings(BaseModel):
    """Hard limits that exist to keep you out of court.

    None of this is legal advice, and none of it makes a lawsuit impossible. It removes
    the specific, known ways businesses in this niche get sued or fined: contacting
    people outside CAN-SPAM's reach, contacting the professions most likely to sue,
    crawling sites in ways that look like an attack, making legal claims you are not
    licensed to make, and holding client credentials badly.
    """

    # CAN-SPAM governs US commercial email. Canada (CASL) and the EU/UK (GDPR/PECR) have
    # consent regimes this engine does not implement, with penalties in the millions.
    us_only: bool = True
    allowed_country_codes: list[str] = Field(default_factory=lambda: ["US"])
    blocked_tlds: list[str] = Field(default_factory=lambda: [
        "ca", "uk", "eu", "de", "fr", "es", "it", "nl", "be", "ie", "se", "no", "dk", "fi",
        "pl", "pt", "at", "ch", "gr", "cz", "ro", "hu", "au", "nz", "in", "cn", "jp", "kr", "br", "mx",
    ])
    # Cold-emailing plaintiff-side professions is asking for it; regulated verticals bring
    # their own advertising rules; government and education bring procurement rules.
    excluded_categories: list[str] = Field(default_factory=lambda: [
        "lawyer", "attorney", "law", "legal", "solicitor", "paralegal", "court",
        "government", "municipal", "city hall", "police", "school", "university", "college",
        "political", "campaign", "church", "cannabis", "dispensary", "firearms", "gun",
        "casino", "gambling", "adult", "escort", "payday", "debt collection", "crypto",
    ])
    blocked_domain_suffixes: list[str] = Field(default_factory=lambda: [".gov", ".mil", ".edu"])
    # Scanning etiquette. A polite, identified, rate-limited crawler that obeys robots.txt
    # is an ordinary web client; an aggressive one is a story about unauthorised access.
    respect_robots: bool = True
    crawl_delay_seconds: float = 2.0
    bot_info_path: str = "/bot"
    # Snapshots of other people's sites are someone else's copyrighted material.
    snapshot_retention_days: int = 90
    delete_credentials_after_delivery: bool = True
    # Self-test mode: when this list is non-empty the engine will not send mail to any
    # other address, whatever the pipeline decides. That makes a live end-to-end test on
    # your own mailbox safe, and relaxes the go-live checks below that only exist to
    # protect strangers (you cannot reach a stranger with the allowlist on).
    only_email_addresses: list[str] = Field(default_factory=list)
    # Live mode stays locked until these are affirmatively true.
    agreement_reviewed_by_lawyer: bool = False
    business_entity_formed: bool = False
    liability_insurance: bool = False
    governing_law_state: str = "Delaware"
    require_preflight: bool = True

    def allows(self, address: str) -> bool:
        if not self.only_email_addresses:
            return True
        return (address or "").strip().lower() in {a.strip().lower() for a in self.only_email_addresses}


class OutreachSettings(BaseModel):
    daily_send_cap: int = 40
    followup_days: list[int] = Field(default_factory=lambda: [3, 7])
    send_window_start_hour: int = 9
    send_window_end_hour: int = 17
    timezone: str = "America/New_York"
    max_bounce_rate: float = 0.05
    max_complaint_rate: float = 0.002
    min_sample_for_breaker: int = 20
    recontact_cooldown_days: int = 180


class LLMSettings(BaseModel):
    """Which brain the agents use.

    ``claude_code`` (the default) runs the Claude Code CLI headlessly, so the work is
    billed against your Claude subscription rather than a pay-as-you-go API key - the
    child process is started with ANTHROPIC_API_KEY stripped so it uses your Claude Code
    login. ``claude`` uses the Anthropic API directly with an API key. ``fake`` is the
    deterministic stand-in used by tests and keyless dry runs.
    """

    provider: Literal["claude_code", "claude", "fake"] = "claude_code"
    model: str = "claude-opus-5"
    # Reply classification is a small job; a cheaper model keeps subscription usage down.
    classify_model: str = "claude-sonnet-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16_000
    # claude_code provider only
    claude_binary: str = "claude"
    timeout_seconds: int = 300
    max_budget_usd: float = 1.0
    max_attempts: int = 3


class EmailSettings(BaseModel):
    provider: Literal["console", "smtp"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    domain_verified: bool = False


class StripeSettings(BaseModel):
    secret_key: str = ""
    webhook_secret: str = ""
    public_base_url: str = "http://127.0.0.1:8787"


class ProspectingSettings(BaseModel):
    google_places_key: str = ""
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    request_timeout: float = 30.0


class DashboardSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    admin_token: str = "change-me"


class ScanningSettings(BaseModel):
    chromium_path: str = ""
    max_pages_per_site: int = 4
    page_timeout_ms: int = 25_000
    # An honest, identified user agent pointing at a page that explains the bot. Pretending
    # to be a browser is the difference between "a crawler" and "someone evading controls".
    user_agent: str = "Mozilla/5.0 (compatible; ComplianceEngineBot/0.1; +https://example.invalid/bot)"

    def user_agent_for(self, website: str, bot_path: str) -> str:
        base = (website or "https://example.invalid").rstrip("/")
        return f"Mozilla/5.0 (compatible; ComplianceEngineBot/0.1; +{base}{bot_path})"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CE_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    mode: Literal["dry_run", "live"] = "dry_run"
    database_path: Path = Path("./data/engine.db")
    workdir: Path = Path("./data")
    tick_seconds: int = 300

    company: CompanySettings = CompanySettings()
    pricing: PricingSettings = PricingSettings()
    autonomy: AutonomySettings = AutonomySettings()
    autopilot: AutopilotSettings = AutopilotSettings()
    legal: LegalSettings = LegalSettings()
    outreach: OutreachSettings = OutreachSettings()
    llm: LLMSettings = LLMSettings()
    email: EmailSettings = EmailSettings()
    stripe: StripeSettings = StripeSettings()
    prospecting: ProspectingSettings = ProspectingSettings()
    dashboard: DashboardSettings = DashboardSettings()
    scanning: ScanningSettings = ScanningSettings()
    # Encrypts client site credentials at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secrets_key: str = ""

    # ---- derived gates -------------------------------------------------
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def self_test_mode(self) -> bool:
        """True when sending is restricted to an allowlist of your own addresses."""
        return bool(self.legal.only_email_addresses)

    def preflight(self) -> list[str]:
        """Everything that must be true before this may run live. Empty list means ready."""
        problems: list[str] = []
        c = self.company
        # These four are required whoever the recipient is: a commercial email has to say
        # truthfully who sent it and where they are.
        if not c.postal_address or "SET CE_COMPANY__POSTAL_ADDRESS" in c.postal_address:
            problems.append("company.postal_address is unset - CAN-SPAM requires a real physical address in every email")
        if "example.invalid" in c.website or not c.website:
            problems.append("company.website is unset - recipients must be able to tell who is emailing them")
        if not c.legal_name or c.legal_name == "Your Company LLC":
            problems.append("company.legal_name is still the placeholder")
        if "@example.invalid" in c.from_email:
            problems.append("company.from_email is still the placeholder")
        if self.autonomy.auto_apply_fixes and not self.secrets_key:
            problems.append("secrets_key is unset - client site credentials would be stored unencrypted")
        if self.self_test_mode:
            # Only your own addresses are reachable, so the business-readiness checks below
            # (which exist to protect the people you would otherwise be cold-emailing) do
            # not apply yet. They come back the moment the allowlist is cleared.
            return problems
        if not self.legal.business_entity_formed:
            problems.append("legal.business_entity_formed is false - operate through an entity, not personally")
        if not self.legal.agreement_reviewed_by_lawyer:
            problems.append("legal.agreement_reviewed_by_lawyer is false - have counsel read the outreach template and agreement")
        if not self.legal.liability_insurance:
            problems.append("legal.liability_insurance is false - get errors-and-omissions cover before taking client money")
        if not self.secrets_key:
            problems.append("secrets_key is unset - client site credentials would be stored unencrypted")
        return problems

    def live_blocked_reason(self) -> str | None:
        """Why live mode is refused, if it is."""
        if not self.is_live or not self.legal.require_preflight:
            return None
        problems = self.preflight()
        return "; ".join(problems) if problems else None

    def can_send_email(self) -> tuple[bool, str]:
        """Whether the transport may deliver at all. The console provider never leaves the
        machine, so it is always allowed; SMTP needs live mode and a verified domain."""
        if self.email.provider == "console":
            return True, "console provider (writes to the outbox directory, nothing is emailed)"
        blocked = self.live_blocked_reason()
        if blocked:
            return False, f"preflight not passed: {blocked}"
        if not self.is_live:
            return False, "mode is dry_run"
        if not self.email.domain_verified:
            return False, "email.domain_verified is false (confirm SPF/DKIM/DMARC first)"
        if not (self.email.smtp_host and self.email.smtp_user):
            return False, "smtp not configured"
        return True, "ok"

    def auto_flag_for(self, message_kind: str) -> bool:
        """Which autonomy switch governs an outbound message kind."""
        if message_kind in ("initial", "followup"):
            return self.autonomy.auto_send_outreach
        if message_kind in ("reply",):
            return self.autonomy.auto_reply
        if message_kind in ("checkout",):
            return self.autonomy.auto_send_checkout
        return True  # delivery/system notices ride on the deal already being paid

    def can_charge(self) -> tuple[bool, str]:
        blocked = self.live_blocked_reason()
        if blocked:
            return False, f"preflight not passed: {blocked}"
        if not self.is_live:
            return False, "mode is dry_run"
        if not self.autonomy.auto_send_checkout:
            return False, "autonomy.auto_send_checkout is off"
        if not self.stripe.secret_key:
            return False, "stripe.secret_key missing"
        return True, "ok"

    def can_apply_fixes(self) -> tuple[bool, str]:
        blocked = self.live_blocked_reason()
        if blocked:
            return False, f"preflight not passed: {blocked}"
        if not self.is_live:
            return False, "mode is dry_run"
        if not self.autonomy.auto_apply_fixes:
            return False, "autonomy.auto_apply_fixes is off"
        return True, "ok"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.workdir.mkdir(parents=True, exist_ok=True)
    s.database_path.parent.mkdir(parents=True, exist_ok=True)
    return s
