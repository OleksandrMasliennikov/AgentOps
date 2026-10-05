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
