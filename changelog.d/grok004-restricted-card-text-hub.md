### Added

- hub: a card's restricted text (docs/api.md §6.4), part one: `GET`, `PUT` and `DELETE`
  `…/tasks/{id}/restricted` for the set `settings.restricted_access` names (closed without
  the setting), with its version, the last 50 changes and `Cache-Control: no-store`; access
  checked before the body and before an idempotent replay; write caps per membership and
  card, 200 texts per project; never on a card, a list, a search, a history or the
  overview; the writer's own texts in their export while they are in the set; a deleted
  account's memberships and agents leave the private event lists.
