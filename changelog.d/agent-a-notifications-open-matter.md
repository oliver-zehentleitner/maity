### Changed

- docs/api.md: the two `inbox` items of an open matter, `registration_pending` and `mail_disabled`,
  are never marked read by a caller (`up_to` skips them, `ids` ignores them); each reads as read once
  its matter is closed, so "mark all read" never hides an open matter (§18.3).
