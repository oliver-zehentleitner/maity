### Fixed

- hub: a page of the board's order (`GET …/tasks`, `docs/api.md` §6.4) whose last card left
  its column goes on from the first card it did not show, so a move that ranked the cards
  before it no longer drops an unmoved card from the next page
