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

# The tools from requirements/dev.txt with their hashes, the CLI itself editable without build
# isolation (setuptools comes from the lock), as CI installs them.
dev:
	python3 -m venv .venv
	.venv/bin/pip install -q --require-hashes -r requirements/dev.txt
	.venv/bin/pip install -q --no-deps --no-build-isolation -e .

# The release build's tools, pinned with hashes in requirements/release.txt (release-cli.yml),
# and the dev extra's in requirements/dev.txt (CI's cli jobs, `make dev`), compiled with the
# hub's dev lock as constraints, so black, ruff, mypy and pytest are the hub's versions.
# `make lock` after changing requirements/release.in or the dev extra, with the uv that
# hub/requirements/tools.txt pins. `lock-check` recompiles copies without their hashes, so every
# hash is fetched again and compared, and checks that pyproject.toml's build backend and dev
# extra pin the same setuptools.
UV ?= uv
LOCK = $(UV) pip compile --quiet --generate-hashes --universal --python-version 3.11 \
	--custom-compile-command "make lock"

lock:
	$(LOCK) requirements/release.in -o requirements/release.txt
	$(LOCK) pyproject.toml --extra dev -c ../hub/requirements/dev.txt -o requirements/dev.txt

lock-check:
	@tmp="$$(mktemp -d)" && trap 'rm -rf "$$tmp"' EXIT \
	&& mkdir -p "$$tmp/cli/requirements" "$$tmp/hub/requirements" \
	&& cp pyproject.toml "$$tmp/cli/" && cp requirements/release.in "$$tmp/cli/requirements/" \
	&& cp ../hub/requirements/dev.txt "$$tmp/hub/requirements/" \
	&& for f in release dev; do sed -e '/^ *--hash=/d' -e 's/ \\$$//' "requirements/$$f.txt" \
		>"$$tmp/cli/requirements/$$f.txt" || exit 1; done \
	&& (cd "$$tmp/cli" && $(LOCK) requirements/release.in -o requirements/release.txt \
		&& $(LOCK) pyproject.toml --extra dev -c ../hub/requirements/dev.txt -o requirements/dev.txt) \
	&& for f in release dev; do diff -u "requirements/$$f.txt" "$$tmp/cli/requirements/$$f.txt" || exit 1; done \
	&& python3 -c 'import re, sys, tomllib; \
		meta = tomllib.load(open("pyproject.toml", "rb")); \
		backend = meta["build-system"]["requires"]; \
		dev = [d for d in meta["project"]["optional-dependencies"]["dev"] if d.startswith("setuptools")]; \
		pinned = re.findall(r"^(setuptools==\S+)", open("requirements/release.in").read(), re.M); \
		sys.exit(0 if backend == pinned == dev else f"lock-check: [build-system] requires {backend}, the dev extra {dev}, requirements/release.in pins {pinned}")' \
	&& echo "lock-check: requirements/release.txt and dev.txt match release.in, pyproject.toml and the hub's dev pins"

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
