### Added

- hub: attachments can live in an S3-compatible bucket (`MAITY_ATTACHMENT_STORE=s3` with
  `MAITY_ATTACHMENT_S3_BUCKET`, `_ENDPOINT`, `_REGION`, `_PREFIX`, `_ACCESS_KEY_ID`,
  `_SECRET_ACCESS_KEY` and `_ALLOW_HTTP`), so several hub replicas share them. `local` stays the
  default, and a laptop or single-server hub changes nothing. Plain `http` to the bucket is only
  allowed with its own switch, and only to a host inside the cluster. Credentials are never logged.

### Changed

- hub: an attachment download past 1 MiB now streams instead of being read into memory whole. Its
  SHA-256 is checked on the way, and bytes that do not match end the answer short of its
  `Content-Length`. Smaller files are still checked before the answer starts.
- hub: an upload now writes its bytes before its database transaction and outside the project's
  lock, so a slow store never holds the lock or a database connection. The quota and pending bounds
  are checked before the write as well. A refusal or a failure after the write began keeps the
  upload counted against the rate. The row is committed only within 5 minutes of the start of the
  write; a slower upload is refused with the new error `503 upload_expired`, and may be sent again.
  When the transaction does not commit, the bytes are removed afterwards; if that fails, the sweep
  removes them after 30 minutes (until now ten). Under `s3` the sweep reads a blob's age from the
  store's own clock, so the hub's clock may differ from it. The sweep likewise asks the store
  outside the lock.
