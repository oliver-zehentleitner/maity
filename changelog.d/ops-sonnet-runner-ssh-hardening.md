### Added

- deploy: step 3b of `SERVER-SETUP.md` switches off password login for root on a rented runner server (a drop-in, with a timer that undoes it
  until a key login and a refused password login were both seen).

### Removed

- deploy: the runner README no longer describes the move from the first single runner (step 0) or the unused `HUB_RUNNER` variable.
