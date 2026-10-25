### Added

- hub: a contract card names where its text lives — `contract.path` (default
  `docs/api.md`, repository-relative, else `not_a_path`) and `contract.section`
  — and `GET /projects/{slug}/tasks/{id}/contract` reads that section from the
  project's repository through the probe at the default branch's commit: the
  heading of level 2 to 4 whose first token is the section number, fenced code
  skipped, `not_found_in_file` / `ambiguous_in_file` / `not_found_on_forge` /
  `too_large` / `not_text` instead of a guess, the text cut at 64 KiB, one read
  kept for 60 s per repository, commit, path and section (docs/api.md §6.8)
