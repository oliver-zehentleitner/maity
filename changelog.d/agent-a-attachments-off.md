### Changed

- docs: §8.7 "Attachments off" says what runs without an attachment store: every attachment call,
  delete included, answers `attachments_not_configured` before any other check; redaction still
  tombstones, the sweep waits for a store, the project view keeps `{used, quota}`.
