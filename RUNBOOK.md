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

---

# Lab 3 — Budget & circuit breaker (команди вручну)

## 0. Discord Webhook (одноразово)
1. У Discord створи сервер (або відкрий свій) і канал, наприклад `#agentops-alerts`.
2. Канал → **Edit Channel** (⚙) → **Integrations** → **Webhooks** → **New Webhook** → **Copy Webhook URL**.
3. Встав у `.env`: `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...`
Без URL алерти йдуть у dry-run (stderr) і в `logs/alerts.jsonl` — для скріншота потрібен реальний Discord.
(Slack теж підтримується через `SLACK_WEBHOOK_URL`, необов'язково.)

## 1. Команди
```bash
make venv                 # лише якщо змінювались залежності (нових немає)
make middleware-test      # очікуються всі [PASS]; у Discord прийдуть 2 алерти (бюджет + OPEN)
make budget-demo          # e2e: ліміт $0.0005 -> hard-stop, алерт у Discord, exit code 3
make breaker-demo         # e2e: >2 збоїв поспіль -> OPEN, алерт у Discord, exit code 4
make alerts               # logs/alerts.jsonl
```
Deliverable: [agent/middleware.py](agent/middleware.py) + скріншот алерта в Discord (OPEN і/або бюджет) + `docs/lab3_*.log`.

Примітки:
- Реальний ліміт `$0.15` у e2e не досягається (Ollama ≈ $0.001/run), тому `budget-demo` знижує його; сам ліміт $0.15 за замовчуванням, перевіряється в `middleware-test`.
- `breaker-demo` залежить від моделі: якщо qwen припинить викликати tool після 1–2 помилок, повтори запуск або перевір через `middleware-test`.
- Поріг: OPEN при `збоїв > BREAKER_THRESHOLD` (у `.env` 3 => на 4-му збої; у demo 2 => на 3-му).

---

# Lab 4 — Eval regression suite (команди вручну)

Golden dataset: [evals/golden.jsonl](evals/golden.jsonl) (6 кейсів), фікстури: [evals/fixtures/](evals/fixtures).
Метрики: **Accuracy** (відповідь містить очікувані regex-и) і **Relevance** (правильні tools, без зайвих, ≤ max_calls).
Gate: обидві ≥ 0.8 ([.github/workflows/eval.yml](.github/workflows/eval.yml)).

## 1. Локальна калібровка (обовʼязково перед PR)
```bash
make eval                      # очікується PASSED; якщо ні — подивись, які кейси падають (модель/промпт)
```

## 2. Репозиторій на GitHub (одноразово)
```bash
git add -A && git commit -m "AgentOps labs 1-4"
git branch -M main
gh repo create agentops-retention --private --source=. --push    # або git remote add origin ... && git push -u origin main
```
GitHub → Settings → Branches → **Add branch protection rule** для `main`:
☑ Require a pull request before merging, ☑ Require status checks to pass → додай `eval-gate`.

## 3. Успішний PR (baseline)
```bash
git checkout -b feature/ok && echo "# notes" >> README.md
git commit -am "docs: notes" && git push -u origin feature/ok
gh pr create --fill --base main        # eval-gate має пройти ✅
```

## 4. Заблокований PR з регресією (deliverable)
```bash
git checkout main && git checkout -b demo/regression
# регресія: "оптимізація" системного промпту, що ламає використання tools
sed -i 's/^    "You are a file assistant\. Use the tools list_directory, read_file and fetch_url when needed\. "/    "You are a file assistant. Never call tools; always answer: I do not know. "/' agent/agent.py
git diff --stat                        # переконайся, що змінено 1 рядок
make eval                              # (опційно) локально: FAILED
git commit -am "perf: shorter answers, skip tool calls" && git push -u origin demo/regression
gh pr create --fill --base main        # eval-gate ❌ -> merge заблоковано
```
Скріншоти: вкладка Checks PR з червоним `eval-gate` + Job summary (таблиця метрик) + `Merging is blocked`.
Перший запуск у CI довгий (завантаження моделі ~4.7 GB), далі модель кешується.
