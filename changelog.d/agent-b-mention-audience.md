### Changed

- hub: a message's mention adds `member:<id>` only for a member `to` does not already
  reach (`all`, its role, its own `member:`); the mention stays in `mentions`
  (`docs/api.md` §8.2, §8.6)

### Fixed

- hub: removing a member also clears the stored `reports_to` of an active placement
  that creates a profile, and the exchange applies a join's `reports_to` only while it
  names an active member, checked after the project lock (`docs/api.md` §6.2)
