### Fixed

- docs: the README no longer says a new project is public on every hub: a
  project is public only once the operator switches `MAITY_PUBLIC_PAGES` on,
  which a self-hosted hub starts with off; on such a hub a new project in
  one's own namespace is public by default (tsk-n59j7q38rjpn).
- web: New project's slug hint no longer says the slug cannot be changed: an
  owner can rename it later, and the old name still leads to the project, in
  all ten languages (tsk-n59j7q38rjpn).
