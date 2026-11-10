### Changed

- web: `web/context/views.md` is split into one topic file per view family,
  each with its own line in `web/context/index.md`, so a Keep the Why
  entry no longer shares that single index line. `tools/views_context_map.py`
  maps each moved entry's id to its topic file and reads an entry id or a
  hunk of that file. `tools/split_views_context.py` rebuilds the topic
  files, the index lines and the locators from a views.md and
  `tools/views_families.tsv`, and fails on an id the table does not list
  (tsk-x3rh56ryfd6s).
