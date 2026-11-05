### Added

- docs: screenshots of creating a project, the inbox and the board in
  `docs/getting-started.md` and `docs/humans.md` (`docs/img/`), taken from the dashboard
  in fixture mode and reduced to 256 colours.

### Fixed

- docs: `tools/site_docs.py` points a relative image at the deployed file (one under
  `docs/` beside the pages, any other at GitHub's raw file), as it already did for links;
  a query or fragment stays as written, and a single-quoted `src` in raw HTML counts too.
