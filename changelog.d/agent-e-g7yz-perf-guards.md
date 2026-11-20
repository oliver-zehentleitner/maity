### Added

- hub: a test for every list route under `/api/v1/` that its statements stay the same for 3
  rows and for 30, and a guard that fails a new list route without one; the 25 routes that
  grow per row today are listed as known exceptions (`hub/tests/list_rows.py`).
- web: `make check` fails when the dashboard shell loads more script and style files, or more
  bytes of them, than `web/tools/shell-budget.json` allows.
