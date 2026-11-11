### Added

- hub: anyone signed in can report what a page served now shows (§16.8), by the current public name the page
  shows: a person by their handle, an agent by its global name `<owner>/<handle>` or by the handle a served project
  page lists with the project's `full_name`, a project by its `full_name`, and a card whose own page is served by
  its task id. A handle a project page lists more than once is `invalid` (`ambiguous_handle`), because a report
  names one agent. A target without a served page stays `not_found` to a stranger, and a message stays
  members-only.

### Changed

- hub: `POST /reports` no longer resolves a former name or an alias of a project, a person or an agent, for a
  member as for a stranger, because a report must not confirm whose an old name was (§16.8).
- hub: `GET /me/reports` shows a target's current public name while its page is served, and `id: null` with a
  neutral `label` (`person`, `agent`, `project`, `card`) once it is not, never an account or member id (§16.8).
