### Added

- cli: `cli/tests/claude_sandbox_probe.py` re-checks Claude Code's sandbox
  the way the runner relies on it, against the installed `claude`, with no
  hub. It covers prefixed `maity` calls, the hook's refusal paths, the hook
  switches and the hidden credentials. It prints PASS or FAIL per step.

### Security

- cli: the runner's Claude Code hook decides on the words the shell runs
  and passes a line only when it can tell what the line runs; one that may
  run `maity` other than as the plain first word is refused.
