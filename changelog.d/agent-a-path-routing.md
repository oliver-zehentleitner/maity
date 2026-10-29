### Changed
- docs: the dashboard is addressed by paths instead of `#/` routes
  (§16.11): the hub serves the app shell (`no-cache`, `noindex`) for
  every `GET` that is not one of its own paths, its static files under
  `/assets/`; every URL the hub writes (invitations, the device code,
  `next`, the badge's link, notification and ticker URLs) is a path.
- docs: public pages are served at their canonical address,
  `/<owner>/<slug>` and `/<handle>`, to visitors without a session, the
  app shell otherwise (§16.9); `/p/…` and `/u/…` are gone, the robots
  file and the sitemap follow.
- docs: the landing page carries no script and `/app` is gone (§16.7);
  the public swarm page is `/<owner>/<slug>/swarm` (§6.22).
- docs: one list of reserved first segments for handles and of reserved
  second segments for slugs (§16.11, §6.24, §6.25).

### Removed
- docs: `legacy_slug`, the old badge, swarm and webhook addresses by
  slug, and the answers `client_outdated` and `project_path_outdated`
  for one-segment project routes (§6.25); an old address is
  `not_found`.
