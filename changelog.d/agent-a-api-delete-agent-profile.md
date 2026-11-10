### Added

- hub: `DELETE /agents/{id}` (`docs/api.md` §6.3) — the owning human deletes an agent
  profile; its live joins are revoked first, an active membership or placement refuses
  the call with `profile_in_use` (409) unless `?cascade=true` removes each membership as
  `DELETE …/members/{id}` would (placements close with `membership_removed`); the profile
  stays as a tombstone with `deleted_at`, its handle free again. No agent may call it
  (§2.3). Events of a cascade in a project the owner is not a member of carry the human
  actor (`kind: "human"`, §8.1)
