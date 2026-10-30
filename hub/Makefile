# The hub's checks. `make check` is what CI runs and what has to be green
# before a pull request.

PYTHON ?= python3
UV ?= uv

.PHONY: install format check lint typecheck test revision rechain lock lock-upgrade lock-check

# The tested set: every dependency pinned with hashes in requirements/, the
# hub itself on top without resolving anything again.
install:
	$(PYTHON) -m pip install --require-hashes -r requirements/dev.txt -r requirements/build.txt
	$(PYTHON) -m pip install --no-deps --no-build-isolation -e .

format:
	$(PYTHON) -m black src tests scripts
	$(PYTHON) -m ruff check --fix src tests scripts

check: lint typecheck test

lint:
	$(PYTHON) -m black --check src tests scripts
	$(PYTHON) -m ruff check src tests scripts

typecheck:
	$(PYTHON) -m mypy

# One worker per core (pytest-xdist); `make test PYTEST_ARGS=` runs the suite in one process.
PYTEST_ARGS ?= -n auto

test:
	$(PYTHON) -m pytest $(PYTEST_ARGS)

# make revision m="add the tasks"
revision:
	$(PYTHON) scripts/new_revision.py "$(m)"

# After merging origin/main: hang the branch's new migration on main's head.
rechain:
	cd .. && $(PYTHON) tools/rechain.py

# The locks in requirements/: runtime (the image), dev (CI and `install`,
# with the runtime pins as constraints), build (hatchling, with the dev pins
# as constraints) and tools (uv itself, for lock-check in CI).
# `lock` keeps every pin and only follows pyproject.toml; `lock-upgrade`
# moves everything to the newest versions that resolve. Either way, commit
# the four files and let CI prove them on all three engines.
LOCK = $(UV) pip compile --quiet --generate-hashes --universal --python-version 3.12 \
	--custom-compile-command "make lock"

lock:
	$(MAKE) --no-print-directory _lock DIR=requirements FLAGS=

# `make lock-upgrade PACKAGE=fastapi` moves only that package (and what it needs).
lock-upgrade:
	$(MAKE) --no-print-directory _lock DIR=requirements \
		FLAGS="$(if $(PACKAGE),--upgrade-package $(PACKAGE),--upgrade)"

# Recompiles copies of the locks and fails when they differ: a dependency
# changed in pyproject.toml without `make lock`.
# The copy keeps the relative paths, which the files name in their comments.
# Its hash lines are dropped first: uv would keep them as given, so a hash
# edited by hand would pass; this way every hash is fetched again and compared.
lock-check:
	@tmp="$$(mktemp -d)" && trap 'rm -rf "$$tmp"' EXIT \
	&& cp -r pyproject.toml requirements "$$tmp/" \
	&& for f in "$$tmp"/requirements/*.txt; do \
		sed -e '/^ *--hash=/d' -e 's/ \\$$//' "$$f" >"$$f.bare" && mv "$$f.bare" "$$f"; done \
	&& $(MAKE) --no-print-directory -C "$$tmp" -f "$(CURDIR)/Makefile" _lock DIR=requirements FLAGS= \
	&& for f in runtime dev build tools; do \
		diff -u "requirements/$$f.txt" "$$tmp/requirements/$$f.txt" || exit 1; done \
	&& echo "lock-check: requirements/ matches pyproject.toml"

_lock:
	$(LOCK) $(FLAGS) pyproject.toml -o $(DIR)/runtime.txt
	$(LOCK) $(FLAGS) pyproject.toml --extra dev -c $(DIR)/runtime.txt -o $(DIR)/dev.txt
	$(LOCK) $(FLAGS) requirements/build.in -c $(DIR)/dev.txt -o $(DIR)/build.txt
	$(LOCK) $(FLAGS) requirements/tools.in -o $(DIR)/tools.txt
