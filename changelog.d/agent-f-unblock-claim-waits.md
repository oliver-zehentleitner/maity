### Fixed

- docs/api.md §7: when a `while_open: wait` request is answered or withdrawn, only the holder's
  waits filed at or after the start of the current claim keep the card `blocked`. An earlier wait
  (filed while the card was unheld, or under an earlier claim the holder released) no longer
  holds the block until it is answered too.
