### Added

- hub: the project policy fields for an outsider's claim, as docs/api.md §6.1 contracts them: `looking_for_coders` (`per_card`, `all` or `off`, default `per_card`), `outside_claims` (`human`, `agent` or `direct`, default `human`; `agent` and `direct` set by an owner only, `human` back by any human with `project:admin`) and `outside_claims_max` (`null` or 1 to 2147483647, default `null`). Each change needs a `reason`, a preset change keeps all three, and a project that predates them reads the defaults (tsk-5q5emh2nm61k).
- hub: the card field `open_to_outsiders` (§6.4), `false` by default, set on `POST …/tasks` and `PATCH …/tasks/{id}` by whoever edits the card and recorded in its history; a caller with trust `outside` that names it is refused with `outside_trust`, whatever the value.
- hub: the card field `claim_requests` (§6.4), `[{id, member_id, instance, requested_at}]`, read by every reader through the API and not shown on the card's public page. Nothing files a claim request yet: it reads `[]` while an outsider's agent still claims no card itself (§6.5).
- hub: `GET …/contribution` answers `looking_for_coders` and `outside_claims` as the policy reads them (§6.1).

### Changed

- hub: upgrade note: the migration `20261126090000_outside_claims` adds three nullable project columns, `card.open_to_outsiders` (false on every existing card) and the empty table `claim_request`. A downgrade drops them all, with any value a project or a card set.
