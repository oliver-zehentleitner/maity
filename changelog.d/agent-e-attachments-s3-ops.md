### Added

- hub: `maity-hub attachments copy-to-s3` copies the files of the `local` store into the bucket of
  the `s3` store, under the same key. It skips what the bucket already holds with the same SHA-256,
  so it can run again, and it only counts without `--apply`. It never overwrites an object the
  hub wrote with other bytes, it does not copy the file of a deleted attachment, and it checks
  each object's size and metadata after the copy. The hub now writes each object's
  SHA-256 as object metadata.
- deploy: chart values `attachments.store` (`local` by default, or `s3`) and `attachments.s3.*`.
  The credentials come by Secret reference, and their key names are configurable. The chart README
  describes how to move a volume's files into a bucket.
