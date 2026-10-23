### Fixed

- web: Ticker — after a first page that failed, the next signal reads that page again instead of
  the whole history, and the page read again clears the failure it said; a live read with
  nothing new clears a failure said before; a signal before the first page is in waits for it
