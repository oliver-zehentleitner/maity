### Changed

- web: the dashboard routes on paths (docs/api.md §16.11) with the History API, in `js/route.js`
  alone: every link is a path (`/new`, `/<owner>/<slug>/board`), a click on one stays in the page,
  and going to the current address changes nothing. Fixture mode, opened from `file://`, carries the
  same path in the fragment. `make check` fails on a `#/`, `location.hash` or the History API
  outside `js/route.js`.
- web: a sign-in's `next` is a path of the dashboard: no `#`, no `//`, not a hub path.
- web: the device code is read from `/sign-in/code#c=…` and removed from the address once read.
- web: a pending account's page is `/account/pending`.
- web: a project's public swarm is `/<owner>/<slug>/swarm` for a visitor and anyone not a member, and
  `?as=public`; a member gets the Swarm tab, which links there.
- web: landing-page links and the button are paths (`/register`), as the contract writes them.
- web: the e2e prints the page's own errors when a step fails.

### Removed

- web: every `#/` route; the old `/p/<slug>` (by `legacy_slug`), `/s/<slug>` and
  `/<owner>/<slug>/agents` and `/join` addresses, without redirects; anchors and bare queries as
  links, which would lead into `/assets/` under the shell's base.
