### Fixed

- web: leaving a project while `start_tabs` is `null` no longer sends
  `PATCH /me`, so the default stays `null`. An explicit list that contains
  the project is updated without it.
- web: while leaving a project is in progress, Tab keeps the focus inside
  the dialog.
