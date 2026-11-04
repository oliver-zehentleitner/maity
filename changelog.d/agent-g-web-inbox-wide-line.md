### Fixed

- web: a long unbroken line in a request (a code line of 600 characters, long links) no longer widens the
  inbox past the window, nor every collapsed row below it; in a card note the same line scrolls in its block
  instead of being cut off. The lists drawn as grids hold their rows in one column of `minmax(0, 1fr)`
  (#1347, tsk-6bn80bppb5e5).
