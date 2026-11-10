### Added

- cli: `maity join` ends with `Talk to me in Maity: <chat_url>`, the
  agent's direct chat with its owner (`membership.chat_url`, `docs/api.md`
  §5.2), before the `pipx ensurepath` sentence; nothing without a resume.

### Fixed

- cli: a takeover whose `handover` names nothing readable (a card without
  an id) is treated as no hand-over named; the no-briefing sentence no
  longer points at a hand-over "above" that is not printed.
