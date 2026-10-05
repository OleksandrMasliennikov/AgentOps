# RUNBOOK — Lab 1 (команди виконуються вручну з каталогу AgentOps)

Усі кроки є в [Makefile](Makefile) (`make help`-подібні коментарі), нижче — еквівалент без make.

## 0. Одноразове налаштування
```bash
cp .env.example .env                       # за потреби відредагуй
make venv                                  # = python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama serve &                             # якщо Ollama ще не запущена
ollama pull qwen2.5:7b                     # якщо моделі немає
```

## 1. Phoenix
```bash
make up                                    # = docker compose up -d
curl -sI http://localhost:6006 | head -1   # очікується HTTP/1.1 200 OK
```

## 2. Перевірка агента
```bash
make smoke                                 # один trace у проєкті retention-agent
```

## 3. Сценарії (≈5 хв на CPU)
```bash
make scenarios                             # = .venv/bin/python scripts/run_scenarios.py
```

## 4. Дашборд
```bash
make report                                # docs/lab1/cost_dashboard.png, cost_by_script.csv, tools.csv
```
У UI: http://localhost:6006 → Projects → `retention-agent` → відкрий trace → скріншот дерева спанів.

## 5. Завершення
```bash
make down                                  # зупинити Phoenix (трейси лишаються у томі)
make clean-traces                          # повне очищення (опціонально)
```

## Типові проблеми
- `Connection refused :6006` — Phoenix не піднятий (`make up`, `make logs`).
- Таймаут LLM — збільш `LLM_TIMEOUT` у `.env`.
- Порожній дашборд — спершу `make scenarios`.

---

# Lab 2 — Guardrails (команди вручну)

```bash
make venv                     # перевстановити залежності (додано guardrails-ai, pyyaml)
make guardrails-test          # швидкий детермінований тест; очікуються всі [PASS]
make injection-test           # e2e шар 1: отруєний тікет блокується guardrail-ом (~1-3 хв)
make injection-test-layer2    # e2e шар 2: скан вимкнено; блокує URL allowlist + PII-маскування
make lab2-log                 # logs/guardrails_blocked.jsonl — deliverable "blocked injection attack log"
```
Deliverable: [agent/guardrails_config.yaml](agent/guardrails_config.yaml) + `logs/guardrails_blocked.jsonl`
+ `docs/lab2/injection_layer*.log`. Спрацювання guardrails видно в stderr як `[GUARDRAILS] BLOCKED ...`.

Примітка: якщо `pip install guardrails-ai` падає на Python 3.14, створи venv на 3.12/3.13:
`rm -rf .venv && python3.12 -m venv .venv && make venv`.
Шар 2 залежить від моделі: якщо qwen не спробувала `fetch_url` на evil-домен, тест покаже 0 спроб — повтори запуск.
