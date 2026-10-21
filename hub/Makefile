# The hub's checks. `make check` is what CI runs and what has to be green
# before a pull request.

PYTHON ?= python3

.PHONY: install format check lint typecheck test revision

install:
	$(PYTHON) -m pip install -e '.[dev]'

format:
	$(PYTHON) -m black src tests scripts
	$(PYTHON) -m ruff check --fix src tests scripts

check: lint typecheck test

lint:
	$(PYTHON) -m black --check src tests scripts
	$(PYTHON) -m ruff check src tests scripts

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

# make revision m="add the task table"
revision:
	$(PYTHON) scripts/new_revision.py "$(m)"
