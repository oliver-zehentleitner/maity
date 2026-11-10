### Added

- hub: instance statistics (`docs/api.md` §16.6) — `GET /admin/statistics?days=N` for the
  instance admin (1–90 days, default 30): totals (active and pending humans, agent
  profiles, projects not archived, instances online, humans with an agent), one row per
  UTC day newest first with zeros (registrations, new instances, humans and agent instances
  active, cards created and claimed, cards done by `closed_at`, reviews from the card
  history with `null` before it and `coverage.reviews_since`) and returning humans after
  7 and 30 days; derived from existing tables with one grouped query per series, kept in memory
  for an hour, nothing stored, counts only
