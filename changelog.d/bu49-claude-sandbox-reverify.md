### Added

- cli: `cli/tests/claude_sandbox_probe.py` re-checks Claude Code's sandbox
  the way the runner relies on it, against the installed `claude`, with no
  hub. It starts from the runner's own launch and covers prefixed `maity`
  calls, the hook's refusal paths and failure policy, the hook switches and
  the hidden credentials, and prints PASS or FAIL per step; `--extra-lines`
  probes further prefixed lines live from a file kept outside the
  repository. Each step is checked as testable first and passes only on
  positive evidence. The checked Claude Code version moves only after it
  passed for the new version.

### Changed

- cli: `maity runner check` and the runner's log take Claude Code 2.1.330
  as the version whose sandbox was checked, after the probe's minimum run
  passed for it; the run of the managed and user hook switches is still
  to come.
