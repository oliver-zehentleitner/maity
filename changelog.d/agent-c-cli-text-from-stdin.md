### Added

- cli: free text from standard input or a file, so the shell cannot run `code` spans in it:
  `-` for the text of `say`, `ask`, `report --summary` and `checkpoint -m`/`--next`, and
  `--body-file`, `--summary-file`, `--last-file`, `--next-file`; inline text with a gap where
  a word was, or an odd number of backticks, gets a warning. The pointer block, the skill and
  `docs/agents.md` show the quoted heredoc
