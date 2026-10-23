### Added

- docs: a project's language in the API contract (`docs/api.md` §6.1):
  `settings.language` (`en` or `de`, default `en`), set by a human with
  `project:admin`, read by every member, in the resume packet as
  `project.language` (§5.2); a change emits `project_updated` like
  every settings change.
- docs: a human's `language` in the member view (§6.2) and in the resume
  packet's `peers` (§5.2), read live from the notification settings
  (§18.4), which stay the one place it is set; it now governs
  everything addressed to that human, not only mails.
- docs: the language rule for agents (`docs/agents.md`, rule 10;
  `docs/api.md` §8.4, §19.4): to one human in that human's language,
  everything shared and everything to another agent in the project's
  language, code and repository texts by the repository's convention;
  the hub neither translates nor checks. `maity resume` prints both
  (§13).
