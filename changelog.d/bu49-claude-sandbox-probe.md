### Added

- cli: `cli/tests/claude_sandbox_probe.py` re-checks Claude Code's sandbox
  the way the runner relies on it, against the installed `claude`, with no
  hub. It covers prefixed `maity` calls, the hook's refusal paths, the hook
  switches and the hidden credentials. It prints PASS or FAIL per step.
