### Changed

- cli: `maity runner` is taken only as the first argument. `maity -- runner …`
  and `maity --for x runner …` (and an abbreviated `--fo`) are refused with
  exit 2 before anything runs; every other command keeps its global options.
