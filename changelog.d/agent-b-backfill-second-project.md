### Changed

- `hub/scripts/backfill_public_merges.py`: `--undo` only counts what it would take off unless
  `--apply` is given too; a test shows another project's merges stay untouched by a run and its
  undo.
