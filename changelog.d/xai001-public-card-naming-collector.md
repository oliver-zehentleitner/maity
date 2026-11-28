### Changed

- hub: the cards whose public page names a member are found by one pair of readers for a member's change and for a
  person's pages (`public_cards.held_or_noted_by`, `edited_by`); `naming` still freezes its membership ids once
  (one statement when empty, four on a one-chunk set) and `pages_of_member` keeps its former order of statements
  (when mine is not empty, four plus one edited-notes statement per distinct-project chunk, five on a one-chunk
  set; four when mine is empty, because the edited-notes read is skipped), passing holder and author a SELECT
  rather than a frozen holding set; IN lists are cut at `chunks.CHUNK`.
