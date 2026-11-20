### Added

- runner: a placement's session now gets `MAITY_RUN_SLOTS_DIR=<scratch>/slots`, and
  `MAITY_RUN_NAME` set to `<handle>#<instance>`. Where its socket path fits, it also gets
  `MAITY_PG_DIR=<scratch>/pg` with `MAITY_PG_PASSWORD`, a password the runner draws once per
  placement and keeps outside every sandbox. Placed sessions can now take
  `tools/run_slot.sh`'s slots and run `with_postgres.sh`. Before this, their defaults under
  `~/.local/state` were outside the sandbox. The slots are per placement. Bounding heavy runs
  across placements is tsk-w7dx3h9mn8dp (tsk-w7qtcbzcshn9).
- hub: `scripts/with_postgres.sh` makes its cluster with `scram-sha-256` when
  `MAITY_PG_PASSWORD` is set, and refuses a cluster that lets anyone in without it. Without the
  variable nothing changes.

### Security

- runner: Claude Code's sandbox now denies every other placement's scratch that exists when the
  session starts (`denyRead`, `denyWrite`), and Codex keeps them hidden. A start whose listing
  cannot be completed is refused.
