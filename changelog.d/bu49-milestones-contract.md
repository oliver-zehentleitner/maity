### Added

- Contract: milestones (`docs/api.md` §6.33, not built). A milestone per project with
  `title` (unique in the project), `description`, an optional `due_on` (a calendar date)
  and `state` open or closed, several open at once, at most 200 per project
  (`milestone_quota`); computed `progress`, done of the cards not cancelled, and counts per
  status; `GET`, `POST …/milestones`, `GET`, `PATCH`, `DELETE …/milestones/{id}`, managed
  with `tasks:admin`; a delete clears the milestone from its cards and is refused while a
  release names it (`conflict`, `details.reason: release`); only a member closes one. The
  events `milestone_created`, `milestone_updated`, `milestone_deleted`, readable by
  everyone, wake nobody.
- Contract: one optional `milestone` per card (§6.4), read as `{id, title, state, due_on}`,
  written as the milestone's id by whoever may edit the card; not inherited by subtasks;
  the `milestone` filter on `GET …/tasks` (`none` for cards without one), used by the
  board and `maity task list --milestone`; recorded in the card's history (§6.15).
- Contract: `release.milestone` (§6.7): a release may point to a milestone, whose cards are
  then the release's cards in place of `depends_on`, frozen into `release.shipped` at the
  close; a release never carries both.
- Contract: every card in the resume packet's `claims` and `assigned` carries its
  milestone with the due date (§5.2); `maity milestone` commands and `--milestone` on the
  task commands in the CLI mapping (§13).
- web: words for the new error code `milestone_quota`.
