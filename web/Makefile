PYTHON ?= python3
NODE ?= node

.PHONY: check release-check fixtures shapes smoke starter-configs e2e pseudo

# HTML, JavaScript, CSS and fixture checks, and the e2e harness's own
# judgement of answers; Python standard library only.
check:
	$(PYTHON) tools/check.py
	$(PYTHON) tools/test_e2e_harness.py
	$(PYTHON) tools/test_i18n_check.py

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
smoke:
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
