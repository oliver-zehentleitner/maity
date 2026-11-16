### Changed

- hub: an address that can never be a page answers `404` with the app shell as its body,
  instead of `200`. That is a first segment that is no handle, a reserved word without a
  route, more than 6 segments outside a project's Why, a project view word that is no
  view, and `/<handle>/agents`. Handle- and project-shaped addresses stay `200`
  (docs/api.md §16.11).
