.PHONY: lock lock-check

# The docs site's tools, pinned with hashes in requirements/site.txt (pages.yml, ci.yml):
# `make lock` after changing requirements/site.in, with the uv that hub/requirements/tools.txt
# pins. `lock-check` recompiles a copy without its hashes, so every hash is fetched again and
# compared.
UV ?= uv
LOCK = $(UV) pip compile --quiet --generate-hashes --universal --python-version 3.11 \
	--custom-compile-command "make -C tools lock"

lock:
	$(LOCK) requirements/site.in -o requirements/site.txt

lock-check:
	@tmp="$$(mktemp -d)" && trap 'rm -rf "$$tmp"' EXIT \
	&& mkdir "$$tmp/requirements" && cp requirements/site.in "$$tmp/requirements/" \
	&& sed -e '/^ *--hash=/d' -e 's/ \\$$//' requirements/site.txt >"$$tmp/requirements/site.txt" \
	&& (cd "$$tmp" && $(LOCK) requirements/site.in -o requirements/site.txt) \
	&& diff -u requirements/site.txt "$$tmp/requirements/site.txt" \
	&& echo "lock-check: requirements/site.txt matches site.in"
