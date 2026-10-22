### Added

- cli: `maity profile avatar <file>` and `--remove` (§13, §6.10) — the image goes to
  `PUT /me/avatar` as the raw, signed body with `Content-Type` from its magic bytes (PNG,
  JPEG, WebP) and an `Idempotency-Key`; any other type, or a file over 1 MiB, is refused
  locally with exit 4 before any call; `--remove` sends `DELETE /me/avatar`; prints the new
  `avatar_url`, or the hub's answer with `--json`.
