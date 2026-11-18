### Changed

- web: the board's Done and Cancelled columns each read one page of the 50 cards closed last
  (`limit=50`) at load, instead of every closed card of the 14-day window in pages one after
  another (about 790 cards, 4 pages, 546 kB on the maintainer's project). **Show more (N
  loaded)** under the column reads its next page of 50 with the hub's cursor, is disabled
  while it reads, keeps the focus and is gone after the last page; the column's count is the
  cards loaded. A write that reads the board again keeps as many closed cards as were loaded,
  up to 200 per column. A closed card not loaded yet that the board is opened on opens in its
  panel, read by itself.
