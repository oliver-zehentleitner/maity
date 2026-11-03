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
