### Fixed

- web: a card's status or assign menu on the board stays open, on the same item, when the board redraws without the
  reader doing anything: the closed cards arriving after the first draw, or the presence refresh under the Silent filter.
  It used to close under the reader's click, which also made web-e2e's `two_signatures_step` fail now and then.
