### Added

- hub: the swarm page (`docs/api.md` §6.22) — `GET …/projects/{slug}/swarm`
  with `live` (every active member's presence, instances online, held cards,
  read at the call) and the window's counters per member and in totals:
  cards done by their last holder, reviews from the card history only, pull
  requests by their first retained merged observation, the pooled
  claim-to-done and review-to-done medians (three samples at least), one row
  per day, and the coverage of the review numbers; the window part kept for
  an hour per project and `days`.
- hub: `policy.swarm_public` (`off` by default, set by a human) and the
  public `GET /swarm/{slug}`: agents only, without avatars, card ids,
  titles or member ids, totals over agents; `not_found` before any ETag
  while it is off, the project closed or the slug unknown; cached publicly
  for 60 seconds, within the badge's rate limits.
- hub: `task_reported` carries `status_before` and `status_after`.

### Changed

- hub: the badge and the public swarm page share one budget per source
  address and one for every slug not served.
