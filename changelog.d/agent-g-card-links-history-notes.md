### Added

- hub: card links (`docs/api.md` §6.13) — `POST`/`DELETE
  …/tasks/{id}/links` and `links` on card creation; forge links parsed and
  checked by the hub, URL links; the probe reads the project's own
  repository's issues and pull requests in one GraphQL read per
  repository and emits `link_observed`; every card shows its `links`.
- hub: the edit history (§6.15) — `GET …/tasks/{id}/history`, one entry
  per changed field with `before`, `after` and a diff for title and body,
  the creation's one entry, and `POST …/history/{id}/redact` for a human
  with `events:admin`, which redacts the same values in the write's event.
- hub: notes (§6.16) — `GET`/`POST …/tasks/{id}/notes`, `…/resolve` by the
  card's creator or `tasks:admin`, `…/redact`; caps of 50 open and 200 in
  all with 150 for agents, 20 per member in 10 minutes; `note_added`,
  `note_resolved`; every card shows `notes: {open, total}`.

### Changed

- hub: `task_created` and `task_updated` carry `fields` and `history` and
  never the card's `body`.
