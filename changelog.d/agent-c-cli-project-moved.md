### Fixed

- CLI: a project with a new full name (an owner's or the project's rename, a transfer) no longer
  stops every command with `not_found`. The CLI asks `GET /me` once, keeps the new name, says
  `project is now <owner>/<slug>` and repeats the call there. `maity wait` keeps waiting at the
  new path, within its `--timeout`.
