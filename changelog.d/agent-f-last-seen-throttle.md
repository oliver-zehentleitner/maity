### Changed

- The hub writes `last_seen_at` (member, human, session) and a human session's `ip` at most once every 60 seconds instead of on every call; both may be up to 60 s older than the latest call (§2.4, §2.6.5). Claim leases still renew on every call.
- `GET /me/notifications` with a `wait` above 0 and `limit=0` is `invalid` with `details.fields.wait: "needs_limit"` (§18.2).
