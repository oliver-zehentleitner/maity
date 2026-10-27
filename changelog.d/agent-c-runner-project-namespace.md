### Changed

- cli runner: the project namespace (§6.25, §15.5). Placements need a full name and a `project_id`;
  clones live at `<workspaces>/<project_id>/<clone>` and tmux sessions are named by the id, so a
  rename or transfer keeps the clone; a clone recorded before the namespace under its slug is
  taken over in place for the same agent; `limits.projects` takes full names only, matched
  against the current name and `project_aliases`; the status file lists `project_id`
