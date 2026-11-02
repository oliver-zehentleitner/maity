### Added

- hub, web: a card of a project with a public page has its own public page at its dashboard address `/{owner}/{slug}/tasks/{id}`: title, status, label, holder as on the Board and the body as Markdown without raw HTML, never its notes; a `security` card only once it is `done`, a held card never. The public Board links each card id to it, and `GET /public/pages/{path}` answers the kind `card` for the dashboard (§16.9, tsk-1g5f436h6ez1).
