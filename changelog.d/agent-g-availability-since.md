### Fixed

- hub: a member's `availability.since` for a state the hub has not stored yet
  (an agent that never resumed) is the member's joining, not the time of the
  read, so two reads of the same state agree (`docs/api.md` §6.12).
