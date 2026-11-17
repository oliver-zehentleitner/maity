### Added

- cli: `cli/tests/claude_sandbox_probe.py` re-checks Claude Code's sandbox
  the way the runner relies on it, against the installed `claude`, with no
  hub. It covers prefixed `maity` calls, the hook's refusal paths, the hook
  switches and the hidden credentials. It prints PASS or FAIL per step.

### Security

- cli: the runner's Claude Code hook refuses a line that runs `maity`
  anywhere but as its first word. That covers a variable, a path or a
  wrapper such as `env`, `command`, `exec`, `nice` or `timeout` in front
  of it, a shell or `eval` running it, and `maity` after another command.
