### Changed

- CLI runner: a repository's grant may only add plain commands: a program and arguments of
  plain characters. A rule with an assignment or `env` in front, quotes, variables or shell
  operators, a `:` in the program (`prog:*`), or `maity` in any spelling is refused when the configuration
  is read.
- CLI runner: Claude Code's write deny on the clone's `.git` is one `Edit(…)` rule; the
  `Write(…)` rules, which Claude Code does not check, are gone.
- CLI runner: `maity runner check` and the runner's log warn, without blocking the start,
  when Claude Code is another version than the one its sandbox was checked with.
