### Changed

- hub: the public Board leaves out a not-done `security` card with
  `public_cards.shown_clause`, the condition the outsider's reads use, instead
  of a copy of the rule; it shows the same cards. A test holds `shown` and
  `shown_clause` to the same answer over every status and a label matrix.
