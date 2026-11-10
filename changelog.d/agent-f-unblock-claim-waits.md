### Fixed

- docs/api.md §7: when a `while_open: wait` request is answered or withdrawn, only the holder's
  waits filed at or after the start of the current claim keep the card `blocked`. An earlier wait
  (filed while the card was unheld, or under an earlier claim the holder released) no longer
  holds the block until it is answered too.
- docs/api.md §6.12: a cover's move of a held card to the substitute, and its return to the member,
  set `claim.since` to the move, as a claim and a takeover do. Before, `claim.since` kept the
  covered member's claim time, and a wait the new holder filed before the move could keep the card
  `blocked`.
