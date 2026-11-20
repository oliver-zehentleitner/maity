### Fixed

- cli: the runner's hook for a placed Claude Code session reads command
  substitutions, and expansions glued to a name, when it decides where
  `maity` stands on a line, so such a line is refused as its docstring and
  docs/runners.md describe.
