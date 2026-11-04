### Fixed

- hub: `context/events.md`, the `holder_stalled` entry: the minute pass filters closed cards (the
  scan without an index is what reads them all), the backfill leaves closed cards alone on purpose
  (Revisit when a closed card can be reopened), the full path of `auth/caller.py`, and why the
  replacement's `holder_moves` guards a reordering.
