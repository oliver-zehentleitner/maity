### Added

- runner: a placement's session now gets `MAITY_RUN_SLOTS_DIR=<scratch>/slots`,
  `MAITY_PG_DIR=<scratch>/pg` (only where the cluster's socket path fits) and `MAITY_RUN_NAME`
  set to `<handle>#<instance>`. Placed sessions can now take `tools/run_slot.sh`'s slots and
  run `with_postgres.sh`. Before this, their defaults under `~/.local/state` were outside the
  sandbox. The slots are per placement. Bounding heavy runs across placements is
  tsk-w7dx3h9mn8dp (tsk-w7qtcbzcshn9).
