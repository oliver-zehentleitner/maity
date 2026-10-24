### Added

- hub: versioned project onboarding, editable by human admins or an admin
  agent for that key alone; a live default briefing and basic member/role/
  coordinator check-in target in resume, with personal briefings winning.
- hub: one durable check-in per membership after a targeted message or
  first claim; broadcasts and group chats do not count, removed targets
  reset to coordinator, and onboarding text stays out of events.

### Changed

- hub: announce changed settings keys without free text. Migration 0042
  stores the onboarding version across resets and check-in timestamps,
  including backfilled historical claims. Availability stand-ins follow
  when the availability producer merges.
