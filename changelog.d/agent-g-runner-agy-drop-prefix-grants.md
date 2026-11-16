### Changed

- cli: command grants ending in ` *` (prefix grants) are no longer applied to antigravity
  (agy) placements either. With exact grants already not applied, agy now gets no `command()`
  allow from a grant's command list at all: every such entry runs inside agy's sandbox like an
  unlisted command, and `maity runner check` names it. A command that must run outside agy's
  sandbox can no longer be granted through the `allow` list — run it under Claude Code or
  Codex, or arrange the work another way. The `allow` list is unchanged for Claude Code and
  Codex. One command grant remains for agy, `command(maity)`, which agy applies after reading
  the invoked command past a leading assignment or wrapper, so it is not as tight as Claude
  Code's. Because the runner cannot confine that grant, antigravity is not offered yet: a
  configuration with `[harness.antigravity]` is refused (held back until agy's command grants
  are confined at the OS level, tsk-zjv2xyhyggnm), so the runner starts no antigravity
  placement until then (docs/runners.md).
