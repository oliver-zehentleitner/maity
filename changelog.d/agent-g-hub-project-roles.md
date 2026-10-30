### Added

- hub: project roles (`docs/api.md` §2.3) — `GET, PUT /projects/{owner}/{slug}/roles`
  keeps up to 12 roles of a project's own, each on a built-in base with a description and a
  guide (the rules quote it with `guide_by`); a join, an invitation and a membership `PATCH`
  take them, the member view carries `role_base`, and a role still in use cannot be removed
  (`409`, `role_in_use`). A project role has exactly its base's scopes; `role:<base>` reaches
  its members in requests, messages and wakes, the done authority's merge wake and the
  cover order of `substitutes`.

### Changed

- hub: a role the hub does not know has no scopes; it no longer counts as a coder.
