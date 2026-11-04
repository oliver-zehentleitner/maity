### Fixed

- web: a long line in a request's code block (600 characters) no longer widens the inbox past the window,
  nor every collapsed row below it; in a card note the same line scrolls in its block instead of making the
  whole card panel scroll sideways. Long links in text drawn as Markdown wrap, the visitor's pages
  included, so a note's no longer scrolls the card panel, nor a project message's or a public card's the
  page on a phone; so does a card link shown by its URL. The lists drawn as grids hold their rows in one
  column of `minmax(0, 1fr)` (#1347, tsk-6bn80bppb5e5).
