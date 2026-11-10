# Organisations

## The fixture hub serves an organisation's page by its switch, which the hub does not yet

**Id:** efe947bc-444d-4b65-b694-610be9137806
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the delta review of #748 (the fixture's `/people` route), 2026-10-30; `hub/src/maity_hub/routes/people.py` (`page_served` read from the store)
**See:** https://github.com/oliver-zehentleitner/maity — 4423561d-6f8e-4ad5-8729-0b896fb37e3c — as of 2026-10-31
**Revisit when:** the hub renders an organisation's page kind

The fixture hub's `GET /people/{handle}` answers `page_served` for an
organisation from its `public_page` switch, and lists its projects with
a served page as `shared: false`. The real hub reads the store, where no
organisation page exists yet, so it answers `false` for every
organisation. The person view's **View public page** branch for an
organisation is drawn only in the fixture.

**Reason:** with the hub's answer the branch would never be drawn
in smoke, and would break unseen when the hub starts serving the page.

**Rejected alternative:** `page_served: false` for every organisation in
the fixture, as the hub answers today: it matches the hub, but leaves
those branches untested.

## Organisations live under the account: `/account/orgs`, not `/orgs`

**Id:** 73999dde-dbb6-4982-a448-e1441e7a5b6b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (one namespace `<owner>/<slug>`, the dashboard's route words reserved as handles) and §6.26; `DASHBOARD_WORDS` in hub/src/maity_hub/namespace.py; the coordinator's approval of the route on the organisations card, 2026-10-29
**Revisit when:** `orgs` is added to the hub's reserved dashboard words, or organisations get pages of their own beside the account (a public organisation page, §16.9)

The dashboard addresses a project as `/<owner>/<slug>`, and any first
word the dashboard does not use itself is read as an owner's handle.
The organisations view therefore sits under a word the dashboard
already owns: `/account/orgs` lists them, `/account/orgs/<handle>`
is one of them. It is reached from the profile menu.

**Reason:** `orgs` is not among the hub's reserved handles
(`DASHBOARD_WORDS`), so a human or an organisation may already be
called `orgs`; `/orgs/<x>` would then be that owner's project
`orgs/<x>` as much as an organisation page. Organisations are a
human's own business (§6.26, humans only, members only), which is what
the account holds.

**Rejected alternative:** `/orgs` and `/orgs/<handle>`: shorter,
but ambiguous with a project of an owner named `orgs` unless the hub
first reserves the word, a change to the hub and to handles that may
already exist. Putting organisations into the Settings menu: that menu
holds the hub's and the runners' settings, not the human's memberships.

## A suspended organisation's handle and public page are locked in the form, not only refused

**Id:** 156c278f-9df0-45c6-b53f-1cece42b2ed9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("Suspended": a rename and `public_page: on` are `forbidden`, `moderation_hold`) and §16.8; the review of the organisations page (#584), 2026-10-29
**Revisit when:** a suspension also locks other settings, or the hub sends the allowed changes with the view

While the organisation's view carries `moderation`, the settings form
disables the handle field and turning the public page on, and says why;
turning the page off stays possible. The refusal `moderation_hold` is
still said in words, for a suspension that comes between loading the
page and saving it.

**Reason:** the human should not type a change the hub will refuse;
the view already says the organisation is suspended.

**Rejected alternative:** leaving the fields open and showing the hub's
`forbidden` afterwards: the human types first and is turned away.

## The organisation's handle in the address is read as a typed one

**Id:** c3e2532b-f64a-4ade-b834-853ad4b1160f
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** docs/api.md §6.24 (handles are lowercase; `{org}` resolves a handle or an alias); the review of the organisations page (#584), 2026-10-29
**Revisit when:** the dashboard moves to real paths (the routing card after #601), where the route parser may normalise once for every handle

`M.orgs.handleOf` decodes the handle from `/account/orgs/<handle>`,
trims it, drops a leading `@` and writes it in lowercase, for the call
and for the page title, so `/account/orgs/%40OZ-Team` opens @oz-team.

**Reason:** a link copied with an `@` or typed with capitals names the
same organisation for a human.

**Rejected alternative:** handing the route as it is to
`GET /orgs/{org}`: an `@` or a capital letter would answer
`not_found` for an organisation the human is in.

## The fixture hub's reserved handles are a copy of the hub's list

**Id:** 6dccb66c-0cd3-4cbb-8b65-59e8e5b814e0
**Type:** workaround
**Status:** active
**Evidence:** inferred
**Source:** `ORG_RESERVED` in web/js/api.js; `DASHBOARD_WORDS` in hub/src/maity_hub/namespace.py (docs/api.md §6.25, "Dashboard routes and handles"; §16.11 with #601); the review of the organisations page (#584), 2026-10-29
**Revisit when:** the hub publishes its reserved words (in its machine form or a route), or #601 changes the list

The fixture hub refuses an organisation handle that is a word of the
dashboard's addresses from its own copy of the hub's list. It is a copy,
not a read: when the hub changes its words, `web/js/api.js` has to
change with it. On a real hub the hub alone refuses.

## New project offers an organisation as owner only where the human may create in it

**Id:** e0cf14f3-56b8-40c4-9e6e-4c5fb739b037
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("The organisation's projects", "Suspended"); web/js/new-project.js; the review of #609, 2026-10-29
**Revisit when:** the hub's form names the owners a human may choose, or organisations get a page of their own for new projects

The **Owner** field (until 2026-10-30 only where the hub's machine form
named `owner` on `POST /projects`, e1699490) offers the human and the organisations
in which they may create a project: as owner or admin, or as a member
while `members_create_projects` is on, and none that is suspended. When
`GET /orgs` fails, only the personal choice is left; the form still
works.

**Reason:** an organisation the human may not create in would only
lead to `org_role` or `moderation_hold`.

**Rejected alternative:** offering every organisation and saying the
hub's 403 afterwards: the rule moves into an error message.

## A transfer into an organisation moves at once only for its owner

**Id:** e47c8d0d-373f-4b2d-be05-15ad3d4306ef
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("Transfer into and out of an organisation"), §6.25; web/js/project-names.js; the review of #609, 2026-10-29
**Revisit when:** the transfer's answer says itself whether it moved or asked, or the project view carries the caller's role in its organisation

Project settings offer the transfer to the project's namespace owner,
and for an organisation's project to each of its owners. The
confirmation says before the call which case comes: into an
organisation the human owns, or to themselves out of an organisation,
the project moves in the call and the page follows its new name; into
one they administer, its owners are asked and the request can be
withdrawn. Whether the human is an owner of the project's organisation
comes from `org_owner` on their own member view (§6.2), since the
project view carries no organisation role. Suspended organisations are
not offered.

**Reason:** an owner of the receiving organisation speaks for it, an
admin only for themselves (§6.26); the page should say which before the
human confirms.

**Rejected alternative:** always saying the transfer waits for consent:
wrong for an owner, whose call moves the project at once.
