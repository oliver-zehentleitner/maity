### Added

- runner: a placement's session now gets `MAITY_RUN_SLOTS_DIR=<scratch>/slots`,
  `MAITY_PG_DIR=<scratch>/pg` with `MAITY_PG_PASSFILE=<scratch>/pg.pass` (a password drawn
  once per placement, 0600, and only where the cluster's socket path fits), and
  `MAITY_RUN_NAME` set to `<handle>#<instance>`. Placed sessions can now take
  `tools/run_slot.sh`'s slots and run `with_postgres.sh`. Before this, their defaults under
  `~/.local/state` were outside the sandbox. The slots are per placement. Bounding heavy runs
  across placements is tsk-w7dx3h9mn8dp (tsk-w7qtcbzcshn9).
- hub: `scripts/with_postgres.sh` makes its cluster with `scram-sha-256` when
  `MAITY_PG_PASSFILE` names a 600 password file, and refuses a cluster made with `trust`.
  Without the variable nothing changes.

### Security

- runner: Claude Code's sandbox now denies every other placement's scratch (`denyRead`,
  `denyWrite`), listed at the start like the other clones' credentials. Codex keeps them
  hidden under the workspaces root. A start whose listing cannot be completed is refused.
