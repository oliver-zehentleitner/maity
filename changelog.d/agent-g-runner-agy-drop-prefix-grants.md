### Changed

- cli: command grants ending in ` *` (prefix grants) are no longer applied to antigravity
  (agy) placements either. With exact grants already not applied, agy now gets no `command()`
  allow from a grant's command list at all: every such entry runs inside agy's sandbox like an
  unlisted command, and `maity runner check` names it. A command that must run outside agy's
  sandbox can no longer be granted through the `allow` list — run it under Claude Code or
  Codex, or arrange the work another way. The `allow` list is unchanged for Claude Code and
  Codex.
