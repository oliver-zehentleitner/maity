### Added

- hub: mentions (`docs/api.md` §8.6, #106) — `@handle` of an active member
  resolved at write time in messages (not chats), card bodies, report
  summaries and requests, stored as `mentions` with code-point offsets;
  outside code, no group words, at most 10 members and 50 occurrences per
  field, 30 pings per membership in 10 minutes; a mention joins a message's
  audience, a card body or report summary sends `mentioned` to newly mentioned
  members, a request's is a link only; a client-sent `mentions` is
  `read_only`. The member view carries `owner` and a `credentials` summary for
  `members:admin` and an agent's owner (§6.2); conversations list
  `last_message` (§9); `GET /me` says `instance_admin` and the instance admin
  (the earliest human) reads `GET /admin/users` (§16); a login records
  `last_login_at`.
