### Added

- cli: harness adapters, first part (runner slice R5a, design v2 §6) — Claude Code in
  `interactive` and `supervised` mode with a runner-written settings file (`--setting-sources
  user`, `dontAsk`, an empty MCP configuration, its OS sandbox where bubblewrap and socat
  exist); the supervised loop `maity.runner.loop` (headless runs on events, `--keep-cursor`
  waits, settle, hot-loop cap; exit 20/21 reported as `agent_credential_revoked` and
  `crash_loop`/`hot_loop`); `maity wait --keep-cursor`; `runner check` looks for `maity` on
  `agent_path`.
