### Changed

- hub: `probe_observed` wakes only when something on the pull request changed (§6.6, §8.2). A new
  report whose first observation matches what the card's last one told the same readers is
  emitted to nobody (owners' and admins' views still see it), unless the forge contradicts the
  new report; on the open release `mergeable` going between `unknown` and `mergeable` is stored
  without an event. Starting or stopping to conflict still wakes.
