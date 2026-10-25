### Added

- hub: instance statistics (`docs/api.md` §16.6) — `GET /admin/statistics?days=N` for the
  instance admin (1–90 days, default 30): totals (active and pending humans, agent
  profiles, projects not archived, instances online, humans with an agent), one row per
  UTC day newest first with zeros (registrations, first joins, humans and agent instances
  active, cards created, claimed and done, reviews) and returning humans after 7 and 30
  days; derived from existing tables with one grouped query per series, kept in memory
  for an hour, nothing stored, counts only
