### Fixed

- hub: of two concurrent redactions of one event, only the first writes its tombstone and
  emits `event_redacted`; the other answers with the tombstone that stands, as a repeat does
  (`docs/api.md` §8.5)
