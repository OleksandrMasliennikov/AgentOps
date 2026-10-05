"""Детермінований тест middleware без LLM: бюджет, circuit breaker, алерти (реальні, якщо задано DISCORD_WEBHOOK_URL)."""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
os.environ["BUDGET_USD"] = "0.15"
os.environ["BREAKER_THRESHOLD"] = "2"
os.environ["BREAKER_COOLDOWN_S"] = "1"

from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, LLMResult  # noqa: E402
from middleware import AgentOpsMiddleware, BudgetExceeded, CircuitOpenError  # noqa: E402

failed = 0


def check(name, cond):
    global failed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    failed += not cond


def llm_result(tin, tout):
    msg = AIMessage(content="x", usage_metadata={"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout})
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    return False


rid = uuid.uuid4

# 1. Бюджет: тариф $1/$5 за 1M => 100k in + 10k out = $0.15 (на межі, ще ОК); +1k out => перевищення
mw = AgentOpsMiddleware("selftest_budget", "t1")
mw.on_llm_end(llm_result(100_000, 10_000), run_id=rid())
check(f"Бюджет: ${mw.cost:.4f} <= $0.15 — продовжуємо", mw.cost <= 0.15 + 1e-9)
check("Бюджет: наступний виклик перевищує ліміт -> BudgetExceeded", raises(BudgetExceeded, mw.on_llm_end, llm_result(0, 1_000), run_id=rid()))
check("Бюджет: новий LLM-виклик після вичерпання заблоковано", raises(BudgetExceeded, mw.on_chat_model_start, {}, [], run_id=rid()))

# 2. Circuit breaker: поріг 2 => OPEN на 3-му послідовному збої
mw = AgentOpsMiddleware("selftest_breaker", "t2")
err = "ПОМИЛКА: шлях 'nope.txt' не існує."
mw.on_tool_end(err, run_id=rid(), name="read_file")
mw.on_tool_end(err, run_id=rid(), name="read_file")
check("Breaker: після 2 збоїв ще CLOSED", mw.breaker.state == "CLOSED")
check("Breaker: 3-й збій -> OPEN + алерт у Discord", raises(CircuitOpenError, mw.on_tool_end, err, run_id=rid(), name="read_file") and mw.breaker.state == "OPEN")
check("Breaker: виклики tool-ів заблоковано поки OPEN", raises(CircuitOpenError, mw.on_tool_start, {"name": "read_file"}, "{}", run_id=rid()))
time.sleep(1.1)
mw.on_tool_start({"name": "read_file"}, "{}", run_id=rid())
check("Breaker: після cooldown -> HALF_OPEN", mw.breaker.state == "HALF_OPEN")
mw.on_tool_end("file content", run_id=rid(), name="read_file")
check("Breaker: успіх у HALF_OPEN -> CLOSED", mw.breaker.state == "CLOSED")

# 3. Успіх скидає лічильник
mw = AgentOpsMiddleware("selftest_reset", "t3")
mw.on_tool_end(err, run_id=rid(), name="read_file")
mw.on_tool_end("ok", run_id=rid(), name="read_file")
check("Breaker: успіх скидає лічильник збоїв", mw.breaker.failures == 0)
sys.exit(1 if failed else 0)
