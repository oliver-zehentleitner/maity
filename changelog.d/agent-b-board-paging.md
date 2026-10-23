### Fixed

- hub: a page of the board's order (`GET …/tasks`, `docs/api.md` §6.4) whose last card left
  its column goes on from the first card it did not show when that card has not moved, and
  otherwise from the top of the column without the cards it showed, so no card that did
  not move is dropped from the next page
