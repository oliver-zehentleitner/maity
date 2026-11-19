### Changed

- hub: the project overview no longer reads every reported card and every open request to
  build its answer. The database sorts and limits the latest reports and reads only the shown
  cards in full. The open requests are counted in one grouped statement, and held, covered and
  jour fixe requests are still decided by the listing's own rule. The response is unchanged.
  On SQLite with 3000 cards and requests, the overview's peak memory went from about 12.6 MB
  to 0.4 MB and its median time from about 90 ms to 25 ms.
