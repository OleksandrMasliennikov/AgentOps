-include .env
export

PY := .venv/bin/python

.PHONY: venv up down logs ollama smoke scenarios report clean-traces

venv:            ## створити venv і поставити залежності
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

up:              ## підняти Phoenix (UI http://localhost:6006)
	docker compose up -d

down:            ## зупинити Phoenix (дані зберігаються у томі)
	docker compose down

logs:            ## логи Phoenix
	docker compose logs -f phoenix

ollama:          ## перевірити, що модель доступна
	ollama list | grep -q "$${OLLAMA_MODEL:-qwen2.5:7b}"

smoke:           ## один швидкий прогін агента
	THREAD_ID=smoke_$$(date +%s) SCRIPT_NAME=smoke TASK="List the contents of the current directory" $(PY) -u agent/agent.py

scenarios:       ## 6 сценаріїв -> 6 traces
	$(PY) -u scripts/run_scenarios.py 2>&1 | tee docs/lab1/scenarios.log

report:          ## cost dashboard (PNG + CSV у docs/lab1)
	$(PY) scripts/cost_report.py

clean-traces:    ## видалити том Phoenix (усі трейси!)
	docker compose down -v

.PHONY: guardrails-test injection-test injection-test-layer2 lab2-log
guardrails-test: ## Lab2: детермінований тест guardrails (без LLM)
	$(PY) scripts/guardrails_selftest.py 2>&1 | tee docs/lab2/selftest.log

injection-test:  ## Lab2: e2e prompt injection, шар 1 (скан вмісту tools)
	$(PY) scripts/injection_test.py 1 2>&1 | tee docs/lab2/injection_layer1.log

injection-test-layer2: ## Lab2: e2e, скан вимкнено -> блокує allowlist доменів + PII
	$(PY) scripts/injection_test.py 2 2>&1 | tee docs/lab2/injection_layer2.log

lab2-log:        ## показати лог блокувань
	cat logs/guardrails_blocked.jsonl

.PHONY: middleware-test budget-demo breaker-demo alerts
middleware-test: ## Lab3: детермінований тест middleware + реальний Discord-алерт
	$(PY) scripts/middleware_selftest.py 2>&1 | tee docs/lab3_selftest.log

budget-demo:     ## Lab3: e2e hard-stop бюджету (ліміт знижено до $0.0005)
	BUDGET_USD=0.0005 SCRIPT_NAME=budget_demo THREAD_ID=budget_$$(date +%s) \
	TASK="Find all .py files in the current directory, read the first file found and name it" \
	$(PY) -u agent/agent.py 2>&1 | tee docs/lab3_budget_demo.log

breaker-demo:    ## Lab3: e2e circuit breaker (поріг 2, читання неіснуючих файлів)
	BREAKER_THRESHOLD=2 SCRIPT_NAME=breaker_demo THREAD_ID=breaker_$$(date +%s) RECURSION_LIMIT=20 \
	SYSTEM_PROMPT="You are a file assistant. Use read_file. Always call the tool for every file requested, one by one, even if previous calls failed." \
	TASK="Read each of these files one by one: missing_a.txt, missing_b.txt, missing_c.txt, missing_d.txt, missing_e.txt" \
	$(PY) -u agent/agent.py 2>&1 | tee docs/lab3_breaker_demo.log

alerts:          ## Lab3: журнал алертів
	cat logs/alerts.jsonl
