### Added

- docs: availability and cover in the API contract (`docs/api.md` §6.12, contract
  only, not built yet) — per-member `availability`, `POST /me/limit` and
  `maity limit`, a per-membership `availability_policy` (`wait` or `substitute`)
  with humans on both sides of cover, the coordinator gate, a covering member's
  right to read and answer covered requests, leases held for at most 24 hours
  under a declared limit, the owner's `absence.until` capped at 90 days, a
  human's away reason shown only where they choose, the events
  `member_availability_changed`, `cover_started`, `cover_ended` and
  `member_limit_ended`, and the runner's `rate_limited` placement state (§15.7)
