# Agent Control Lab -- Stage 0 instrument validation.
#
# `make reproduce SCHEDULE=P2` is the claim: a stranger clones this, runs one
# command, and sees the violation happen exactly as described. `SCHEDULE=P0`
# runs the identical interleaving with a coordination primitive and stays clean.

PY := python3
COMPOSE := docker compose

.PHONY: help up down migrate test unit integration schedules reproduce determinism calibrate manifest assessment-pdf catalog test-llm observability observability-down clean

help:
	@echo "up          bring up the three databases"
	@echo "down        tear them down"
	@echo "migrate     create schemas and the oracle read-only role"
	@echo "test        full suite"
	@echo "unit        unit tests only (no databases needed)"
	@echo "schedules   the five controls: P0 P1 P2 P3 P4"
	@echo "reproduce   make reproduce SCHEDULE=P2  |  make reproduce FAILURE=ACL-F02"
	@echo "determinism ACL_REPLAYS=20 replay check"
	@echo "calibrate   prove the oracle catches a planted violation"
	@echo "manifest    print the run manifest (isolation levels, topology)"
	@echo "assessment-pdf  rebuild the client-facing assessment PDF"
	@echo "observability   start Tempo + Grafana (http://127.0.0.1:3001)"
	@echo "catalog         regenerate docs/FAILURE-CATALOG.md from catalog/failures.yaml"
	@echo "test-llm        run the live model arms (needs DEEPSEEK_API_KEY)"

up:
	# --wait blocks until every healthcheck passes. Without it `make up`
	# returns while Postgres is still starting, and `make up && make reproduce`
	# succeeds only if the databases happen to win the race. A first-run
	# experience that depends on machine speed is not reproducible.
	$(COMPOSE) up -d --wait
	@$(MAKE) --no-print-directory migrate
	@$(COMPOSE) ps

down:
	$(COMPOSE) down -v

# Schemas do not exist on a fresh database. Without this, every target that
# talks to Postgres outside pytest fails on first run -- pytest fixtures were
# quietly the only thing running migrations.
migrate:
	@$(PY) -c "from apps.billing.db import run_migrations as b; \
from apps.ledger.db import run_migrations as l; \
from apps.control.db import run_migrations as c; \
from apps.crm.db import run_migrations as m; \
from apps.entitlements.db import run_migrations as e; \
from oracle.quiescence import grant_readonly; \
b(); l(); c(); m(); e(); grant_readonly(); print('schemas ready')"

test:
	$(PY) -m pytest tests/ -q

unit:
	$(PY) -m pytest tests/unit/ -q

integration:
	$(PY) -m pytest tests/integration/ -q

schedules:
	$(PY) -m pytest tests/schedules/ -q

SCHEDULE ?= P2
FAILURE ?=
# Two ways in: by schedule (P2) or by catalogue id (ACL-F02). The id form looks
# the command up in catalog/failures.yaml rather than a second copy here, which
# would drift from the catalogue the first time either changed.
reproduce:
	@if [ -n "$(FAILURE)" ]; then \
		$(PY) catalog/reproduce.py $(FAILURE); \
	else \
		$(PY) -m pytest tests/schedules/test_$(shell echo $(SCHEDULE) | tr A-Z a-z).py -q -s; \
	fi

determinism:
	ACL_REPLAYS=$${ACL_REPLAYS:-20} $(PY) -m pytest \
		tests/schedules/test_p4_determinism.py -q

calibrate: migrate
	$(PY) -c "from oracle.calibration import calibrate; r = calibrate(); \
	print('calibration passed'); \
	[print(f'  {c.name}: expected {c.expected.value}, got {c.actual.value}') for c in r.cases]"

manifest: migrate
	$(PY) -c "import json; from oracle.manifest import build_manifest; \
	print(json.dumps(build_manifest(), indent=2))"

catalog:
	$(PY) catalog/render.py

test-llm:
	ACL_RUN_LLM=1 $(PY) -m pytest tests/schedules/test_llm_arms.py -q

observability:
	$(COMPOSE) --profile observability up -d --wait
	@echo "Grafana:  http://127.0.0.1:3001  (dashboard: Agent Control Lab -- traces)"
	@echo "Export spans by running a schedule with:"
	@echo "    OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4317 make reproduce SCHEDULE=S1"

observability-down:
	# Named services, NOT `down`. `docker compose --profile observability down`
	# tears down the whole project -- including all five databases -- because a
	# profile filters what starts, not what stops. A target called
	# observability-down that silently stops the databases is a trap, and it
	# caught me: the next test run failed with "connection refused" on every
	# suite that needs Postgres.
	$(COMPOSE) rm -sf tempo grafana

assessment-pdf:
	$(PY) tools/build_assessment_pdf.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
