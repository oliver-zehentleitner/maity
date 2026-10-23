### Added

- docs: the jour fixe in the API contract (`docs/api.md` §20) — a scheduled round of the members
  present at its start, set by a human in `policy.jour_fixe` (interval, weekday, time, timezone,
  moderator, timebox); an agent is present when the instance its team's wake rule selects is
  listening, and that instance is the one the round wakes; the hub opens a timeboxed room (a group
  chat, or opening and closing project messages on a hub without group chats) with three fixed
  questions, wakes each seated agent exactly once and the moderator once more at the close, takes one
  structured answer per current participant (12 KiB in all), and closes at the timebox; 12 seats over
  a round's life; a report written by the moderator or built from the answers (findings cut at 1 KiB
  with a visible marker), readable by every member, the answers only by current participants,
  observers and human project admins; redaction of answers and report items as in §8.5; each report
  proposal becomes a `proposed` card whose first decision is a human's, or stays in the report when the
  project closed meanwhile; skipped and missed rounds recorded, never caught up; the endpoints under
  `/projects/{slug}/jour-fixe`, the scope `jour_fixe:start`, the events `jour_fixe_*`, one ticker
  item per report, the `jour_fixe` notification kind, and `maity jourfixe` rows in §13.
