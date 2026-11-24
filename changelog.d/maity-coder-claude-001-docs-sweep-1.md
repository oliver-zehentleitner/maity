### Fixed

- docs: the README no longer says a new project is public on every hub: a
  project is public only once the operator switches `MAITY_PUBLIC_PAGES` on,
  which a self-hosted hub starts with off; on such a hub a new project in
  one's own namespace is public by default (tsk-n59j7q38rjpn).
- web, docs: New project's slug hint, in all ten languages, and
  `docs/getting-started.md` no longer say the slug cannot be changed: an
  owner can rename it later, and the old name still leads to the project
  (tsk-n59j7q38rjpn).
- docs: `docs/getting-started.md` no longer says an agent reads its
  briefing first on every session: `maity resume` prints its memory,
  check-in, setup cards, Keep the Why and subagent text before it, so the
  agent reads the briefing at the start of every session with the rest of
  its packet (tsk-n59j7q38rjpn).
