"""Model access.

``ClaudeLLM`` is the production client (official Anthropic SDK, structured outputs via
``beta.messages.parse``, adaptive thinking, server-side refusal fallbacks).
``FakeLLM`` is a deterministic stand-in used by the test-suite and by dry runs on
machines without an API key. Both satisfy the same tiny ``LLM`` protocol so the rest
of the engine never knows which one it has.
"""
from __future__ import annotations

import json
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from . import schemas
from .config import LLMSettings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    """The model declined the request; the caller should escalate to a human, not retry."""


class LLM(Protocol):
    def structured(self, *, system: str, user: str, schema: type[T], effort: str | None = None) -> T: ...
    def text(self, *, system: str, user: str, effort: str | None = None) -> str: ...


class ClaudeLLM:
    def __init__(self, settings: LLMSettings):
        import anthropic  # imported lazily so the fake path needs no SDK

        self._anthropic = anthropic
        self.settings = settings
        self.client = anthropic.Anthropic()

    def _system_blocks(self, system: str) -> list[dict[str, Any]]:
        # Stable prefix first so repeated calls with the same system prompt hit the cache.
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    def structured(self, *, system: str, user: str, schema: type[T], effort: str | None = None) -> T:
        try:
            resp = self.client.beta.messages.parse(
                model=self.settings.model,
                max_tokens=self.settings.max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=self._system_blocks(system),
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": effort or self.settings.effort},
            )
        except self._anthropic.RateLimitError as e:
            raise LLMError(f"rate limited: {e}") from e
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"api error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMRefusal(getattr(getattr(resp, "stop_details", None), "explanation", "refused"))
        if resp.parsed_output is None:
            raise LLMError("model returned no parsed output")
        return resp.parsed_output

    def text(self, *, system: str, user: str, effort: str | None = None) -> str:
        try:
            resp = self.client.beta.messages.create(
                model=self.settings.model,
                max_tokens=self.settings.max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=self._system_blocks(system),
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort or self.settings.effort},
            )
        except self._anthropic.APIStatusError as e:
            raise LLMError(f"api error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMRefusal("refused")
        return "".join(b.text for b in resp.content if b.type == "text")


# --------------------------------------------------------------------------------------
# Deterministic fake
# --------------------------------------------------------------------------------------

def extract_context(user: str) -> dict[str, Any]:
    """Prompts embed their facts as a ```json block; the fake reads them back."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", user, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _money(cents: int | None) -> str:
    return f"${(cents or 0) / 100:,.0f}"


class FakeLLM:
    """Rule-based stand-in. Good enough to exercise every code path end to end."""

    def __init__(self, settings: LLMSettings | None = None):
        self.settings = settings
        self.calls: list[tuple[str, str]] = []
        self.canned: dict[str, list[BaseModel]] = {}

    def enqueue(self, response: BaseModel) -> None:
        self.canned.setdefault(type(response).__name__, []).append(response)

    def structured(self, *, system: str, user: str, schema: type[T], effort: str | None = None) -> T:
        self.calls.append((schema.__name__, user))
        queue = self.canned.get(schema.__name__)
        if queue:
            return queue.pop(0)  # type: ignore[return-value]
        ctx = extract_context(user)
        handler = getattr(self, f"_fake_{schema.__name__}", None)
        if handler is None:
            raise LLMError(f"FakeLLM has no handler for {schema.__name__}")
        return handler(ctx, user)

    def text(self, *, system: str, user: str, effort: str | None = None) -> str:
        self.calls.append(("text", user))
        return "OK"

    # -- handlers -------------------------------------------------------------
    def _fake_OutreachDraft(self, ctx: dict[str, Any], user: str) -> schemas.OutreachDraft:
        biz = ctx.get("business_name") or ctx.get("domain", "your business")
        issues = ctx.get("top_issues", [])[:3]
        issue_text = "; ".join(i.get("plain", i.get("rule_id", "")) for i in issues) or "several accessibility and search issues"
        exp = ctx.get("exposure", {})
        low, high = exp.get("ada_low_cents"), exp.get("ada_typical_cents")
        pkg = ctx.get("recommended_package", "bundle")
        price = ctx.get("price_cents", 0)
        return schemas.OutreachDraft(
            subject=f"A few fixable issues on {ctx.get('domain', 'your website')}",
            opening=f"I ran an automated check on {ctx.get('domain')} this week while looking at {ctx.get('category', 'local')} businesses in {ctx.get('city', 'your area')}.",
            findings_paragraph=f"The scan flagged {issue_text}. These are the kinds of gaps that keep screen-reader users from using the site and keep AI assistants from recommending {biz}.",
            exposure_paragraph=(
                f"For context: web-accessibility demand letters and suits against small businesses commonly settle in the "
                f"{_money(low)} to {_money(high)} range once legal fees are included (estimate, sources linked below)."
                if low and high else "These gaps have real costs, detailed below."
            ),
            offer_paragraph=f"We fix exactly what the report lists, for a flat {_money(price)} ({pkg} package), delivered within 10 business days, with a before-and-after rescan so you can see the difference.",
            call_to_action="If you'd like the full report or want us to go ahead, just reply to this email.",
        )

    def _fake_ReplyClassification(self, ctx: dict[str, Any], user: str) -> schemas.ReplyClassification:
        body = (ctx.get("reply_text") or user).lower()
        def has(*words: str) -> bool:
            return any(w in body for w in words)
        intent = "unclear"
        counter = None
        if has("unsubscribe", "remove me", "stop emailing", "take me off", "do not contact", "don't contact"):
            intent = "unsubscribe"
        elif has("undeliverable", "delivery failed", "mailer-daemon", "address not found", "550 "):
            intent = "bounce"
        elif has("out of office", "auto-reply", "automatic reply", "on vacation", "away from"):
            intent = "auto_reply"
        elif has("wrong person", "not the right person", "forward this to", "you should contact"):
            intent = "wrong_person"
        elif has("already have", "we already work with", "already compliant", "already hired"):
            intent = "already_customer"
        elif has("not interested", "no thanks", "no thank you", "please don't", "not at this time"):
            intent = "not_interested"
        elif has("go ahead", "let's do it", "lets do it", "sign me up", "send the link", "send me the link", "how do i pay", "we accept", "i accept", "sounds good, proceed", "send the invoice", "let's proceed"):
            intent = "accept"
        elif has("too expensive", "cheaper", "discount", "lower price", "budget", "can you do it for", "would you take"):
            intent = "objection_price"
            m = re.search(r"\$\s?(\d[\d,]*)", body)
            if m:
                counter = int(m.group(1).replace(",", "")) * 100
        elif has("interested", "tell me more", "send me the report", "more info", "more information"):
            intent = "interested"
        elif "?" in body:
            intent = "question"
        elif has("scam", "lawyer", "attorney", "legal action", "report you"):
            intent = "objection_other"
        questions = [s.strip() + "?" for s in re.split(r"[.!\n]", ctx.get("reply_text", "")) if "?" in s][:3]
        return schemas.ReplyClassification(
            intent=intent, confidence=0.85 if intent != "unclear" else 0.4,
            summary=f"Sender appears to be: {intent.replace('_', ' ')}.",
            questions=[q.replace("??", "?") for q in questions],
            counter_offer_cents=counter, wants_call=has("call me", "phone call", "give me a call"),
        )

    def _fake_NegotiationReply(self, ctx: dict[str, Any], user: str) -> schemas.NegotiationReply:
        intent = ctx.get("intent", "question")
        pkg = ctx.get("package", "bundle")
        current = int(ctx.get("current_price_cents", 0))
        floor = int(ctx.get("floor_cents", current))
        min_allowed = int(ctx.get("min_allowed_cents", floor))
        counter = ctx.get("counter_offer_cents")
        first = (ctx.get("contact_name") or "there")
        if intent == "accept":
            return schemas.NegotiationReply(
                body_text=f"Great, thank you. I'll send the secure payment link in a separate email right after this one. Once it's paid we start immediately and you'll have the before/after report within 10 business days.",
                package=pkg, proposed_price_cents=current, ready_to_close=True,
            )
        if intent == "objection_price":
            if counter and counter >= min_allowed:
                price = int(counter)
                body = f"Understood. I can do the {pkg} package for {_money(price)} flat, everything in the report included. If that works, reply 'go ahead' and I'll send the payment link."
            else:
                price = min_allowed
                body = f"I hear you on budget. The lowest I can go on the {pkg} package is {_money(price)}, which still covers every item in the report plus the verification rescan. If that works, reply 'go ahead' and I'll send the payment link."
            return schemas.NegotiationReply(body_text=body, package=pkg, proposed_price_cents=price, ready_to_close=False)
        if intent in ("objection_other",):
            return schemas.NegotiationReply(
                body_text="", package=pkg, proposed_price_cents=current, ready_to_close=False,
                escalate=True, escalate_reason="Non-price objection or hostile tone; human should review.",
            )
        # question / interested
        qs = ctx.get("questions") or []
        answer = " ".join(f"On '{q}': {ctx.get('faq_hint', 'happy to walk through the details; the short version is that we change only what the report lists and you approve every change before it goes live.')}" for q in qs[:2]) or "Happy to share more."
        return schemas.NegotiationReply(
            body_text=f"Hi {first}, thanks for getting back to me. {answer} The full report is attached as a link above. The {pkg} package is {_money(current)} flat; reply 'go ahead' whenever you're ready and I'll send the payment link.",
            package=pkg, proposed_price_cents=current, ready_to_close=False,
        )

    def _fake_AltTextBatch(self, ctx: dict[str, Any], user: str) -> schemas.AltTextBatch:
        items = []
        for src in ctx.get("images", []):
            stem = re.sub(r"[-_]+", " ", src.rsplit("/", 1)[-1].rsplit(".", 1)[0]).strip()
            decorative = any(w in stem.lower() for w in ("spacer", "divider", "bg", "background", "pixel"))
            items.append(schemas.AltTextItem(src=src, alt="" if decorative else (stem.capitalize() or "Image")))
        return schemas.AltTextBatch(items=items)

    def _fake_MetaCopy(self, ctx: dict[str, Any], user: str) -> schemas.MetaCopy:
        name = ctx.get("business_name") or ctx.get("domain", "Business")
        cat = ctx.get("category") or "local business"
        city = ctx.get("city") or ""
        title = f"{name} | {cat.title()}" + (f" in {city}" if city else "")
        desc = f"{name} is a {cat} serving {city or 'the local area'}. Contact us for services, hours and directions."
        return schemas.MetaCopy(title=title[:60], description=desc[:160])

    def _fake_BusinessProfile(self, ctx: dict[str, Any], user: str) -> schemas.BusinessProfile:
        name = ctx.get("business_name") or ctx.get("domain", "Business")
        cat = (ctx.get("category") or "LocalBusiness").replace(" ", "")
        return schemas.BusinessProfile(
            name=name,
            description=f"{name} is a {ctx.get('category', 'local business')} based in {ctx.get('city', 'the area')}.",
            business_type=cat[:1].upper() + cat[1:],
            services=ctx.get("services", [])[:5],
            phone=ctx.get("phone"), locality=ctx.get("city"), region=ctx.get("region"),
            faq=[schemas.FAQItem(question=f"What does {name} do?", answer=f"{name} provides {ctx.get('category', 'local')} services.")],
        )


def build_llm(settings: LLMSettings) -> LLM:
    if settings.provider == "fake":
        return FakeLLM(settings)
    return ClaudeLLM(settings)
