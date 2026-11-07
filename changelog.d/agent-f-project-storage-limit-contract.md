### Changed

- docs/api.md §8.7, §16.5: the bytes of attachments one project may store are the admin limit
  `max_attachment_storage_per_project` (environment `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`,
  default 1 GiB, 1 MiB to 1 PiB or `unlimited`), with the source rules of every limit; the
  project view's `attachments.quota` is `null` under `unlimited`.

### Removed

- The environment variable `MAITY_ATTACHMENT_QUOTA`, without alias or fallback; set
  `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT` or the admin field instead.
