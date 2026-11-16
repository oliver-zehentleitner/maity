### Fixed

- cli: runner — the Claude Code and opencode sandbox profiles now allow
  `cat /proc/sys/kernel/random/uuid`, so a placed agent can make the OS
  UUID v4 that every Keep the Why entry's `Id` needs. Under the command
  allowlist `uuidgen`, `node` and `od /dev/urandom` are all refused, which
  blocked every entry a runner agent wrote. Codex and agy have no
  per-command allowlist and already run the command in their own sandbox.
