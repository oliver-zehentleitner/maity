### Changed

- Dashboard: the first half of the board's words come from the catalog (`board.*`): a card's kind,
  why a release is not ready, the claim line, subtasks, parent and related cards, the checkpoint and
  the report, the why line and the pull requests table. A sentence around a link or a member is one
  key read with the new `M.tn`, which places the node where the sentence puts it; `make check`
  checks `M.tn` keys as it does `M.t`'s. The baseline for `board.js` is lowered.
