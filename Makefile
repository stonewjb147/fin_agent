PYTHON ?= python
COMPOSE ?= docker compose

.PHONY: help check lint test evals smoke collect web docker-build docker-test docker-collect docker-check probe

help:
	@echo "make check         - lint + tests + eval smoke (CI gate)"
	@echo "make lint          - ruff check"
	@echo "make test          - pytest -q (offline)"
	@echo "make smoke         - validate golden set + metric self-test"
	@echo "make collect       - fetch today's data (network)"
	@echo "make web           - start the Streamlit research console"
	@echo "make docker-build  - build the deployment image"
	@echo "make docker-test   - run the offline test suite in the image"
	@echo "make docker-collect- run the daily collector in the image"
	@echo "make docker-check  - run the health check in the image"
	@echo "make probe         - probe AKShare source availability"

check: lint test smoke

lint:
	$(PYTHON) -m ruff check finagent scripts tests

test:
	$(PYTHON) -m pytest -q

smoke:
	$(PYTHON) -m finagent.evals.run_evals --smoke

evals:
	$(PYTHON) -m finagent.evals.run_evals --answers evals/answers.jsonl

collect:
	$(PYTHON) -m finagent.cli collect --start 2022-01-01

web:
	$(PYTHON) -m streamlit run finagent/web/app.py

probe:
	$(PYTHON) scripts/probe_sources.py

docker-build:
	$(COMPOSE) build

docker-test:
	$(COMPOSE) run --rm app python -m pytest -q

docker-collect:
	$(COMPOSE) run --rm app python scripts/collect_daily.py

docker-check:
	$(COMPOSE) run --rm app python scripts/health_check.py
