PYTHON ?= python3
NODE ?= node

.PHONY: check fixtures smoke starter-configs e2e

# HTML, JavaScript, CSS and fixture checks; Python standard library only.
check:
	$(PYTHON) tools/check.py

# Regenerate fixtures/fixtures.js from fixtures/**/*.json.
fixtures:
	$(PYTHON) tools/check.py --write

# Behaviour smoke test against a DOM shim; needs a node binary, no packages.
smoke:
	$(NODE) tools/smoke.js .
	$(NODE) tools/notifications-stream.js .

# The Runners view's starter configurations through `maity runner check`;
# needs node, bash and maity (Python 3.11+) from cli/.
starter-configs:
	$(PYTHON) tools/starter_configs.py

# Headless Chromium against a real hub; needs maity-hub, maity and Playwright
# for Python (README.md, "Browser end-to-end test").
e2e:
	$(PYTHON) tools/e2e.py $(if $(ARTIFACTS),--artifacts $(ARTIFACTS))
