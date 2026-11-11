PYTHON ?= python3
NODE ?= node

.PHONY: check release-check fixtures shapes smoke smoke-run starter-configs e2e pseudo lock lock-check

# HTML, JavaScript, CSS and fixture checks, and the e2e harness's own
# judgement of answers, and that ci.yml runs the web job for every file
# check.py reads outside web/; Python standard library only.
check:
	$(PYTHON) tools/check.py
	$(PYTHON) tools/test_e2e_harness.py
	$(PYTHON) tools/test_i18n_check.py
	$(PYTHON) tools/test_step_up_check.py
	$(PYTHON) tools/test_vendor_ktw.py
	$(PYTHON) tools/test_ci_paths.py

# Before a release: no translation lacks a key or follows an older English text.
release-check:
	$(PYTHON) tools/check.py --release

# Regenerate fixtures/fixtures.js from fixtures/**/*.json.
fixtures:
	$(PYTHON) tools/check.py --write

# Re-record tools/hub-shapes.json, the forms of the hub's answers that check
# compares the fixtures with, after a change to the hub's answers; needs the hub
# installed (HUB_PYTHON: a Python with hub/'s test requirements).
HUB_PYTHON ?= python3
shapes:
	cd ../hub && MAITY_WRITE_SHAPES=1 $(HUB_PYTHON) -m pytest -q -p no:cacheprovider tests/test_web_shapes.py

# Behaviour smoke test against a DOM shim; needs a node binary, no packages.
# It runs in one of the account's run slots (../tools/run_slot.sh, at most two
# smoke or PostgreSQL runs at a time); `make smoke SLOT=` runs it without one.
SLOT ?= ../tools/run_slot.sh

smoke:
	$(SLOT) $(MAKE) --no-print-directory smoke-run

smoke-run:
	$(NODE) tools/smoke.js .
	$(NODE) tools/notifications-stream.js .
	$(NODE) tools/landing-js.js

# The Runners view's starter configurations through `maity runner check`;
# needs node, bash and maity (Python 3.11+) from cli/.
starter-configs:
	$(PYTHON) tools/starter_configs.py

# Every route in headless Chromium with a pseudo catalog: what carries no mark is a text
# outside the catalog. Needs Playwright, no hub. STRICT=1 fails on any.
pseudo:
	$(PYTHON) tools/pseudo_run.py $(if $(STRICT),--strict)

# Headless Chromium against a real hub; needs maity-hub, maity and Playwright
# for Python (README.md, "Browser end-to-end test").
e2e:
	$(PYTHON) tools/e2e.py $(if $(ARTIFACTS),--artifacts $(ARTIFACTS))

# Playwright for the e2e and pseudo runs, pinned with hashes in requirements/e2e.txt
# (ci.yml, web-e2e): `make lock` after changing requirements/e2e.in, with the uv that
# hub/requirements/tools.txt pins. It is compiled with the hub's runtime pins as constraints,
# because CI installs it into the hub's environment. `lock-check` recompiles a copy without
# its hashes, so every hash is fetched again and compared.
UV ?= uv
LOCK = $(UV) pip compile --quiet --generate-hashes --universal --python-version 3.12 \
	--custom-compile-command "make -C web lock"

lock:
	$(LOCK) -c ../hub/requirements/runtime.txt requirements/e2e.in -o requirements/e2e.txt

lock-check:
	@tmp="$$(mktemp -d)" && trap 'rm -rf "$$tmp"' EXIT \
	&& mkdir -p "$$tmp/web/requirements" "$$tmp/hub/requirements" \
	&& cp requirements/e2e.in "$$tmp/web/requirements/" \
	&& cp ../hub/requirements/runtime.txt "$$tmp/hub/requirements/" \
	&& sed -e '/^ *--hash=/d' -e 's/ \\$$//' requirements/e2e.txt >"$$tmp/web/requirements/e2e.txt" \
	&& (cd "$$tmp/web" && $(LOCK) -c ../hub/requirements/runtime.txt requirements/e2e.in -o requirements/e2e.txt) \
	&& diff -u requirements/e2e.txt "$$tmp/web/requirements/e2e.txt" \
	&& echo "lock-check: requirements/e2e.txt matches e2e.in and the hub's runtime pins"
