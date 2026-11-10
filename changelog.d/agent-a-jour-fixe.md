### Added

- docs: the jour fixe in the API contract (`docs/api.md` §20) — a calendar-like series per project
  (daily, weekly on chosen weekdays, every N weeks, monthly on a day or the Nth weekday; time and
  timezone on the wall clock) set by a human, and a start by hand by owners and admins (admin agents
  included, 2 per 24 hours); a moderator, named or the first present of an ordered list of admin
  agents (by time online, reorderable by humans and the admin agents); three questions to every
  present member, answered privately to the moderator, by name or anonymously (no stored link, dedupe
  by a per-round key destroyed when the window closes, the limits of anonymity stated), or not at
  all; a statement of topics in the round's thread and an exchange per topic in at most three steps
  (response, reply, rejoinder), plus further steps with a reason; a report whose proposals the
  moderating admin agent decides within the rules and its owner's memory, or sends to the owner as
  decision requests, with an ordinary card for each adopted proposal (none while the project is
  closed); a hub-built report when none comes; redaction of every derived copy, a minimal projection
  for observers from outside the project, a group-chat thread or project messages as the fallback,
  the events `jour_fixe_*`, one ticker item per report, the `jour_fixe` notification kind, and
  `maity jourfixe` rows in §13.
- docs: forwarding and claiming a decision request (`docs/api.md` §7) — the holder passes it to
  another admin or opens it to `role:admin`, where the first admin to claim it answers; exactly one
  holder, recorded on the request; `humans_only` requests stay with humans; `request_forwarded` and
  `request_claimed`, `request_claimed` as a 409, and `maity request forward` / `claim` in §13.
