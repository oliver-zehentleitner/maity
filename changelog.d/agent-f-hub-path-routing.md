### Changed

- hub: the dashboard is served on paths (docs/api.md §16.11). Every path the hub does not
  answer itself is the app shell (`no-cache`, `noindex`); the dashboard's scripts, stylesheets
  and brand files are served under `/assets/` and nothing else of `web/` is a file. A path
  under a hub path that names nothing is `not_found`, never the shell.
- hub: every URL the hub writes is a path, not a `#/` route: invitations (`/invite/<token>`),
  the device code (`/sign-in/code#c=<code>`), the forge settings, the bell and mail items, the
  jour fixe item, the registration and deletion mails. A login's `next` is a dashboard path
  (no `#`, no `//`, first segment not a hub path).
- hub: the reserved first segments of §16.11 are one list in the code (`paths.RESERVED_FIRST`),
  compared with the contract by a test; `maity-hub migrate` stops and names a handle, slug or
  project alias that already holds a reserved word. A slug is never a project view of the
  dashboard.

### Removed

- hub: the paths from before the namespace and the hash routes: `/j/<token>`, the `426
  client_outdated` and `410 project_path_outdated` answers, the redirects of the old badge and
  public swarm addresses, the forge webhook's one-segment address, and `legacy_slug` (the field
  of the project view and, with migration 0086, the column). No redirect leads from an old link.
