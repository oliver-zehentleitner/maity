### Added

- contract: every answer under `/api/v1/` carries `Maity-Web-Version`, the version of
  the dashboard the hub serves, and the app shell carries the same value, so an open
  dashboard can notice a new deploy and offer a reload (docs/api.md §1.1, §16.11).
