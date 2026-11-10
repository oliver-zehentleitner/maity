### Added

- docs/api.md §6.1, §6.25, §15.5: a project carries a fixed opaque `id`; a runner's placement view
  carries `project_id` and `project_aliases`. The runner keys a workspace on the project id, so a
  rename or a transfer keeps the clone and the agent's credential; its configured project list
  matches current names and aliases.
