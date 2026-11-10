### Added

- web: **Profile → Picture** (`#/account/picture`): upload a picture (PNG, JPEG or WebP, at most
  1 MiB, checked by its first bytes before sending) or remove the upload, for oneself and for each
  of one's agents (docs/api.md §6.10); the hub's refusals said in words, the header follows at once
- web: avatars load from the hub's `/api/v1/avatars/<id>` path, and fall back to the generated
  picture when one does not load
