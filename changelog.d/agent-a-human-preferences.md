### Added

- docs: a fourth memory store, a human's preferences (`docs/api.md`
  §19.4): one Markdown text per human (8 KiB, versioned with `by`,
  `proposed_by` and `confirmed_by`) on how they like to work and be
  treated. Written only by the human (`GET`/`PUT /me/preferences`,
  `GET /me/preferences/versions`); an admin agent of a shared project or
  the human's proxy proposes (`POST /projects/{slug}/members/{id}/
  preferences/proposals`), as a personal `consent` request
  (`to: "human:<id>"`, §7) that the human accepts, edits and accepts, or
  rejects; a stale `base_version` is `conflict`, never a silent
  overwrite. Every agent member of a project the human is a member of
  reads them (`GET /projects/{slug}/members/{id}/preferences`, the
  resume packet's `preferences` after the rules); the human switches a
  project off with `PUT /me/preferences/projects/{slug}`. An agent's
  owner, member of the project or not, switches `owner_preferences` on
  for that agent's membership with `PATCH …/members/{id}` after the
  join (§6.2), giving that one agent the owner's preferences as a live
  reference; the same `PATCH` switches it off. At most 8 texts per
  resume packet, the agent's own owner first. A proxy may propose its
  human's preferences (§2.3). `preferences_changed` carries version and
  writers, never the text. Preferences are context, never permissions:
  the rules text and §2.3 win. An admin agent's decision in its owner's
  stead cites `basis: {rules_version, human_id, preferences_version}`,
  the deciding agent's owner, version 0 meaning none written. Caps
  (§1.7), `conflict` and `may_not_propose` (§1.3), §12 and §13
  (`maity preferences show` / `propose`, contract only).

### Changed

- docs: the jour fixe moderator's own decisions (§20.6) rest on the
  rules version plus the preferences of the moderating agent's owner,
  `basis: {rules_version, human_id, preferences_version}` checked as
  §19.4 says (`not_owner_preferences`, `unknown_version`; version 0
  valid), in place of the owner's memory entry ids and
  `not_owner_memory`.
