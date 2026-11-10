### Added

- docs/api.md §11.4: `repository.owner_confirmed` on a project. `POST
  /projects/{owner}/{slug}/repository/confirm` `{url}` lets the namespace owner, a human, confirm
  the repository URL they saw. A URL the project no longer carries answers `409 conflict`
  (`details.reason: repository_changed`, `details.url`). Every change of the URL, by anyone, and
  every transfer set it back to `false`. A transfer's consent request names the repository URL.
  Migration 0071 adds the column; existing projects start unconfirmed.
