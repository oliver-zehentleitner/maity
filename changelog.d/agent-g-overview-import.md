### Added

- hub: `GET /projects/{owner}/{slug}/overview` (`docs/api.md` §6.11) — the board's
  column counts in the board's window, the open requests the caller may
  see with their priorities, and the latest reports with the probe's
  facts.
- hub: `POST /projects/{owner}/{slug}/tasks/import` (§6.14) — a card from an issue
  of the project's own repository, read from the forge before the
  write: the issue's title, its body quoted under the hub's header with
  every `@` neutralised, its link observed from the same read, and
  `imported_from`; `already_linked` while a card from it is open.
