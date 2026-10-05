# Building a Reliable Customer Retention System (AgentOps)

Агент із теми 12 (LangGraph ReAct + MCP stdio, локальна Ollama `qwen2.5:7b`) перетворено на production-ready систему: observability, guardrails, SLA-контроль і регресійні тести в CI.

| Lab | Що зроблено | Основні файли |
|---|---|---|
| 1. Observability | Arize Phoenix (Docker), повне дерево трейсів, cost dashboard | [docker-compose.yml](docker-compose.yml), [agent/tracing.py](agent/tracing.py), [scripts/cost_report.py](scripts/cost_report.py) |
| 2. Guardrails | Guardrails AI: маскування PII, allowlist доменів, детектор prompt injection | [agent/guardrails_config.yaml](agent/guardrails_config.yaml), [agent/guardrails_setup.py](agent/guardrails_setup.py) |
| 3. SLA control | Hard-stop бюджету $0.15/run, circuit breaker, алерти в Discord | [agent/middleware.py](agent/middleware.py) |
| 4. Regression | Golden dataset (6 кейсів), threshold gate у GitHub Actions | [evals/](evals), [.github/workflows/eval.yml](.github/workflows/eval.yml) |

## Архітектура

```
 PR ──► GitHub Actions ──► evals/run_evals.py ──► agent ─┐
                                                         │
 користувач ─► agent/agent.py (LangGraph ReAct) ◄────────┘
                 │  callbacks: AgentOpsMiddleware (бюджет, circuit breaker ─► Discord)
                 │  вихід:     Guardrails (PII-маскування)
                 │  трейси:    OpenTelemetry ─► Phoenix :6006
                 ▼
          MCP server (stdio): read_file, list_directory, fetch_url
                 └─ Guardrails: allowlist доменів, скан вмісту на prompt injection
```

Принцип із теми 12: права перевіряє сервер, а не лише модель. Тому allowlist доменів і скан вмісту живуть у MCP-сервері.

## Запуск

Повний порядок команд: [RUNBOOK.md](RUNBOOK.md). Скорочено:

```bash
cp .env.example .env            # додай DISCORD_WEBHOOK_URL
make venv && make up            # залежності + Phoenix (http://localhost:6006)
make scenarios && make report   # Lab 1
make guardrails-test && make injection-test   # Lab 2
make middleware-test && make budget-demo && make breaker-demo   # Lab 3
make eval                       # Lab 4 (локально)
```

---

## Lab 1 — Full tracing setup

**Реалізація.** Phoenix піднято через Docker Compose. Агент інструментований через OpenInference (LangChain/LangGraph + MCP); кореневий спан `agent.run` має атрибут `script.name`. 6 різних сценаріїв ([scripts/run_scenarios.py](scripts/run_scenarios.py)) дали окремі трейси у проєкті `retention-agent`.

**Cost dashboard.** Ollama безкоштовна, тому Phoenix показує `$0`. Для `$/run` використано **умовний тариф Claude Haiku 4.5** ($1 / 1M вхідних, $5 / 1M вихідних токенів); токени беруться з LLM-спанів. Середня вартість ≈ **$0.0014/run**, найдорожчий сценарій `find_py` — $0.0024 (≈37 с). Виклики tool-ів < 0.02 с: час іде на LLM.

| Артефакт | |
|---|---|
| Проєкт Phoenix | `http://localhost:6006` → `retention-agent` (локальний, тому доказ — скріншоти) |
| Список трейсів | ![traces](docs/screenshots/lab1_traces_list.png) |
| Дерево трейсу (`agent.run → LangGraph → ChatOpenAI → tools → list_directory → ChatOpenAI`) | ![tree](docs/screenshots/lab1_trace_tree.png) |
| Cost dashboard (`$/run` за скриптами, latency спанів і tool-ів) | ![dashboard](docs/lab1/cost_dashboard.png) |

Дані: [cost_by_script.csv](docs/lab1/cost_by_script.csv), [tools.csv](docs/lab1/tools.csv), [scenarios.log](docs/lab1/scenarios.log).

## Lab 2 — Guardrails

**Реалізація** (кастомні валідатори Guardrails AI, конфіг у [guardrails_config.yaml](agent/guardrails_config.yaml)):

1. **PII у фінальній відповіді** — email, телефон, банківська картка, IBAN, SSN маскуються (`<EMAIL>` тощо).
2. **Allowlist доменів** для `fetch_url` — лише `https` і домени з allowlist; перевірка стійка до обходів (`example.com.evil.net`, `http://`).
3. **Prompt injection** — вміст, який повертають tools, скануватиметься за патернами; збіг блокується, а не передається моделі.

**Тест.** Агент читає отруєний тікет [poisoned_ticket.txt](docs/lab2/poisoned_ticket.txt), який просить вивантажити базу клієнтів на `evil-collector.net` і вивести email та картку. Guardrail блокує вміст ще до моделі; спроб exfiltration — 0, витоку PII немає (`РЕЗУЛЬТАТ: PASS`).

| | |
|---|---|
| Детермінований тест (11 перевірок, усі PASS) | ![selftest](docs/screenshots/lab2_guardrails_selftest.png) |
| E2E: заблокована injection-атака | ![injection](docs/screenshots/lab2_injection_blocked.png) |
| Лог блокувань [guardrails_blocked.jsonl](docs/logs/guardrails_blocked.jsonl) | ![log](docs/screenshots/lab2_blocked_log.png) |

Логи: [selftest.log](docs/lab2/selftest.log), [injection_layer1.log](docs/lab2/injection_layer1.log).

**Обмеження.** PII ловиться regex-ами, імена людей не маскуються (для цього потрібен Presidio/`DetectPII` з Guardrails Hub). Детектор injection — евристичний.

## Lab 3 — Budget & circuit breaker

**Реалізація** ([agent/middleware.py](agent/middleware.py)) — callback-handler LangGraph із `raise_error=True`, тож виняток зупиняє прогін:

- **Токен-бюджет.** Токени з кожного LLM-виклику переводяться в `$`; при `cost > $0.15` — `BudgetExceeded` (hard-stop, код виходу 3). Новий LLM-виклик після вичерпання бюджету не робиться.
- **Circuit breaker.** CLOSED → OPEN при `> N` послідовних збоях tool-ів (збій = виняток або результат `ПОМИЛКА…`, включно з блокуванням guardrails). Після cooldown — HALF_OPEN (одна пробна спроба), успіх → CLOSED. Код виходу 4.
- **Алерти.** Перехід у OPEN і hard-stop бюджету надсилають повідомлення в Discord webhook; усе дублюється в [alerts.jsonl](docs/logs/alerts.jsonl).

**Результати.** `middleware-test` — усі 8 перевірок PASS ([log](docs/lab3_selftest.log)). E2E: бюджет знижено до $0.0005 → hard-stop при $0.000628 ([log](docs/lab3_budget_demo.log)); поріг breaker 2 → OPEN після збоїв на неіснуючих файлах ([log](docs/lab3_breaker_demo.log)).

![discord](docs/screenshots/lab3_discord_alerts.png)

**Примітка.** Реальний ліміт $0.15 в e2e недосяжний (≈$0.001/run на Ollama), тому демо знижує його; сам ліміт $0.15 стоїть за замовчуванням і перевіряється в `middleware-test`.

## Lab 4 — Regression suite

**Golden dataset** — [evals/golden.jsonl](evals/golden.jsonl), 6 кейсів на фіксованих файлах ([evals/fixtures/](evals/fixtures)): ціна плану, промокод політики, кількість тікетів, причини скасування (×2), відсутній файл (перевірка чесної обробки помилки).

**Метрики** ([evals/run_evals.py](evals/run_evals.py)):
- **Accuracy** — відповідь містить усі очікувані regex-и;
- **Relevance** — викликано потрібні tools, лише дозволені, не більше `max_calls`.

**Threshold gate** — обидві метрики ≥ 0.8; інакше `exit 1` і workflow падає. Workflow [eval.yml](.github/workflows/eval.yml) запускається на кожен PR у `main`: ставить Ollama з тією ж моделлю, прогоняє eval, пише таблицю в Job summary.

**Baseline.** Локально на чистому коді: Accuracy 1.00, Relevance 1.00 ([log](docs/lab4_eval_local.log)).

**Заблокований PR з регресією** — [PR #2](https://github.com/OleksandrMasliennikov/agentops-retention/pull/2), гілка `demo/regression`:

1. Перший коміт підміняв системний промпт на «Never call tools». Перевірка **пройшла** ✅: `qwen2.5:7b` проігнорувала інструкцію й далі викликала tools, тож якість не впала.
2. Другий коміт «drop tool binding» (`tools=[]` у `create_react_agent`) — детермінована регресія. `eval-gate` став **❌ failed**.

![PR](docs/screenshots/lab4_regression_pr.png)

**Чесно про обмеження.** Gate робить перевірку червоною, але на скріншоті кнопка Merge ще активна: обов'язкову перевірку (branch protection) для приватного репозиторію на безкоштовному плані GitHub увімкнути не вдалося/не ввімкнено. Для фактичного блокування потрібне правило «Require status checks → `eval-gate`». PR із регресією навмисно залишено незмерженим.

---

## Структура репозиторію

```
agent/        агент, MCP-сервер, tracing, guardrails, middleware
evals/        golden dataset, фікстури, run_evals.py
scripts/      сценарії, cost_report, selftest-и guardrails/middleware, injection_test
docs/         логи прогонів, скріншоти, артефакти по лабах
docs/logs/    копії guardrails_blocked.jsonl, alerts.jsonl (робочі логи — logs/, у .gitignore)
.github/      workflow eval-regression
```

Нотатки Lab 1 (попередня версія README): [docs/lab1/README_lab1_notes.md](docs/lab1/README_lab1_notes.md).
