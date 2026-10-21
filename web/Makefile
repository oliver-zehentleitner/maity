PYTHON ?= python3
NODE ?= node

.PHONY: check fixtures smoke

# HTML, JavaScript, CSS and fixture checks; Python standard library only.
check:
	$(PYTHON) tools/check.py

# Regenerate fixtures/fixtures.js from fixtures/**/*.json.
fixtures:
	$(PYTHON) tools/check.py --write

# Behaviour smoke test against a DOM shim; needs a node binary, no packages.
smoke:
	$(NODE) tools/smoke.js .
