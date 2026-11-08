### Fixed

- hub: `GET /projects/{owner}/{slug}/roles` now answers `builtin` next to `custom`, as docs/api.md
  §2.3 promises: each built-in role with its `description` (the role table's text), its `guide` as
  it applies in the project (today the hub's default) and its own `scopes`.
