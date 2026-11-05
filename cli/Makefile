PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: check lint format typecheck test dev lock lock-check release-build

check: lint typecheck test

lint:
	$(PY) -m ruff check src tests
	$(PY) -m black --check src tests

format:
	$(PY) -m ruff check --fix src tests
	$(PY) -m black src tests

typecheck:
	$(PY) -m mypy src tests
	$(PY) -m mypy --platform win32 --follow-imports=silent src/maity/winacl.py src/maity/state.py

test:
	$(PY) -m pytest -q

dev:
	python3 -m venv .venv
	.venv/bin/pip install -q -e '.[dev]'

# The release build's tools, pinned with hashes in requirements/release.txt (release-cli.yml):
# `make lock` after changing requirements/release.in, with the uv that hub/requirements/tools.txt
# pins. `lock-check` recompiles a copy without its hashes, so every hash is fetched again and
# compared, and checks that pyproject.toml's build backend and dev extra pin the same setuptools.
UV ?= uv
LOCK = $(UV) pip compile --quiet --generate-hashes --universal --python-version 3.11 \
	--custom-compile-command "make lock"

lock:
	$(LOCK) requirements/release.in -o requirements/release.txt

lock-check:
	@tmp="$$(mktemp -d)" && trap 'rm -rf "$$tmp"' EXIT \
	&& mkdir "$$tmp/requirements" && cp requirements/release.in "$$tmp/requirements/" \
	&& sed -e '/^ *--hash=/d' -e 's/ \\$$//' requirements/release.txt >"$$tmp/requirements/release.txt" \
	&& (cd "$$tmp" && $(LOCK) requirements/release.in -o requirements/release.txt) \
	&& diff -u requirements/release.txt "$$tmp/requirements/release.txt" \
	&& python3 -c 'import re, sys, tomllib; \
		meta = tomllib.load(open("pyproject.toml", "rb")); \
		backend = meta["build-system"]["requires"]; \
		dev = [d for d in meta["project"]["optional-dependencies"]["dev"] if d.startswith("setuptools")]; \
		pinned = re.findall(r"^(setuptools==\S+)", open("requirements/release.in").read(), re.M); \
		sys.exit(0 if backend == pinned == dev else f"lock-check: [build-system] requires {backend}, the dev extra {dev}, requirements/release.in pins {pinned}")' \
	&& echo "lock-check: requirements/release.txt matches release.in and pyproject.toml"

# The sdist and wheel from the locked tools only: a fresh environment with nothing but
# requirements/release.txt as wheels only (a package with only an sdist would be built with
# unhashed build tools), and a build without isolation, so nothing else is downloaded.
BUILD_ENV ?= $(CURDIR)/.release-env

release-build:
	rm -rf "$(BUILD_ENV)" ../dist
	python3 -m venv "$(BUILD_ENV)"
	"$(BUILD_ENV)/bin/python" -m pip install --quiet --require-hashes --no-deps --only-binary :all: -r requirements/release.txt
	"$(BUILD_ENV)/bin/python" -m build --no-isolation --outdir ../dist
	"$(BUILD_ENV)/bin/python" -m twine check --strict ../dist/*
