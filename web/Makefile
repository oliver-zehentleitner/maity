PYTHON ?= python3
NODE ?= node

.PHONY: check release-check fixtures smoke starter-configs e2e

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

# Behaviour smoke test against a DOM shim; needs a node binary, no packages.
smoke:
	$(NODE) tools/smoke.js .
	$(NODE) tools/notifications-stream.js .
	$(NODE) tools/landing-js.js

# The Runners view's starter configurations through `maity runner check`;
# needs node, bash and maity (Python 3.11+) from cli/.
starter-configs:
	$(PYTHON) tools/starter_configs.py

# Headless Chromium against a real hub; needs maity-hub, maity and Playwright
# for Python (README.md, "Browser end-to-end test").
e2e:
	$(PYTHON) tools/e2e.py $(if $(ARTIFACTS),--artifacts $(ARTIFACTS))
