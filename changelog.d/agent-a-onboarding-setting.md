### Added

- docs: a project's onboarding in the API contract (`docs/api.md` §6.1):
  `settings.onboarding` with a default `briefing` and `check_in_with`
  (a member, `role:<role>` or `coordinator`, resolved on every resume).
  A membership without a briefing of its own gets the project's in its
  resume packet with `briefing_source: "project"`, never copied onto the
  membership; until it has posted a message or held a claim, its packet
  carries an `onboarding` hint naming whom to check in with. Set by a
  human with `project:admin` or by an admin agent (the one exception to
  §2.3 ʰ); a change emits `project_updated` without the text; removing
  the named member resets it to `coordinator`; `maity resume` prints a
  `Check in` block (§13).
