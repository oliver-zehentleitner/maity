### Changed

- docs/api.md §8.7: without `MAITY_ATTACHMENT_DIR` the hub no longer refuses to start; it runs with
  attachments off and answers attachment calls with `409 attachments_not_configured`. A set but
  missing or unwritable directory still stops the hub.
