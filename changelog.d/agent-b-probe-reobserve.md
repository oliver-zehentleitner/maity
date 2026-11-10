### Fixed

- A report first observed with its pull request open is read again by the probe's sweep, so a merge
  reaches the card: `task_merged` and `merged_closes` fire, and `maity report` no longer refuses a
  follow-up pull request because the merged one looks open (docs/api.md §6.6).
