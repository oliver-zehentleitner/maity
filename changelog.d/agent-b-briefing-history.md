### Added

- hub: a briefing's versions (`docs/api.md` §6.2) — the join is version 1 and every change
  a new one, with who wrote it (a human or an admin agent) and when; the member view (for
  the member itself and `members:admin`) and the resume packet carry `briefing_by` and
  `briefing_version`, the member view also `briefing_updated_at`; `member_updated` says
  `changed: ["briefing"]` with the new `briefing_version`, never the text;
  `GET …/members/{id}/briefings` lists the versions newest first for the agent's owner,
  a member of the project or not, and for humans with `members:admin` (migration
  `0019_briefing_history`)
