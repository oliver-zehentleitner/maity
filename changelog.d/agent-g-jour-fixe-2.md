### Added

- hub: the jour fixe, part 2 (`docs/api.md` §20.5) — every round runs in
  its own group chat, created by the hub with the invited members, closed
  with `round_closed` when the exchange ends, read along by the project's
  owners, and written only through the round (`round_thread`); the
  moderator's statement with numbered topics, items and proposals; the
  response, reply and rejoinder steps and up to three further steps, each
  opened only with someone eligible and waking only those members once
  (`jour_fixe_step_opened`); `jour_fixe_exchange_closed` with the report's
  due time; a round without a statement goes straight to its report.

### Changed

- hub: a round's thread, its statement and its posts wake nobody.
