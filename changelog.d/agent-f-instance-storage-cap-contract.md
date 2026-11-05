### Added

- contract: an instance-wide limit on stored attachments, `max_attachment_storage` in the admin
  section Limits (`MAITY_MAX_ATTACHMENT_STORAGE`, default `unlimited`), with a read-only
  `attachment_storage_used`. An upload over it is `attachment_quota` with `details.scope: "instance"`.
