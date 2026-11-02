### Added

- `hub/scripts/backfill_public_merges.py`: a one-time script that marks the old ticker merges of
  named projects public, so public pages count them; a dry run unless `--apply`, refuses a project
  whose id, name, repository address or public check doesn't match, and `--undo` takes back
  exactly what it marked.
