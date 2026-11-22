### Added

- Contract: milestones (`docs/api.md` §6.33, a draft, not built). A milestone per project
  with `title`, `description`, an optional `due_on` and `state` open or closed, several
  open at once, with computed `progress` (done of total) and counts per status;
  `GET`, `POST …/milestones`, `GET`, `PATCH`, `DELETE …/milestones/{id}`; the events
  `milestone_created`, `milestone_updated`, `milestone_deleted`. Points the scope leaves
  open are listed in §6.33.1 with the draft's proposals, none decided.
- Contract: one optional `milestone` per card (§6.4), read as `{id, title, state, due_on}`,
  written as the milestone's id; the `milestone` filter on `GET …/tasks` (`none` for cards
  without one), used by the board and `maity task list --milestone`; recorded in the
  card's history (§6.15).
- Contract: `release.milestone` (§6.7): a release may point to a milestone, whose cards are
  then the release's cards (proposed: in place of `depends_on`, frozen into
  `release.shipped` at the close).
- Contract: every card in the resume packet's `claims` and `assigned` carries its
  milestone with the due date (§5.2); `maity milestone` commands and `--milestone` on the
  task commands in the CLI mapping (§13).
