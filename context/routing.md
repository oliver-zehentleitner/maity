# Routing

## The dashboard is addressed by paths, public pages sit at the same canonical address, and nothing old is kept

**Id:** e34ae588-4dbc-423c-8da8-29fc62436cb5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 in the team chat (paths like a forge, indexable public pages, alpha without legacy layers); the details are the contract owner's; contract `docs/api.md` §16.11, §16.7, §16.9, §6.25
**Revisit when:** Maity leaves alpha (from then on an address change needs the §1.6 rule of a stated period, not a removal); or the hub must render a dashboard page itself beyond the public pages; or a word the hub or the dashboard needs as a first segment is already held by a handle
**See:** projects.md#projects-live-in-their-owners-namespace-ownerslug-as-on-a-forge-old-names-stay-aliases-the-change-is-made-once-in-v1-before-the-launch — 281820c9-2286-45c4-9389-603b7e8a3923 — as of 2026-10-29
**See:** scope.md#public-pages-are-static-html-chosen-by-their-owner-and-the-instances-operator-must-allow-them — 2571d046-a270-4680-b50a-dc4e9ad60f19 — as of 2026-10-29

Every dashboard route is a path (`/<owner>/<slug>/board`, `/inbox`,
`/invite/<token>`, …) and the dashboard routes with the History API.
The hub serves the app shell for every `GET` that is not one of its own
paths (`/api/…`, `/assets/…`, `/mail/…`, `/badge/…`, the join, the
legal pages, the files for search engines), unknown paths included,
`no-cache` and `noindex`. A project's public page is served at
`/<owner>/<slug>`, a person's or an organisation's at `/<handle>`: to a
visitor without a session the static page where it is public, the app
shell otherwise, never a status that tells whether the name exists;
with a session always the dashboard, which links to the public page.
Handles can never be a first segment the hub or the dashboard uses,
slugs never a project view. Every URL the hub writes is a path. The
hash routes, `/app`, `/p/…`, `/u/…`, `/s/…`, the inline redirect script
of the landing page, `legacy_slug` with its frozen old badge, swarm and
webhook addresses, and the answers for one-segment project routes
(`client_outdated`, `project_path_outdated`) are removed; an old
address is simply `not_found` or the app shell. The CLI's one-time read
of `full_name` from `GET /me` for a state written before the namespace
stays, because it needs no hub route.

Aliases from a rename or a transfer (handles, §6.24; projects, §6.25)
are not part of what is removed: they are a feature, not a transition —
mentions, other people's links and bookmarks keep reaching the same
person or project, and nobody can take over a given-up name and pose as
its former holder.

Two consequences are left to the web owner's implementation: the public
swarm page now shares `/<owner>/<slug>/swarm` with the members' Swarm
tab (members get the tab, `?as=public` the public view), a known
conflict with the dashboard's decision d81c0a1a-0d4c-4176-9a85-a56ef9f5975e
in `web/context/views.md`, which that implementation supersedes; and the
dashboard's `file://` fixture mode, a development tool, has to find the
files under `/assets/` (a `<base>`, a development server), settled in
`web/`.

The reserved first segments live in one place, `docs/api.md` §16.11.
The hub's list (`namespace.DASHBOARD_WORDS`) and the dashboard's
(`ORG_RESERVED`) are to be derived from it, with a test that compares
both with §16.11, so they cannot drift apart; until the implementation
cards land, both are hand copies of the older list.

**Reason:** Maity is alpha and every caller is one of its own clients,
so the maintainer chose the best practice outright over carrying
compatibility layers. Paths give a public page and the dashboard one
address, the same one a forge would use, so a link shared by a member
is the page a search engine indexes; fragments are never sent to the
hub, so with hash routes the hub could not serve a public page at the
dashboard's address. Answering a non-public page with the app shell
instead of a status keeps the address from telling a stranger whether
a project or a person exists.

**Rejected alternatives:**
- Keeping hash routing and only adding server-rendered public pages
  under `/p/` and `/u/`: two addresses for one project, the shared
  dashboard link never the indexed one, and the `/app` move and the
  landing page's redirect script kept only because `/` could be the
  landing page.
- Keeping `#/` redirects for old links: a compatibility layer for links
  from an alpha, which the maintainer ruled out; the landing page would
  keep a script and a CSP hash for it.
- Removing rename aliases too, as legacy: they serve every rename from
  now on, not the one-time move into the namespace that `legacy_slug`
  served; without them mentions and links would break on each rename
  and a given-up name could be taken by someone posing as its former
  holder.
