### Added

- hub: two-level subtasks with `parent`, symmetric `related` navigation,
  computed child counts and a parent filter on the board. Parent and
  dependency gates are checked together; open children block completion.
  `policy.subtasks` defaults to admin-approved proposals, with a `direct`
  option. Parent/related edits are recorded in history and mirrored or
  computed-count changes are announced on the affected cards.
