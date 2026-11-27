### Changed

- hub: the cards whose public page names a member are found by one pair of readers for a member's change and for a
  person's pages (`public_cards.held_or_noted_by`, `edited_by`); each caller still freezes its own membership ids
  once and keeps its project selection and order, IN lists are cut at `chunks.CHUNK`, and `naming` of an empty
  set is still one statement.
