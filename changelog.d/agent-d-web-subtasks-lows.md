### Fixed

- web: fixture mode refuses an unknown subtask parent as the hub does (400 `invalid`,
  `fields.parent: unknown_task`) and applies the subtask policy to the `?as=` member, so a
  member's subtask can be tried end to end
