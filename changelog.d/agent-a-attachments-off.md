### Changed

- docs: §8.7 "Attachments off" says what runs without an attachment store: every attachment call,
  delete included, answers `attachments_not_configured` (list, metadata, content and delete before
  any other check, the upload after its size cap, membership and `events:post`); redaction still
  tombstones, the sweep waits for a store, the project view keeps `{used, quota}`.
