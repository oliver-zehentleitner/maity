### Changed

- hub: `blue-team` is no longer a role an agent of an owner from outside may
  hold (docs/api.md §6.1, §6.2): `policy.outside_roles` refuses it
  (`role_not_allowed`), a stored list reads without it, and such an agent
  falls back to `coder` (or is isolated where the list has no `coder`) with a
  `member_updated` and a notice to its owner, at the isolation pass and at its
  next resume; a security team stays among the project's own owners.
- web: the setting **Roles for outside agents** no longer offers the blue team,
  and the leave confirmation says that an owned blue-team agent stays as a
  coder.
