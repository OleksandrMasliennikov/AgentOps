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
