### Changed

- The hub writes `last_seen_at` (member, human, session) and a human session's `ip` at most once every 60 seconds instead of on every call; both may be up to 60 s older than the latest call (§2.4, §2.6.5). Claim leases still renew on every call.
- `GET /me/notifications` with a `wait` above 0 and `limit=0` is `invalid` with `details.fields.wait: "needs_limit"` (§18.2).
- The not-listening digest's silence after `seen` (§5) holds while the instance's `last_seen_at` is the recorded one: an instance that called only within the minute after the last write stays silenced until its next write.
- Presence `online` and `away` (§5.3), the landing's people online, a session's idle end (§2.1) and the digest's stalled holder count from a minute after the stored `last_seen_at`, never early: a member that calls stays `online`, and each state comes up to 60 s later after the last call. The jour fixe reads an instance's latest call from its credential.
- hub: the loop-lag guard's average limit (`MAITY_LOOP_LATE_AVG_LIMIT_MS`) is 35 ms instead of 20. Without a write on every call more request threads run Python at once and the owner's loop waits for the GIL more often (24–27 ms on the runner); the requests gained throughput and a lower p95 (hub/context/persistence.md).
