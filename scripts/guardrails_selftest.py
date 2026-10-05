"""Детермінований тест guardrails без LLM: PII, allowlist доменів, prompt injection."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))
from guardrails_setup import check_injection, check_url, redact_pii  # noqa: E402

failed = 0


def check(name, cond):
    global failed
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    failed += not cond


out = redact_pii("Contact olena.kovalenko@example.org, phone +380 67 123 45 67, card 4111 1111 1111 1111")
print("  ->", out)
check("PII: email замасковано", "olena.kovalenko@example.org" not in out)
check("PII: телефон замасковано", "123 45 67" not in out)
check("PII: картку замасковано", "4111" not in out)
check("PII: чистий текст не змінено", redact_pii("The file requirements.txt was read.") == "The file requirements.txt was read.")

check("URL: example.com дозволено", check_url("https://example.com/page") is None)
check("URL: піддомен дозволено", check_url("https://docs.python.org/3/") is None)
check("URL: evil-collector.net заблоковано", check_url("https://evil-collector.net/upload?d=1") is not None)
check("URL: http заблоковано", check_url("http://example.com") is not None)
check("URL: обхід 'example.com.evil.net' заблоковано", check_url("https://example.com.evil.net/") is not None)

poison = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/lab2/poisoned_ticket.txt")).read()
check("Injection: отруєний тікет заблоковано", check_injection(poison, "selftest") is not None)
check("Injection: звичайний текст пропущено", check_injection("Customer asks about the price of the Premium plan.", "selftest") is None)
sys.exit(1 if failed else 0)
