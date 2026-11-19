### Changed

- hub: `GET …/tasks` reads only the order's keys of the cards the filters let
  through and the full rows of the page's cards alone, so a page no longer
  loads every card's body and report (tsk-ybc2ma72dzvq). With `q`, the search
  reads card text a batch at a time, starting at the page's size, and a card's
  notes only when its own text did not match or it is shown, so it no longer
  loads every note body of the project. On a seeded hub of 1,000 cards (SQLite)
  a page of 50 answers in about 22 ms at the median with a peak of about
  0.8 MiB, a search that finds one card in about 34 ms
  (`hub/tests/test_load_card_paging.py`).

### Fixed

- hub: a search's next page on the board's order (`GET …/tasks?q=…` with the
  cursor) goes on after the last card shown even when that card no longer
  matches or has left its column, so a card that began to match between two pages is no longer
  skipped (§6.4).
