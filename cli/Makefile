PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: check lint format typecheck test dev

check: lint typecheck test

lint:
	$(PY) -m ruff check src tests
	$(PY) -m black --check src tests

format:
	$(PY) -m ruff check --fix src tests
	$(PY) -m black src tests

typecheck:
	$(PY) -m mypy src

test:
	$(PY) -m pytest -q

dev:
	python3 -m venv .venv
	.venv/bin/pip install -q -e '.[dev]'
