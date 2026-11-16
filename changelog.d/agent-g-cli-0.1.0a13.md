### Changed

- cli: version 0.1.0a13 for PyPI. The runner installs and updates
  Claude Code and Codex where its configuration says so, from checked
  vendor releases, beside the version in use, with `maity runner tools`
  and `rollback`, the owner's "Update now" and `login_needed` (#1805,
  with the fixes of #1862 and #1863). `maity wait`'s chat read on a
  timeout renews no claim lease (#1856). An antigravity (agy) placement
  gets no command grant from a repository's `allow` list (its
  `command(maity)` stays), and the runner does not offer agy until it
  can confine agy's `maity` at the OS level (#1859, #1860).
- Upgrading: a `runner.toml` with a `[harness.antigravity]` table is now
  refused and the whole runner does not start; remove that table before
  upgrading. Managing a tool (`install` or `update` set) needs a hub
  version 0.1.0a8 or later; a runner that manages no tool keeps working
  with an older hub. A runner that offers codex is refused at `hello`
  by a hub that does not accept codex's `sandbox` confinement; that was
  so before 0.1.0a13 too, and it needs a hub with that fix.
