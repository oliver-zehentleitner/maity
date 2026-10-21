# The hub's checks. `make check` is what CI runs and what has to be green
# before a pull request.

PYTHON ?= python3

.PHONY: install format check lint typecheck test

install:
	$(PYTHON) -m pip install -e '.[dev]'

format:
	black src tests
	ruff check --fix src tests

check: lint typecheck test

lint:
	black --check src tests
	ruff check src tests

typecheck:
	mypy

test:
	pytest
