### Fixed

- hub tests: the card paging tests read a statement's text without its identifier quotes, so they
  pass on MariaDB, whose dialect writes `card.body` as ``card.`body` ``.
