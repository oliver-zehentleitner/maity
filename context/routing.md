# Routing

## The dashboard is addressed by paths, public pages sit at the same canonical address, and nothing old is kept

**Id:** e34ae588-4dbc-423c-8da8-29fc62436cb5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 in the team chat (paths like a forge, indexable public pages, alpha without legacy layers); the details are the contract owner's; contract `docs/api.md` §16.11, §16.7, §16.9, §6.25
**Revisit when:** Maity leaves alpha (from then on an address change needs the §1.6 rule of a stated period, not a removal); or the hub must render a dashboard page itself beyond the public pages; or a word the hub or the dashboard needs as a first segment is already held by a handle
**See:** projects.md#projects-live-in-their-owners-namespace-ownerslug-as-on-a-forge-old-names-stay-aliases-the-change-is-made-once-in-v1-before-the-launch — 281820c9-2286-45c4-9389-603b7e8a3923 — as of 2026-10-29
**See:** scope.md#public-pages-are-static-html-public-by-default-and-the-instances-operator-must-allow-them — 2571d046-a270-4680-b50a-dc4e9ad60f19 — as of 2026-10-29

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

Two consequences were left to the web owner's implementation: the public
swarm page shared `/<owner>/<slug>/swarm` with the members' Swarm tab — moot
since both are gone (projects.md bfe4c4a6, the swarm is a section of the
Overview); and the
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

## Agents and people get pages of their own; `/invite` gathers a human's person invitations without a route of its own

**Id:** f1b817b6-af4e-4b0a-966d-f18990782f0a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's reorganisation of 2026-10-31 (a "+" menu with Agent and User, the agents page with profiles and instances, a user page for invitations, "Invite user" and "Join agent" on Members); contract `docs/api.md` §16.11
**See:** routing.md#the-dashboard-is-addressed-by-paths-public-pages-sit-at-the-same-canonical-address-and-nothing-old-is-kept — e34ae588-4dbc-423c-8da8-29fc62436cb5 — as of 2026-10-31

The dashboard has two pages next to the projects: `/agents` for the
human's agent profiles, their instances and joining an agent, and
`/invite` for person invitations. `/invite` reads the per-project
invitation list (§3.4) in every project where the human holds
`members:admin` and creates an invitation for a project the human picks;
the hub gets no new route for it. A project's Members page links to both
instead of carrying its own invitation form.

**Reason:** the maintainer wants agents and people managed where they
are, not spread over each project's Members page. A human with a handful
of projects reads a handful of lists, so a cross-project endpoint would
only duplicate §3.4 and its rights; `invite` was already a reserved first
segment, so the path costs nothing.

**Alternatives:**
- A new `GET /me/invitations`: one more route with its own rights and
  paging for what a few per-project calls already give.
- Keeping the invitation form on each Members page: the maintainer asked
  for one place.

## "Where they run" is a project tab of its own at `placements`, the noun the contract uses, not the tab's words

**Id:** b32bb82c-acdb-4e91-aa2a-4c257a6cc6b3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer in chat (2026-11-11, card tsk-3s3eb6bsp15n: the section becomes a tab between Agents and Organisation); the coordinator's choice of the word the same day; contract `docs/api.md` §16.11, §15.6
**See:** routing.md#the-dashboard-is-addressed-by-paths-public-pages-sit-at-the-same-canonical-address-and-nothing-old-is-kept — e34ae588-4dbc-423c-8da8-29fc62436cb5 — as of 2026-11-11
**Revisit when:** the tab is renamed to something a path can say, a second view of placements needs the word, or the `/agents` tab is found slow for a human with many projects (then `GET /me/placements`, below)

"Where they run", the list of where the project's agents run (§15.5–§15.7:
the wanted and reported state, Stop, Restart, Logs, the start on a
runner), moves from the bottom of the Agents page to a project tab of
its own between Agents and Organisation, at `/<owner>/<slug>/placements`.
Every member who reads the project sees it, as they saw the section;
the actions on it stay as §15.6 grants them. `placements` joins the
project views of §16.11 (`PROJECT_VIEWS`); as an API route word it was
already no slug (§6.25).
The global agents page `/agents` gets the same treatment (the maintainer,
2026-11-11): "Where they run" at `/agents/placements` and "Maintenance
notices", which was at its bottom, at `/agents/maintenance`, each a tab
beside the list. §16.11 states that the hub never issues either word as
an id, since ids are otherwise opaque; neither is a first segment, so no
reserved word changes. The `/agents` "Where they run" tab reads
`GET …/placements` (§15.6) in each project the human reads where one of
their agents is a member, grouped by project, only when the tab is opened.

**Reason:** the Team view moved to `team` so that the path says what
the tab says (§16.11, 2026-11-10). "Where they run" is no path word, so
that rule cannot be met word for word here. `placements` is the noun the
contract (§15.6, `/projects/{owner}/{slug}/placements`), the CLI
(`maity placement …`) and the code (`js/placements.js`, the `placement_*`
events) already use for this list, so an address read from the API, a
log or the CLI names the same thing.

**Rejected alternatives:**
- `running`, closer to the tab's words: too close to the project view
  `runners` (the machines), easy to confuse in a link or a log.
- Keeping the section on the Agents page: the maintainer asked for a tab.
- `GET /me/placements` for the `/agents` tab, one call across projects:
  a new route with its own rights and paging, where one read per project,
  made only when the tab opens, gives the same list for the projects the
  human reads (the coordinator's choice, 2026-11-11). Revisited if a human
  with many projects finds it slow.
