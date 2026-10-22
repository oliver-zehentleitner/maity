### Changed

- docs/api.md: a preset change keeps `policy.spawn_consent_by` (§6.1); §8.6 says the mention
  word boundary is ASCII only (before the `@` too, so `andré@agent-b.example` mentions), and
  what "already in the audience" means for the ping rate. A mention of a member the message's
  `to` already reaches adds no `member:` token to the audience (§8.2, §8.6), so it cannot wake
  a supervised member under `to: all`; the hub follows in a separate change.
