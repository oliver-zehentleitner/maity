### Fixed

- web: in the Chat access history, an answer shows the side's agents it sent ("their agents …")
  beside the ticks, and a failed re-read of the first page keeps Show more for the rows still on
  screen.
- web: the German words of the Chat access history follow the page's own: Erlaubnis and Verbot
  rather than Erlauben- and Sperren-Eintrag, "angehakt" as the forms say, "ihre Seite verbieten".

### Changed

- web (fixture hub, test only): a deny logs each allow it narrows or removes, with its `deny_id`,
  after its own item, and an item's `names` covers the entry before a change, as the hub writes
  them (§9.6); the smoke test has a case for each and checks each part of the history's crafted
  items on its own.
- web: the context entry on the pitch panel's narrow-screen rule no longer names a gap the smoke
  test closed (documentation only).
