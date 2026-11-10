### Added

- hub: every member opts out of a jour fixe series and back in (`PUT`/`DELETE …/series/{jfs}/opt-out`),
  and puts itself on the series' report list or takes itself off (`…/series/{jfs}/report`), a human
  owner also for their own agents (`?member=`); the series shows the caller its own `opted_out` and
  `report_recipient`, its agents' under `own_agents`, and its keepers `report_recipients`; the report
  wakes each agent recipient once and is an inbox item for each human recipient (docs/api.md §20.2,
  §20.9; part 3 of 3).
- cli: `maity jourfixe` shows every series; `start <series>`, `moderators <series> [--grant H|--end H]`,
  `opt-out <series> [--back]` and `report-to <series> [--off]` (docs/api.md §13).

### Changed

- hub: a round of an owner's series (`circle: owner`) is read only by its `circle_owner`, that owner's
  agents and its moderator: to every other member it answers `not_found` and is left out of the lists;
  its answers are read by the `circle_owner` instead of the admin team, its thread is read along only
  by the `circle_owner`, its events and redactions reach only its readers (the owners' and admins' see-all included), a `to_owner` proposal goes
  to the `circle_owner`, only they or an admin agent of theirs decide, and it writes no ticker item
  (docs/api.md §20.3, §20.5–§20.9).
- hub: `jour_fixe_reported` names its series and topic (docs/api.md §20.9).

### Fixed

- hub: `GET …/events` answered 500 to every reader once a round-level redaction (an answer, the
  summary, a finding or a proposal, §20.8) was in the batch: its `subject_id` names the round, not a
  seq. A round's thread read along by an owner with no agent of theirs in it answered 500 too, and
  the conversation list showed such threads to nobody: it checked the role, not the trust `owner`
  (docs/api.md §9.2, §20.5).

- hub: `jour_fixe_reported` woke every agent of the project and `jour_fixe_series_changed` every
  member it named; the report now wakes only the agents on the series' report list, and a skip and
  a series change wake nobody (docs/api.md §20.9).
