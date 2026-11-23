### Fixed

- cli: a placed Claude Code coder can run the project workflow it was refused. `git -C
  <clone> <subcommand>` is allowed like plain git, scoped to the placement's own clone and
  with every git escape (`-c`, `--exec-path`, `--no-index` and the rest) mirrored as a `-C`
  deny, so the `-C` form carries the same denies as plain git. Every
  Claude Code placement's start briefing — sandboxed or not — tells the agent to run one
  command per Bash call, to use `make -C <pkg>` and path arguments instead of `cd <pkg> &&
  …`, and not to prefix a command with a variable. The runner refuses to start a placement (any
  harness) whose resolved clone path contains a character its permission matcher treats as a
  wildcard (`*`, `?`, `[]`), so the `git -C <clone>` allow cannot widen past the placement's
  own clone to other repositories. Virtualenv creation and `pip install` stay out, pending the
  runner-built venvs of tsk-kshm.
