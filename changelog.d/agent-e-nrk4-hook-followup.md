### Changed

- cli: `maity runner` refuses a Claude Code start on a host with the sandbox's tools
  (bubblewrap and socat) when Claude Code is older than 2.1.295 or its version is unknown,
  instead of starting it unsandboxed. `require_sandbox = false` under `[harness.claude-code]`
  keeps the unsandboxed start; `require_sandbox` is now unset by default.
- cli: `maity runner` reads a harness version only as a token of its own; a malformed one
  (`2.1.295+`) counts as unknown.
- cli: on an ssh host `maity runner` finds `maity` on `agent_path` when it connects and
  starts the session loop and the hook of a sandboxed Claude Code agent by that absolute
  path; a host without `maity` there is refused.

### Security

- cli: `maity runner` refuses a sandboxed Claude Code start, and `maity runner check`
  reports an error, while managed Claude Code settings set `disableAllHooks` or
  `allowManagedHooksOnly`, or the agents' user's settings set `allowManagedHooksOnly`.
