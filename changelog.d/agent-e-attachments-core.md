### Added

- hub: attachments (§8.7), the core: `POST /projects/{slug}/attachments` (a raw file up to 10 MiB,
  its type sniffed, an image decoded and encoded again), `GET …/attachments/{id}` and `…/content`
  (a file is only served as a download, with the hardening headers), `GET …/attachments?status=pending`
  and `DELETE …/attachments/{id}` for pending uploads; the `attachment` table (migration `0063`), a
  local blob store, the project quota (`MAITY_ATTACHMENT_QUOTA`), the per-membership caps and rate.
  Naming attachments in a message, redaction and the sweep follow. Without
  `MAITY_ATTACHMENT_DIR` the hub starts and the calls answer `attachments_not_configured`.
