### Added

- hub: personal requests (§7) — requests the hub files to the human who owns an agent
  profile (`to: profile_owner:<agent id>`), member of the project or not. They are read,
  answered and withdrawn through `GET /requests/{id}`, `POST /requests/{id}/answer` and
  `…/withdraw`, and listed in `GET /requests` with `personal: true`. The project's request
  routes never show them to anyone but the asker. Their events carry `{id, personal,
  status}` only, and a closed one keeps its card as it was. A caller's `to:
  profile_owner:…` is `invalid`. Migration `0015`.
