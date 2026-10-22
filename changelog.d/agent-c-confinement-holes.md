### Security

- cli runner: every agent session gets `GIT_COMMON_DIR=<clone>/.git` and, through
  `GIT_CONFIG_COUNT`, `core.fsmonitor=false` and `diff.ignoreSubmodules=all`. A
  `.git/commondir` or a nested repository registered as a submodule, planted from the
  sandbox, no longer makes the harness's own (unsandboxed) git run a program.
- cli: `maity`'s own git (`report`, `checkpoint`, the state and pointer lookups) always runs
  with `core.fsmonitor=false`, `core.hooksPath=/dev/null` and `diff.ignoreSubmodules=all`,
  whatever its environment; for Claude Code it runs outside the sandbox.
- cli runner: Codex's profile hides the workspaces root (other agents' clones and
  credentials), the runner's state and configuration, and a list of logins and keys in the
  agents' home. Claude Code's sandbox denies the same reads except the workspaces root,
  plus the credential of every other clone that exists when the agent starts. opencode's
  `grep` and `glob` are off (they are permission-checked by pattern, not by path).
- cli runner: Codex is advertised `sandbox: on` only where `codex sandbox -- true` works; a
  stale `auth.json` link in a Codex home is replaced; `runner check` warns when Codex has
  no login.
