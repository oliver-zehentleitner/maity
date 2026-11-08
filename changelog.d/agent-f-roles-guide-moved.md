### Changed

- hub: `PUT /projects/{owner}/{slug}/roles` refuses a `guide` in a custom role as `invalid` with
  `custom[].guide: "moved"`, as docs/api.md §2.3 says: a role's guide is set with the project's
  briefings (§6.28). A role keeps the guide it already has; a new role has none.
