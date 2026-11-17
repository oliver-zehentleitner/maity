### Changed

- hub: `GET …/roles` answers the list's `version`, and `PUT …/roles` requires the
  `base_version` it was made on (docs/api.md §2.3 "Version.", tsk-pw0aagxnydr9). A stale
  one is `409 conflict` with `details.current_version` and `details.base_version`, and
  nothing changes, so of two admins saving at once exactly one wins. A `PUT` that changes
  nothing keeps the version. The version is stored in the new column
  `project.roles_version` (migration `20261117100000_roles_version`) in the same write as
  the list.
- web: Settings → Members and agents → Roles sends the version it read. When someone
  else saved first, the draft stays, the page says so and offers **Reload**. The read
  just before saving (#1911) is gone, since the hub's check covers it.
