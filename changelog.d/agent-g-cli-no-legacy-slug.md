### Removed

- cli: the runner no longer takes over a clone recorded before the project namespace; a clone
  lives at `<workspaces>/<project_id>/<clone>` only, and `runner gc` reads the record's `project`
  (alpha, no compatibility layers).
