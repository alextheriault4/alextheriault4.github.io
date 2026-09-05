"""Pydantic schemas for every structured model call.

Each agent asks the model for one of these shapes; the code around it does the
policy enforcement (pricing floors, compliance footer, forbidden claims), so the
model is never the last line of defence.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OutreachDraft(BaseModel):
    subject: str = Field(description="Plain, honest subject line. No urgency tricks, no 'Re:', no legal-sounding words.")
    opening: str = Field(description="One or two sentences that show we actually looked at their site.")
    findings_paragraph: str = Field(description="Plain-language summary of the 2-3 most important issues found.")
    exposure_paragraph: str = Field(description="What those issues can cost them, using ONLY the figures provided, labelled as estimates.")
    offer_paragraph: str = Field(description="What we do, the fixed price, what is included, and the turnaround.")
    call_to_action: str = Field(description="One sentence asking for a reply. No pressure language.")


class ReplyClassification(BaseModel):
    intent: Literal[
        "interested", "question", "objection_price", "objection_other", "not_interested",
        "unsubscribe", "wrong_person", "auto_reply", "bounce", "accept", "already_customer", "unclear",
    ]
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(description="One sentence: what the sender wants.")
    questions: list[str] = Field(default_factory=list, description="Verbatim questions the sender asked, if any.")
    counter_offer_cents: int | None = Field(default=None, description="If they named a price they'd pay, in cents.")
    wants_call: bool = False
    forwarded_to: str | None = Field(default=None, description="Email of the right person if they redirected us.")


class NegotiationReply(BaseModel):
    body_text: str = Field(description="The reply body only. No signature, no footer; the system appends those.")
    package: Literal["ada", "aiseo", "bundle"]
    proposed_price_cents: int = Field(description="Price we are now offering, in cents. Must respect the floor given.")
    ready_to_close: bool = Field(description="True only if the sender has clearly agreed to buy at a stated price.")
    escalate: bool = Field(default=False, description="True if a human must step in (legal threat, custom scope, anger, anything outside policy).")
    escalate_reason: str | None = None


class AltTextItem(BaseModel):
    src: str
    alt: str = Field(description="Concise, descriptive alt text; empty string if purely decorative.")


class AltTextBatch(BaseModel):
    items: list[AltTextItem]


class MetaCopy(BaseModel):
    title: str = Field(description="50-60 char page title with business name and locality.")
    description: str = Field(description="140-160 char meta description in plain language.")


class BusinessProfile(BaseModel):
    name: str
    description: str = Field(description="One paragraph describing the business for search engines and AI assistants.")
    business_type: str = Field(description="Best-fit schema.org LocalBusiness subtype, e.g. Dentist, Plumber, Restaurant, LegalService.")
    services: list[str] = Field(default_factory=list)
    phone: str | None = None
    street_address: str | None = None
    locality: str | None = None
    region: str | None = None
    postal_code: str | None = None
    faq: list[FAQItem] = Field(default_factory=list, description="Up to 5 plain Q&A pairs derived from the site's own content.")


class FAQItem(BaseModel):
    question: str
    answer: str


BusinessProfile.model_rebuild()
