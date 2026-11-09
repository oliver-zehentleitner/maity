### Fixed

- docs/api.md §7: a `while_open: wait` request filed before its asker claimed the card no longer
  keeps the card `blocked` after the claim. When a later wait is answered or withdrawn, only the
  waits filed under the current claim keep the block. Before, the earlier one held the card
  blocked until it was answered too.
