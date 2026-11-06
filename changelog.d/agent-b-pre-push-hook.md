### Added

- An opt-in pre-push hook (`tools/hooks/pre-push`, `tools/pre_push.py`, turned on with
  `git config core.hooksPath tools/hooks`; CONTRIBUTING.md): for each of `hub/` and `cli/` a push
  touches it runs CI's `make lint typecheck` (black, ruff, mypy, no tests) with the hub's
  environment from the hashed lock, and stops first when that environment's black, ruff or mypy
  differ from the lock's pins.
