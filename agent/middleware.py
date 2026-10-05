"""AgentOps middleware (Lab 3): токен-бюджет з hard-stop, circuit breaker для tools і алерти (Discord/Slack).

Підключається до LangGraph як callback handler з raise_error=True: виняток із handler-а
зупиняє прогін агента (hard-stop), а не лише логується.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

from langchain_core.callbacks import BaseCallbackHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERT_LOG = os.path.join(ROOT, "logs", "alerts.jsonl")

# умовний тариф Claude Haiku 4.5, $ за 1M токенів (Ollama безкоштовна)
PRICE_IN = float(os.getenv("PRICE_IN_PER_M", "1.0")) / 1e6
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_M", "5.0")) / 1e6

CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"


class StopRun(Exception):
    """Базовий виняток hard-stop-у агента."""


class BudgetExceeded(StopRun):
    pass


class CircuitOpenError(StopRun):
    pass


def find_stop(exc: BaseException) -> StopRun | None:
    """Знаходить StopRun, навіть якщо його загорнуто в ExceptionGroup (anyio/MCP)."""
    if isinstance(exc, StopRun):
        return exc
    for sub in getattr(exc, "exceptions", ()) or ():
        found = find_stop(sub)
        if found:
            return found
    return exc.__cause__ and find_stop(exc.__cause__) or None


def send_alert(title: str, fields: dict) -> bool:
    """Шле алерт у Discord (DISCORD_WEBHOOK_URL) і/або Slack (SLACK_WEBHOOK_URL) через webhook.
    Без жодного URL — dry-run у stderr. Завжди пише logs/alerts.jsonl."""
    record = {"ts": datetime.now(timezone.utc).isoformat(), "title": title, **fields}
    os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    lines = "\n".join(f"• **{k}:** {v}" for k, v in fields.items())
    targets = {  # webhook env -> (markdown-текст, ключ JSON)
        "DISCORD_WEBHOOK_URL": (f"🚨 **{title}**\n{lines}"[:1990], "content"),
        "SLACK_WEBHOOK_URL": (f":rotating_light: *{title}*\n{lines.replace('**', '*')}", "text"),
    }
    sent = False
    for env, (text, key) in targets.items():
        url = os.getenv(env, "").strip()
        if not url:
            continue
        # Discord відхиляє дефолтний User-Agent urllib (403), тому задаємо свій
        req = urllib.request.Request(url, data=json.dumps({key: text}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "agentops-alerts/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                sent = sent or resp.status in (200, 204)
            print(f"[ALERT] відправлено ({env.split('_')[0]}): {title}", file=sys.stderr)
        except Exception as e:  # алерт не має ламати агента
            print(f"[ALERT] помилка відправки ({env}): {e}", file=sys.stderr)
    if not sent and not any(os.getenv(e, "").strip() for e in targets):
        print(f"[ALERT DRY-RUN] webhook не задано\n🚨 {title}\n{lines}", file=sys.stderr)
    return sent


class CircuitBreaker:
    """CLOSED -> OPEN при > threshold послідовних збоїв tool-ів; після cooldown — HALF_OPEN (одна пробна спроба)."""

    def __init__(self, threshold: int, cooldown_s: float, on_open=None):
        self.threshold, self.cooldown_s, self.on_open = threshold, cooldown_s, on_open
        self.state, self.failures, self.opened_at, self.last_error = CLOSED, 0, 0.0, ""

    def before_call(self, tool: str) -> None:
        if self.state == OPEN:
            if time.monotonic() - self.opened_at >= self.cooldown_s:
                self.state = HALF_OPEN
            else:
                raise CircuitOpenError(f"circuit breaker OPEN: виклик '{tool}' заблоковано")

    def record_success(self) -> None:
        self.failures, self.state = 0, CLOSED

    def record_failure(self, tool: str, error: str) -> None:
        self.failures += 1
        self.last_error = f"{tool}: {error[:200]}"
        if self.state == HALF_OPEN or self.failures > self.threshold:
            self.state, self.opened_at = OPEN, time.monotonic()
            if self.on_open:
                self.on_open(self)
            raise CircuitOpenError(
                f"circuit breaker OPEN після {self.failures} послідовних збоїв (поріг {self.threshold})")


class AgentOpsMiddleware(BaseCallbackHandler):
    raise_error = True  # без цього LangChain ковтає винятки callback-ів

    def __init__(self, script: str = "", thread_id: str = ""):
        self.script, self.thread_id = script, thread_id
        self.budget = float(os.getenv("BUDGET_USD", "0.15"))
        self.cost = 0.0
        self.tokens_in = self.tokens_out = 0
        self.breaker = CircuitBreaker(int(os.getenv("BREAKER_THRESHOLD", "3")),
                                      float(os.getenv("BREAKER_COOLDOWN_S", "30")), on_open=self._alert_breaker)

    # --- допоміжне ---
    def _context(self) -> dict:
        return {"script": self.script, "thread_id": self.thread_id, "cost_usd": f"{self.cost:.6f}",
                "budget_usd": self.budget, "tokens": f"in={self.tokens_in} out={self.tokens_out}"}

    def _alert_breaker(self, br: CircuitBreaker) -> None:
        send_alert("Circuit breaker: стан змінено на OPEN", {
            "state": "→ OPEN",
            "consecutive_failures": f"{br.failures} (поріг {br.threshold})",
            "last_error": br.last_error, **self._context()})

    @staticmethod
    def _text(output) -> str:
        content = getattr(output, "content", output)
        if isinstance(content, list):
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return str(content)

    def _check_budget(self) -> None:
        if self.cost > self.budget:
            send_alert("Бюджет перевищено: агента зупинено (hard-stop)", {
                "reason": f"cost ${self.cost:.6f} > ліміт ${self.budget}", **self._context()})
            raise BudgetExceeded(f"token budget exceeded: ${self.cost:.6f} > ${self.budget}")

    # --- LLM: облік токенів ---
    def on_chat_model_start(self, serialized, messages, **kwargs):
        if self.cost > self.budget:  # бюджет уже вичерпано — нового LLM-виклику не буде
            self._check_budget()

    def on_llm_end(self, response, **kwargs):
        tin = tout = 0
        for gens in response.generations:
            for g in gens:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                tin += usage.get("input_tokens", 0)
                tout += usage.get("output_tokens", 0)
        if not (tin or tout):
            usage = (response.llm_output or {}).get("token_usage", {})
            tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        self.tokens_in += tin
        self.tokens_out += tout
        self.cost += tin * PRICE_IN + tout * PRICE_OUT
        self._check_budget()

    # --- tools: circuit breaker ---
    def on_tool_start(self, serialized, input_str, **kwargs):
        self.breaker.before_call((serialized or {}).get("name", "tool"))

    def on_tool_end(self, output, **kwargs):
        text = self._text(output)
        name = kwargs.get("name") or getattr(output, "name", "tool")
        if text.startswith("ПОМИЛКА"):
            self.breaker.record_failure(name, text)
        else:
            self.breaker.record_success()

    def on_tool_error(self, error, **kwargs):
        self.breaker.record_failure(kwargs.get("name") or "tool", repr(error))
