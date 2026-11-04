### Changed

- hub: `maity-hub attachments copy-to-s3` without `--apply` also counts what a run with it would
  remove from the bucket, as `deleted, to remove from the bucket: N`, and removes nothing. A
  failing clean-up at the end of a run counts as failed, and the run exits non-zero.

### Fixed

- hub: the attachment sweep no longer stops at a folder of a project the database does not
  know, also one it cannot read (`lost+found` on the volume); it leaves the folder alone and
  names it once in the log.
