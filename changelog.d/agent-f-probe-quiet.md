### Changed

- hub: `probe_observed` wakes only when something on the pull request changed (§6.6, §8.2). A new
  report whose first observation matches the card's last announced one is filled without an
  event, and on the open release `mergeable` going between `unknown` and `mergeable` is stored
  without one. Starting or stopping to conflict still wakes.
