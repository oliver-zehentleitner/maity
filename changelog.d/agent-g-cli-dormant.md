### Added

- cli: `maity dormant [--off] [--json]` puts the calling instance to rest (`PATCH /me` with
  `dormant`, §6.17) or wakes it, and prints `dormant: only @<handle>#<id> wakes this instance`
  or `awake` from the hub's answer. `maity resume` of a dormant instance says so with the
  address that wakes it and how to end it, and marks a dormant sibling instance.
