### Added

- cli: the runner can build a placed coder's per-subpackage virtual environments inside the
  clone at setup (`[backend.local] clone_venvs`), each from that subpackage's own hash-locked
  `requirements/dev.txt`, so the checks that invoke `<dir>/.venv/bin/python` work; claude-code
  placements only, opt-in and idempotent, a failed build never fails the start.
- cli: the runner can set a placed coder's clone `core.hooksPath` (`[backend.local]
  clone_hooks_path`) so the repository's pre-push hook runs its checks before a push;
  claude-code placements only.
- cli: the runner can grant a harness sandbox write access to directories beyond the clone
  (`[backend.local] sandbox_writable_dirs`, absolute or `~/…`), for a shared run-slot or lock
  directory the tests coordinate through.
- cli: a coder may run `git -C <clone> <subcommand>` under Claude Code, allowed exactly as
  `git <subcommand>` is, with the git option denials (config, exec-path, no-index, the
  credential path, …) applying under a `-C` prefix too.

### Changed

- cli: `tools/guards.sh` defaults `HUB_PYTHON` to the work tree's own `hub/.venv/bin/python`
  (resolved from the clone root) when unset, so a plain `tools/guards.sh` needs no environment
  prefix.
- cli: agent, editor and shell config a sandboxed run may leave in the work tree (`.bashrc`,
  `.mcp.json`, `.claude/…`, `.vscode`, …) is now ignored by the repository's `.gitignore`, so
  `tools/guards.sh`'s clean-tree check passes inside a sandboxed coder clone.
