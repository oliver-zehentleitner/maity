### Added

- docs: `docs/how/infrastructure.md`, a page of "How Maity works" on the hub,
  its database, background passes, waits, stored data, the Helm chart, self-hosting
  and the security areas.
- docs: a figure of the hub on that page, `docs/img/how-hub-inside.png`,
  reduced to 256 colours.
- docs: extra copies of the hub need PostgreSQL and attachments outside a
  local directory; `serve` never migrates and refuses a schema that isn't
  at the revision this version expects.
- context: the docs-images entry covers diagrams, drawn by the designer
  and reduced the same way as the screenshots.
