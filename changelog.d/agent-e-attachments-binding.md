### Added

- hub: attachments in messages (§8.7): `POST /projects/{slug}/events` and chat messages take
  `attachments` (up to 10 pending uploads of the poster, bound in the post's transaction; the
  body may then be empty), every message carries `attachments` in its payload, redacting a
  message tombstones its attachments and removes their bytes, and the project view shows
  `attachments: {used, quota}` to a caller with `project:admin`. A message that names an attachment
  without a configured store answers `attachments_not_configured`.
