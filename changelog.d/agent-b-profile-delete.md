### Added

- hub: deleting an agent profile (`docs/api.md` §6.3) — `DELETE /agents/{id}` for its owning
  human only: its live joins are revoked first, a profile with an active membership or
  placement is `profile_in_use` (409, `details.memberships`, `details.placements`) unless
  `?cascade=true`, which removes every membership as `DELETE …/members/{id}` does (its
  placements closed with `membership_removed`); the profile stays as a tombstone with
  `deleted_at` (handle and name kept, the uploaded avatar dropped), a second `DELETE`
  answers it as it is, `GET /agents` leaves it out, and `PATCH`, the avatar and a join or
  placement naming it answer `not_found`; its handle is free for a new profile at once
  (migration `0032_agent_profile_delete`)
