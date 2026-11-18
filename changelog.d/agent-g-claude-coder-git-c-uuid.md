### Fixed

- cli: a placed Claude Code coder can run the project workflow it was refused. `git -C
  <clone> <subcommand>` is allowed like plain git, scoped to the placement's own clone and
  with every git escape (`-c`, `--exec-path`, `--no-index` and the rest) mirrored as a `-C`
  deny, so the `-C` form carries the same denies as plain git. The Keep-the-Why UUID source
  works again: Claude Code routes `cat <path>` to the Read tool, so the kernel UUID path now
  also has a Read rule and `cat /proc/sys/kernel/random/uuid` is no longer refused. Every
  Claude Code placement's start briefing — sandboxed or not — tells the agent to run one
  command per Bash call, to use `make -C <pkg>` and path arguments instead of `cd <pkg> &&
  …`, and not to prefix a command with a variable. A workspaces root containing a
  glob-special character (`*`, `?`, `[]`) is refused, so a `git -C <clone>` rule cannot
  become a wildcard. Virtualenv creation and `pip install` stay out, pending the
  runner-built venvs of tsk-kshm.
