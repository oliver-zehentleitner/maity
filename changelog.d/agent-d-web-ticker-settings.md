### Added

- web: Project settings show the change ticker (`settings.ticker`, docs/api.md §17.3): on or off,
  the contract files, and who implements which section, written as lines `<section>: <token> …`,
  with tokens that name nobody now said as unresolved; every member reads it, a human admin
  changes it. Beside it the forge webhook (§17.4) for that human: whether a secret is set and the
  last delivery, create or rotate the secret (shown once with the payload URL to enter at the
  forge), remove it. A link leads to one's own follows and mutes in the Ticker
