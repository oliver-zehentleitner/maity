### Added

- docs: §2.3 the role `writer` (README, documentation, the website's words, release notes, announcements) and project roles: up to 12 per project via `GET, PUT /projects/{owner}/{slug}/roles`, each on a built-in base role whose scopes it grants exactly, with its own name, description and briefing text; `role_base` on the member view; a project role's text is carried with `guide_by` and printed quoted with its author; `role:<base>` includes the project roles on that base for wakes, the done authority and substitutes.
