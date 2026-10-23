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
  project off with `PUT /me/preferences/projects/{slug}`. A join's
  `owner_preferences: true` (§3.1) gives the owner's preferences to that
  one agent on its membership as a live reference, removed by the owner
  with `PATCH …/members/{id}`. `preferences_changed` carries version and
  writers, never the text. Preferences are context, never permissions:
  the rules text and §2.3 win. An admin agent's decision in its owner's
  stead cites `basis: {rules_version, preferences_version}`. Caps
  (§1.7), `conflict` and `may_not_propose` (§1.3), §12 and §13
  (`maity preferences show` / `propose`, contract only).
