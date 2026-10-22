### Changed

- docs/api.md §6.12: the 24-hour lease bound holds within one outage (clearing and declaring a new
  limit after the member was `available` starts a new one, accepted because any call renews leases,
  §2.4); a limit's extension never shortens a lease; `show_reason_in` from an agent is `invalid`;
  cover never moves the `contract_arbiter` seat — a human names a new arbiter (also §2.3).
- docs/api.md §6.2, §7: a pending cross-owner `reports_to` pair is withdrawn only by the asker and
  the edge's two owners; anyone else, an admin agent included, gets `forbidden` with
  `details.reason: "pending_consent"`, a superseding `PATCH` by an agent other than the asker too.
- docs/api.md §6.2, §6.3: removing the member named in `policy.contract_arbiter` (an agent profile's
  cascade included) sets it to `role:admin` and emits `policy_changed` addressed to the project's
  human owners and admins as well.
- docs/api.md §17.4: requests to the forge webhook that do not verify are limited to 60 per minute
  per source address and never set `last_result` (`signature` and `too_large` are no longer values).
- docs/api.md §17.5, §17.6: a manual post's tokens resolve to `member:` tokens with `why:
  "addressed"` and `wake: true`; a manual `to: all` wakes every member through their own tokens.
- docs/api.md §9.1: a direct conversation's messages take `before=` and answer `earlier`, as a
  group chat's do.
