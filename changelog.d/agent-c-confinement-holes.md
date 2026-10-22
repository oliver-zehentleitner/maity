### Security

- cli runner: every agent session gets `GIT_COMMON_DIR=<clone>/.git`, so a `.git/commondir`
  an agent writes from its sandbox no longer redirects the harness's own (unsandboxed) git
  to a configuration with `core.fsmonitor` or hooks. Codex's profile hides the workspaces
  root (other agents' clones and credentials), the runner's state directory and the logins
  and keys in the agents' home (`~/.ssh`, `~/.gnupg`, `~/.codex`, `~/.claude`,
  `~/.git-credentials`, `~/.netrc`); Claude Code's sandbox denies the same reads except
  the workspaces root; opencode's `grep` and `glob` cannot read `.git/maity`.
- cli runner: Codex is advertised `sandbox: on` only where `codex sandbox -- true` works; a
  stale `auth.json` link in a Codex home is replaced; `runner check` warns when Codex has
  no login.
