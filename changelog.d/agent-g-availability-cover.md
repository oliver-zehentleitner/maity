### Added

- hub: cover by a substitute (`docs/api.md` §6.12) — a member out beyond
  its grace under the `substitute` policy hands its held and open
  assigned cards and the requests addressed to it to the first available
  member of its cover order who may take each, visibly (`cover` on cards
  and requests, `covered_by`/`covering`, `cover_started`, `task_assigned`
  with `reason: cover`); the substitute answers on the member's behalf;
  on return what it touched stays, the rest returns (`cover_ended`); new
  cards routed to the member by area go to its substitute; a cover that
  found nobody tries again.
- hub: the coordinator gate — while the coordinator (and its
  `coordinator_substitute`) is out beyond its grace, an agent's `assign`,
  `assigned_to`, claim on another's behalf and new takeover answer
  `coordinator_unavailable`; humans are not gated.
- hub: a substitute acts with its own trust and role: an entry that has
  become a guest or a proxy does not cover, owner decisions (`trust:owner`
  included) go to humans only, a `review` card never to a holder of the
  done authority, and a card under an open takeover stays with the
  covered member (`left`).
