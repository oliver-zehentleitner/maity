### Added

- cli: `[backend.local] clone_venvs` gives a Claude Code placement in the `single` layout a dev
  venv for each named part of its clone (for example `hub`, `cli`), so the agent runs the
  project's checks although its session cannot reach PyPI. The runner builds it at the start
  from `<part>/requirements/dev.txt` as the placement's branch has it in the repository (every
  requirement pinned with sha256 hashes), wheels only, the clone's own code taken from
  `<part>/src`. The venv is read-only to the session; `<part>/.venv` in the clone links to it
  where nothing else stands there; it goes with the placement. One that cannot be built is
  logged and never fails a start.

### Changed

- tools: `tools/guards.sh` without `HUB_PYTHON` tests with the work tree's
  `hub/.venv/bin/python` where it exists, else with `python3` as before.
- tools: the repository's `.gitignore` hides the empty placeholders Claude Code's sandbox leaves at a
  clone's root, so `tools/guards.sh` starts in a placed coder's clone.
