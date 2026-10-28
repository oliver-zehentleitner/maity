### Changed

- Dashboard: projects are addressed by their full name, `<owner>/<slug>` (docs/api.md §6.25). Views live at `#/<owner>/<slug>/…`, and every call goes to `/projects/<owner>/<slug>/…`. The badge, the public swarm page (`#/s/<owner>/<slug>`), read-along (`#/observe/<owner>/<slug>`) and the global chat (`#/chats/<owner>/<slug>/<id>`) follow. A project is keyed by its full name everywhere: counts, inbox filter and grouping, the runners' configuration and pairing, and the preferences per project.
- Dashboard: an old address `#/p/<slug>/…` leads to the project of one's own whose `legacy_slug` it is. An alias of a project of one's own leads to its current full name.
- Fixture mode: the fixture hub serves `/projects/<owner>/<slug>/…` and refuses an old one-segment path with 410 `project_path_outdated`.
