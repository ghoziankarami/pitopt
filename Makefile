# One entry point for the whole system. `make help` lists the targets.

# Python 3.10+ for `make setup`; override with e.g. `make setup PYTHON=python3.12`
PYTHON   ?= python3
PY       ?= .venv/bin/python
PIP      ?= .venv/bin/pip
PITOPT   := $(PY) -m pitopt
PORPHYRY := projects/porphyry_synthetic

.PHONY: help setup ui test lint check example porphyry \
        minelib verify cross-check all bundle clean

help:
	@echo "setup        create .venv and install pitopt (editable) with all dependencies"
	@echo "ui           start the web UI at http://127.0.0.1:8765"
	@echo "test         unit tests + independent consistency checks on every run in outputs/"
	@echo "lint         ruff"
	@echo "check        lint + test"
	@echo ""
	@echo "example      small synthetic tin model                    -> outputs/example_tin/"
	@echo "porphyry     synthetic porphyry: pipe orebody, bowl pit   -> outputs/porphyry/"
	@echo ""
	@echo "minelib      solver alone on the MineLib zuck_small benchmark"
	@echo "verify       independent slope / cone / schedule / design checks on the porphyry result"
	@echo "cross-check  NetworkX preflow-push vs SciPy Dinic and brute force"
	@echo "all          test + example + minelib + porphyry + verify"
	@echo ""
	@echo "bundle       concatenate all source into dist/pitopt_source_bundle.md"
	@echo "clean        remove outputs/ and dist/"

setup:
	$(PYTHON) -m venv .venv
	$(PIP) install --default-timeout=300 -e ".[mcp,dev]"

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

check: lint test

ui:
	$(PITOPT) ui

example:
	$(PITOPT) run --config projects/example_tin/project.yaml

$(PORPHYRY)/data/porphyry_blocks.csv:
	$(PY) scripts/make_synthetic_deposit.py --nx 60 --ny 60 --nz 28

porphyry: $(PORPHYRY)/data/porphyry_blocks.csv
	$(PITOPT) run --config $(PORPHYRY)/project.yaml

minelib:
	$(PY) scripts/run_minelib.py benchmarks/minelib_zuck_small zuck_small

verify: porphyry
	$(PY) scripts/verify_pit.py $(PORPHYRY)/project.yaml

cross-check:
	$(PY) scripts/cross_check_solver.py projects/example_tin/project.yaml

all: test example minelib porphyry verify

bundle:
	$(PY) scripts/bundle_source.py

clean:
	rm -rf outputs dist
