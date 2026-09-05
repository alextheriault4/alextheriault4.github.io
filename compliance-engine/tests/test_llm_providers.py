"""The Claude Code provider: subscription auth, structured output, and how failures are typed.

A stub `claude` binary stands in for the real CLI so these tests are free, fast, and can
force the failure modes (usage limit, malformed output) that are hard to provoke live.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from engine import schemas
from engine.config import LLMSettings
from engine.llm import ClaudeCodeLLM, LLMCapacityError, LLMError, build_llm, inline_schema

RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.017,
    "usage": {"input_tokens": 2, "output_tokens": 90},
}


def make_stub(tmp_path: Path, payload: dict, exit_code: int = 0, stderr: str = "") -> Path:
    """A fake `claude` that records its argv and env, then prints one JSON line."""
    out = tmp_path / "calls.json"
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(payload))
    script = tmp_path / "claude"
    script.write_text(f"""#!/usr/bin/env python3
import json, os, sys
json.dump({{"argv": sys.argv[1:], "has_api_key": "ANTHROPIC_API_KEY" in os.environ}}, open({str(out)!r}, "w"))
sys.stderr.write({stderr!r})
print(open({str(payload_file)!r}).read())
sys.exit({exit_code})
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def settings_for(script: Path, **kw) -> LLMSettings:
    return LLMSettings(provider="claude_code", claude_binary=str(script), max_attempts=2, **kw)


def test_structured_call_uses_subscription_and_cache_friendly_flags(tmp_path, monkeypatch):
    payload = {**RESULT, "structured_output": {"intent": "accept", "confidence": 0.9,
                                               "summary": "wants to buy", "questions": [], "wants_call": False}}
    script = make_stub(tmp_path, payload)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-passed-through")

    llm = ClaudeCodeLLM(settings_for(script))
    out = llm.structured(system="classify", user="hello", schema=schemas.ReplyClassification,
                         effort="low", model="claude-sonnet-5")

    assert out.intent == "accept" and out.confidence == 0.9
    assert llm.last_cost_usd == 0.017 and llm.total_cost_usd == 0.017

    call = json.loads((tmp_path / "calls.json").read_text())
    # The point of this provider: bill the subscription, not an API key.
    assert call["has_api_key"] is False
    argv = call["argv"]
    assert argv[0] == "-p" and argv[1] == "hello"
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in argv, flag
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    assert argv[argv.index("--effort") + 1] == "low"
    # Replacing (not appending to) the system prompt keeps the cached prefix small and stable.
    assert argv[argv.index("--system-prompt") + 1] == "classify"
    assert "--append-system-prompt" not in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "$ref" not in json.dumps(schema) and schema["properties"]["intent"]["enum"]


def test_usage_limit_is_a_capacity_error_not_a_failure(tmp_path):
    """Hitting the subscription limit must never look like a broken lead."""
    payload = {**RESULT, "subtype": "error_during_execution", "is_error": True,
               "result": "You have reached your usage limit. Try again later."}
    llm = ClaudeCodeLLM(settings_for(make_stub(tmp_path, payload)))
    with pytest.raises(LLMCapacityError):
        llm.structured(system="s", user="u", schema=schemas.ReplyClassification)


def test_budget_cap_is_a_capacity_error(tmp_path):
    payload = {**RESULT, "subtype": "error_max_budget", "is_error": True, "result": ""}
    llm = ClaudeCodeLLM(settings_for(make_stub(tmp_path, payload)))
    with pytest.raises(LLMCapacityError):
        llm.structured(system="s", user="u", schema=schemas.ReplyClassification)


def test_plain_text_json_is_salvaged(tmp_path):
    """If the CLI hands back a fenced JSON block instead of structured output, use it."""
    fenced = {**RESULT, "result": '```json\n{"title": "A Title Here", "description": "d"}\n```'}
    llm = ClaudeCodeLLM(settings_for(make_stub(tmp_path, fenced)))
    assert llm.structured(system="s", user="u", schema=schemas.MetaCopy).title == "A Title Here"


def test_unusable_output_retries_then_raises_a_plain_error(tmp_path):
    other = tmp_path / "b"
    other.mkdir()
    llm = ClaudeCodeLLM(settings_for(make_stub(other, {**RESULT, "result": "not json at all"})))
    with pytest.raises(LLMError) as e:
        llm.structured(system="s", user="u", schema=schemas.MetaCopy)
    assert not isinstance(e.value, LLMCapacityError)  # a broken response is not a capacity problem


def test_missing_binary_is_explained_not_crashed():
    with pytest.raises(LLMError, match="not on PATH"):
        build_llm(LLMSettings(provider="claude_code", claude_binary="definitely-not-installed-xyz"))


def test_nested_schema_is_inlined_for_the_cli():
    schema = inline_schema(schemas.BusinessProfile)
    blob = json.dumps(schema)
    assert "$ref" not in blob and "$defs" not in blob
    faq = schema["properties"]["faq"]["items"]
    assert set(faq["properties"]) == {"question", "answer"}
    assert faq["additionalProperties"] is False
