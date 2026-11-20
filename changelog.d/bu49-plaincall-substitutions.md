### Fixed

- cli: the runner's hook for a placed Claude Code session reads command
  substitutions, and an expansion glued right after `maity`, when it
  decides where `maity` stands on a line, so a line that may leave the
  sandbox runs only as one plain call, as its docstring and
  docs/runners.md describe.
