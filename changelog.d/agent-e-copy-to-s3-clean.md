### Changed

- hub: `maity-hub attachments copy-to-s3 --apply` also removes from the bucket what was deleted
  since an earlier run, while the hub still served from the volume: the object of a deleted
  attachment at once, an object no attachment names once it is older than 30 minutes. Its output
  gains `deleted, removed from the bucket: N`.

