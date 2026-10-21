PYTHON ?= python3
HOST ?= 127.0.0.1
PORT ?= 8070

.PHONY: check fixtures serve

# HTML, JavaScript, CSS and fixture checks; Python standard library only.
check:
	$(PYTHON) tools/check.py

# Regenerate fixtures/fixtures.js from fixtures/*.json.
fixtures:
	$(PYTHON) tools/check.py --write

# Serve web/ over HTTP. Without the hub behind it, open it with
# ?source=fixtures; the page never falls back to fixtures on its own.
serve:
	@echo "http://$(HOST):$(PORT)/?source=fixtures"
	$(PYTHON) -m http.server --bind $(HOST) --directory . $(PORT)
