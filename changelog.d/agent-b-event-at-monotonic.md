### Fixed

- hub: an event's `at` never runs backwards within a project: under the project's lock it
  is the later of the clock and the project's last event, so a clock step back or a replica
  whose clock is behind keeps `at` in `seq` order (`docs/api.md` §18.2)
