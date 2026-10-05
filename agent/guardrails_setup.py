"""Guardrails AI: кастомні валідатори (без Guardrails Hub) і допоміжні функції.

Три захисти:
  - redact_pii(text)        — Guard на фінальну відповідь (PII маскується);
  - check_url(url)          — allowlist доменів для tool-викликів;
  - check_injection(text)   — prompt injection у вмісті, який повертають tools.
Кожне блокування пишеться в JSONL-лог (log_file з конфігу).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import yaml
from guardrails import Guard, OnFailAction
from guardrails.validators import FailResult, PassResult, Validator, register_validator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
with open(os.getenv("GUARDRAILS_CONFIG", os.path.join(HERE, "guardrails_config.yaml")), encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

LOG_PATH = os.getenv("GUARDRAILS_LOG", os.path.join(ROOT, CONFIG["log_file"]))
SCAN_TOOL_OUTPUT = os.getenv("GUARDRAILS_SCAN_TOOL_OUTPUT", str(CONFIG["tools"]["scan_tool_output"])).lower() in (
    "1", "true", "yes")


def log_block(guard: str, detail: str, sample: str = "") -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "guard": guard, "detail": detail, "sample": sample[:200]}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[GUARDRAILS] BLOCKED {guard}: {detail}", file=sys.stderr)


@register_validator(name="agentops/pii_redactor", data_type="string")
class PiiRedactor(Validator):
    """Знаходить PII за regex-ами і пропонує fix_value із замаскованими значеннями."""

    def __init__(self, patterns: dict, on_fail=None, **kwargs):
        super().__init__(on_fail=on_fail, **kwargs)
        self._patterns = {name: re.compile(rx) for name, rx in patterns.items()}

    def _validate(self, value, metadata):
        fixed, found = value, []
        for name, rx in self._patterns.items():
            fixed, n = rx.subn(f"<{name}>", fixed)
            if n:
                found.append(f"{name}x{n}")
        if found:
            return FailResult(error_message="PII у відповіді: " + ", ".join(found), fix_value=fixed)
        return PassResult()


@register_validator(name="agentops/allowed_domain", data_type="string")
class AllowedDomain(Validator):
    """Дозволяє лише https-URL з доменів allowlist (та їхніх піддоменів)."""

    def __init__(self, allowed_domains: list, on_fail=None, **kwargs):
        super().__init__(on_fail=on_fail, **kwargs)
        self._allowed = [d.lower() for d in allowed_domains]

    def _validate(self, value, metadata):
        u = urlparse(value.strip())
        host = (u.hostname or "").lower()
        if u.scheme != "https":
            return FailResult(error_message=f"схема '{u.scheme}' не дозволена (лише https)")
        if not any(host == d or host.endswith("." + d) for d in self._allowed):
            return FailResult(error_message=f"домен '{host}' не в allowlist")
        return PassResult()


@register_validator(name="agentops/no_prompt_injection", data_type="string")
class NoPromptInjection(Validator):
    """Евристичний детектор prompt injection за regex-ами."""

    def __init__(self, patterns: list, on_fail=None, **kwargs):
        super().__init__(on_fail=on_fail, **kwargs)
        self._patterns = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]

    def _validate(self, value, metadata):
        for rx in self._patterns:
            m = rx.search(value)
            if m:
                return FailResult(error_message=f"ознака prompt injection: '{m.group(0)[:80]}'")
        return PassResult()


_tools = CONFIG["tools"]
pii_guard = Guard(name="pii_output").use(
    PiiRedactor(patterns=CONFIG["output"]["pii"]["patterns"], on_fail=OnFailAction.FIX))
url_guard = Guard(name="url_allowlist").use(
    AllowedDomain(allowed_domains=_tools["allowed_domains"], on_fail=OnFailAction.NOOP))
injection_guard = Guard(name="prompt_injection").use(
    NoPromptInjection(patterns=_tools["injection_patterns"], on_fail=OnFailAction.NOOP))


def _error(outcome) -> str:
    summaries = getattr(outcome, "validation_summaries", None) or []
    return "; ".join(s.failure_reason or "" for s in summaries) or str(getattr(outcome, "error", "") or "невалідно")


def redact_pii(text: str) -> str:
    outcome = pii_guard.validate(text)
    out = outcome.validated_output if outcome.validated_output is not None else text
    if out != text:
        log_block("pii_output", _error(outcome), text)
    return out


def check_url(url: str) -> str | None:
    """None, якщо URL дозволений; інакше причина блокування."""
    outcome = url_guard.validate(url)
    if outcome.validation_passed:
        return None
    reason = _error(outcome)
    log_block("url_allowlist", reason, url)
    return reason


def check_injection(text: str, source: str = "") -> str | None:
    """None, якщо вміст чистий; інакше причина блокування."""
    if not SCAN_TOOL_OUTPUT:
        return None
    outcome = injection_guard.validate(text)
    if outcome.validation_passed:
        return None
    reason = _error(outcome)
    log_block("prompt_injection", f"{reason} (джерело: {source})", text)
    return reason
