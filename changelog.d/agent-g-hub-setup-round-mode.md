### Changed

- hub: a project's `setup` is never `null`; a migration writes every option off and `cards: []`
  into a project without it, and the column is `NOT NULL` (§6.1).

### Removed

- hub: a jour fixe round has no `mode` any more, in the API, the contract and the database; every
  round runs in its group chat (§20.5). The dashboard no longer has a text for a project without
  `setup` (alpha, no compatibility layers).
