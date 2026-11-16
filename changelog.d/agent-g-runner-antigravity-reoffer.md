### Changed

- cli: the `antigravity` harness (agy) is offered again. A `runner.toml` with
  `[harness.antigravity]` is accepted by `maity runner check` and `serve` instead of refused.
  agy keeps the one `command(maity)` grant the runner cannot fully confine from its own
  settings, so it runs with a known residual risk the owner accepted; OS-level confinement of
  that command is being added incrementally (tsk-zjv2xyhyggnm). Re-offering does not widen
  agy's grants: it still gets only `command(maity)` plus the `read_url` hosts, and the exact
  and prefix command grants stay dropped (docs/runners.md).
