### Changed

- cli: **Upgrade note:** from 0.1.0a13, a `runner.toml` with a
  `[harness.antigravity]` table is refused and the whole runner does not
  start; remove that table before upgrading.
- cli: **Upgrade note:** from 0.1.0a13, a runner that manages a tool
  (`install` or `update` set on a harness) needs hub 0.1.0a8 or later
  (#1801); a runner that manages no tool keeps working with an older hub.
- cli: **Upgrade note:** a runner whose `runner.toml` has `[harness.codex]`
  is refused at `hello` by every hub up to 0.1.0a7, before 0.1.0a13 too;
  it needs a hub with the fix of tsk-z7f0xt4k1dx7 (#1872).
