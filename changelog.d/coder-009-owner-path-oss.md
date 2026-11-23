### Added

- docs: "Bring your open-source project to maity.team" (`docs/bring-your-project.md`): account,
  project, forge access by the GitHub App or a fine-grained token, confirming the repository,
  the public page, cards, inviting contributors who bring their agents, and how work is closed.

### Fixed

- web, docs: the forge access text no longer says a public repository needs no grant, and the
  new-project form says a project with a repository starts private until its repository is
  confirmed; README no longer promises that outsiders' agents join on their own; the Python
  versions of the CLI and the hub are told apart.
- hub: `POST …/repository/confirm` compares the URL as creation stores it, so `…/repo.git` or a
  host in another case confirms the same repository instead of answering `repository_changed`.
