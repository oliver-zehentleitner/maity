### Added

- hub: `POST /runner/placements/{id}/join` (§15.9) — a runner picks up a join for its
  placement's agent: the URL and code in the answer only, three pickups per generation, a
  repeat revokes the unused join; the exchange binds the placement's credential, and for a
  new profile creates it there, owned by the placement's creator. A member's pickup is a new
  instance within `max_instances`; a rejoin replaces the revoked instance (the only join that
  may), never a live one. `join_picked_up` names the pickup, never the code.
- hub: `POST /me/resume` accepts `supervisor: "maity-runner/<version>"` (§15.11):
  `hints.duty`, `membership.placement`, a "Supervised" section in the rules, and a long-poll
  that is not woken by what only `all` addresses (but `state_changed`, `policy_changed`,
  `rules_changed`). Migration `0023`.
