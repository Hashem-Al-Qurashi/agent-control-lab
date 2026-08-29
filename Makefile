# Agent Control Lab -- Stage 0 instrument validation.
#
# `make reproduce SCHEDULE=P2` is the claim: a stranger clones this, runs one
# command, and sees the violation happen exactly as described. `SCHEDULE=P0`
# runs the identical interleaving with a coordination primitive and stays clean.

PY := python3
COMPOSE := docker compose

.PHONY: help up down test unit integration schedules reproduce determinism calibrate manifest clean

help:
	@echo "up          bring up the three databases"
	@echo "down        tear them down"
	@echo "test        full suite"
	@echo "unit        unit tests only (no databases needed)"
	@echo "schedules   the five controls: P0 P1 P2 P3 P4"
	@echo "reproduce   make reproduce SCHEDULE=P2"
	@echo "determinism ACL_REPLAYS=20 replay check"
	@echo "calibrate   prove the oracle catches a planted violation"
	@echo "manifest    print the run manifest (isolation levels, topology)"

up:
	$(COMPOSE) up -d
	@$(COMPOSE) ps

down:
	$(COMPOSE) down -v

test:
	$(PY) -m pytest tests/ -q

unit:
	$(PY) -m pytest tests/unit/ -q

integration:
	$(PY) -m pytest tests/integration/ -q

schedules:
	$(PY) -m pytest tests/schedules/ -q

SCHEDULE ?= P2
reproduce:
	$(PY) -m pytest tests/schedules/test_$(shell echo $(SCHEDULE) | tr A-Z a-z).py -q -s

determinism:
	ACL_REPLAYS=$${ACL_REPLAYS:-20} $(PY) -m pytest \
		tests/schedules/test_p4_determinism.py -q

calibrate:
	$(PY) -c "from oracle.calibration import calibrate; r = calibrate(); \
	print('calibration passed'); \
	[print(f'  {c.name}: expected {c.expected.value}, got {c.actual.value}') for c in r.cases]"

manifest:
	$(PY) -c "import json; from oracle.manifest import build_manifest; \
	print(json.dumps(build_manifest(), indent=2))"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
