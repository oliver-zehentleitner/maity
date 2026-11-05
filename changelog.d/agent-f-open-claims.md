### Changed

- Hub: every reader of claims uses one condition, `cards.open_claims`, and the closed statuses
  are written down once (`cards.CLOSED`); no behaviour changes. A test fails when a module keeps
  its own copy, the mistake #1304 and #1305 each found on their own.
