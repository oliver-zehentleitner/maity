### Changed

- cli: Python 3.11 is the minimum for the whole CLI, the agent commands included (maintainer
  decision); `tomllib` is imported plainly and the 3.10 refusal is gone; CI tests 3.11 and 3.13.
- cli: the runner offers `claude-code` and `codex` (and `stub`); `opencode` is built but refused
  as "not offered yet" until the maintainer decides.
- cli: `maity wait` writes a one-line summary of each event to stderr (`#seq kind subject:
  title`); stdout stays the JSON.
