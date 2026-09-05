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
    provider: Literal["claude", "fake"] = "claude"
    model: str = "claude-opus-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 16_000


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
    user_agent: str = "Mozilla/5.0 (compatible; ComplianceEngineBot/0.1; +https://example.invalid/bot)"


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
    outreach: OutreachSettings = OutreachSettings()
    llm: LLMSettings = LLMSettings()
    email: EmailSettings = EmailSettings()
    stripe: StripeSettings = StripeSettings()
    prospecting: ProspectingSettings = ProspectingSettings()
    dashboard: DashboardSettings = DashboardSettings()
    scanning: ScanningSettings = ScanningSettings()

    # ---- derived gates -------------------------------------------------
    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def can_send_email(self) -> tuple[bool, str]:
        """Whether the transport may deliver at all. The console provider never leaves the
        machine, so it is always allowed; SMTP needs live mode and a verified domain."""
        if self.email.provider == "console":
            return True, "console provider (writes to the outbox directory, nothing is emailed)"
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
        if not self.is_live:
            return False, "mode is dry_run"
        if not self.autonomy.auto_send_checkout:
            return False, "autonomy.auto_send_checkout is off"
        if not self.stripe.secret_key:
            return False, "stripe.secret_key missing"
        return True, "ok"

    def can_apply_fixes(self) -> tuple[bool, str]:
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
