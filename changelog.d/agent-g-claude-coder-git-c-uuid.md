### Fixed

- cli: a placed Claude Code coder can run the project workflow it was refused. `git -C
  <clone> <subcommand>` is allowed like plain git, scoped to the placement's own clone and
  with every git escape (`-c`, `--exec-path`, `--no-index` and the rest) denied again in the
  `-C` form, so it reads and writes the clone without reaching another repository or outside
  the work tree. The Keep-the-Why UUID source works again: Claude Code routes `cat <path>` to
  the Read tool, so the kernel UUID path now also has a Read rule and
  `cat /proc/sys/kernel/random/uuid` is no longer refused. The start briefing tells the agent
  to run one command per Bash call, to use `make -C <pkg>` and path arguments instead of
  `cd <pkg> && …`, and not to prefix a command with a variable, since Claude Code matches the
  allowlist against the command line as written. Virtualenv creation and `pip install` stay
  out, pending the runner-built venvs of tsk-kshm.
