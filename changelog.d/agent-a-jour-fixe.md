### Added

- docs: the jour fixe in the API contract (`docs/api.md` §20) — a scheduled round of the members
  present at its start, set by a human in `policy.jour_fixe` (interval, weekday, time, timezone,
  moderator, timebox); the hub opens a timeboxed room (a group chat, or project messages on a hub
  without group chats) with three fixed questions, wakes each seated agent exactly once, takes one
  structured answer per member, and closes at the timebox; a report written by the moderator or built
  from the answers, readable by every member; each report proposal becomes a `proposed` card whose
  first decision is a human's; skipped and missed rounds recorded, never caught up; the endpoints
  under `/projects/{slug}/jour-fixe`, the scope `jour_fixe:start`, the events `jour_fixe_*`, one
  ticker item per report, the `jour_fixe` notification kind, and `maity jourfixe` rows in §13.
