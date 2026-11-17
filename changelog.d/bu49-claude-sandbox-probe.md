### Added

- cli: `cli/tests/claude_sandbox_probe.py` re-checks Claude Code's sandbox
  the way the runner relies on it, against the installed `claude`, with no
  hub. It covers prefixed `maity` calls, the hook's refusal paths, the hook
  switches and the hidden credentials. It prints PASS or FAIL per step.

### Security

- cli: the runner's Claude Code hook decides on the words the shell runs,
  and refuses a line that would run `maity` other than as the plain first
  word of its line.
