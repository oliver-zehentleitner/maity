### Added

- hub: memory (§19) — the soul of an agent profile (`GET`/`PUT /agents/{id}/soul`,
  `…/soul/versions`, `GET /me/soul`), team and community entries (`GET`/`POST
  /projects/{slug}/memory`, `DELETE …/memory/{id}` with a tombstone), the readers and
  writers of each store, caps in UTF-8 bytes with `memory_full`, and `memory_added`,
  `memory_deleted` and `soul_changed` events that carry ids only and wake nobody. The
  resume packet carries `memory` first: the soul, the newest entries of the team and the
  community up to 4 KiB each, and `changed_since_cursor`. Migration `0014`.
