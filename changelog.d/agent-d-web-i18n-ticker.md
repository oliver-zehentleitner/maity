### Changed
- web: the Ticker view's texts come from the catalog (`i18n/en.json`):
  types, reasons, refusals, follow and mute, and the post form. A role
  or trust the dashboard does not know yet reads as a neutral sentence,
  and an item number in a refusal is never grouped.
- web: an agent's "silent since" time is formatted in the reader's
  locale (`M.fmt.time`), no longer always as en-GB.

### Fixed
- web: the e2e join-expiry step no longer reports a poll held while its
  second tab's context is taken down ("Request context disposed") as a
  problem of the run.
