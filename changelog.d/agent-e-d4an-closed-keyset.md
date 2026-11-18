### Changed

- hub: the board's closed columns (`GET …/tasks` with `status` naming only `done` and
  `cancelled`, board order, no `q`) are sorted and paged by the database, reading one card
  more than the page instead of the whole column for every page. Their `next_cursor` holds
  only the last card's key and keeps one size (about 120 characters instead of about
  5.5 kB at `limit=200`); a page of the whole board that ends on a closed card hands out the
  same cursor. Cursors given out before still page. The order is unchanged.
