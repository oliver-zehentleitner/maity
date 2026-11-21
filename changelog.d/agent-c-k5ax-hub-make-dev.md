### Added

- hub: `make dev` creates `hub/.venv` inside make, installs the hashed dev and build locks
  (wheels only, so no build backend is fetched unpinned) and the hub editable, as cli's
  `make dev` does; a sandbox that refuses a bare `python3 -m venv` can now set up the hub.
  With `MAITY_SCRATCH` set, pip's cache goes to `$MAITY_SCRATCH/pip-cache` unless
  `PIP_CACHE_DIR` is set.

### Changed

- hub: the Makefile's targets run `hub/.venv/bin/python` when it exists, else `python3` as
  before (CI's case); `PYTHON=` still names another, and the targets quote it, so a checkout
  path with a space works. `CONTRIBUTING.md`, `hub/README.md` and the pre-push hook's hint
  name `make -C hub dev` as the setup; the README keeps activating the venv, which puts
  `maity-hub` on the path for the entry-point test and the join smoke.
