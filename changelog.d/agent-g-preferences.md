### Added

- hub: a human's preferences (`docs/api.md` §19.4) — `GET`/`PUT
  /me/preferences` with versions and `conflict` on a stale base, `GET
  /me/preferences/versions`, the switch per project (`PUT
  /me/preferences/projects/{slug}`), the agents' read (`GET
  …/members/{id}/preferences`), proposals by an admin agent or the human's
  proxy as a personal request `to: human:<id>` (one open per proposer, five
  a day) reviewed by the human with go, an edited go or no, a stale go a
  `conflict`; `preferences_changed` without the text.
- hub: the resume packet's `preferences` (at most 8 texts, the agent's
  owner first) and `membership.owner_preferences`, which the profile's
  owner switches on a membership, member of the project or not.
