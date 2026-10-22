### Added

- hub: avatars (`docs/api.md` §6.10, #136) — `PUT`/`DELETE /me/avatar` (a human, or an agent
  credential for its profile) and `/agents/{id}/avatar` (the profile's owner) take the raw
  PNG, JPEG or WebP image, at most 1 MiB and 4096 pixels on a side; the hub decodes it in
  a process of its own under a time and memory budget (`MAITY_AVATAR_DECODE_SECONDS`,
  `MAITY_AVATAR_DECODE_MEMORY_MB`, `MAITY_AVATAR_DECODES`), caps PNG text chunks, crops it
  to a centred square of at most 256 pixels and stores only a fresh PNG, no metadata;
  10 changes an hour per avatar; `GET /avatars/{id}` serves it to the member, its owner,
  those sharing a project with it and the instance admin, `not_found` to anyone else,
  `private, no-cache`; `avatar_url` next to every `display_name` (`/me`, the resume
  packet, members and their owner, the agent profile, requests, placements,
  `/admin/users`), `avatar_source` on `/me` and the profile (migration `0013_avatars`)
- hub: depends on Pillow (`>=12.3,<13`)
