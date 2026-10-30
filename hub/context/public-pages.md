# Public pages

How the hub stores and serves the pages a search engine can read (`docs/api.md` §16.9).

## A public page is a row of `public_page`, served by the app shell's route

**Id:** 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 and §16.11; the coordinator's answer of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5 (the stored page is a row in the database)
**Revisit when:** the pages grow so large or so many that a row per page is the wrong place, or a page has to be served from the join host

`public_page` holds one row per address: the HTML as it is served, its ETag, a digest of the inputs it
was made from and when they last changed. A page that stops being public is a deleted row
(`public_pages.remove`, `clear`), in the transaction that changed the input, so the next request already
gets the app shell. `ShellRoute` asks `public_pages.answer` before it serves the shell for a `GET` or a
`HEAD` that is no hub path: a stored page for a request without a live session or with `?as=public`,
else the shell. While `MAITY_PUBLIC_PAGES` is off, nothing is looked up. The page answers `Cache-Control:
public, max-age=60`, its ETag (`304` on a match), the CSP of the static pages and `Vary: Cookie`, never
a cookie; the shell of the same addresses carries `Vary: Cookie` too. The middleware lets a non-hub path
choose public caching while pages are on, and only the page's answer asks for it (the shell stays
`no-cache`). The page's rate limit is its own budget per source address, of the badge's size, taken
only when a page is served. The join host sends a page's address to the public root as every address
there that is not the join.

**Reason:** one row per page makes taking a page off one `DELETE` in the same transaction, and every
replica of the hub serves the same page; the route that already answers every other address is the one
place where "page or shell" can be decided without a second catch-all.

**Rejected alternatives:**
- Files on disk: deleting a file is not part of the database transaction that changed the input, so a
  page could outlive it, and replicas would need a shared volume.
- A router of its own with `/{path:path}`: registered before the `/assets` mount it would shadow the
  dashboard's files, and after the shell route it would never match.
- Rendering at request time: the contract stores the page and renders it again on change or on an
  interval, so the cost of a crawler stays one read.
- Sharing the badge's budget: the contract gives the pages the badge's size, and one visitor's pages
  and badges would then spend the same budget.

## A page is rendered again in the transaction that changed its input, by a registry of kinds

**Id:** b7a13a49-7c56-49d6-bc18-4622b21d0077
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("How the pages are made", "Removing something is never left to the interval"); the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** a page kind needs inputs no write path can name, or the renders of one transaction become too slow to run inside it

Each kind of page (a person, a project and its views, an agent, an organisation) registers how to render the
pages of one target and which targets exist (`public_pages.Kind`). The write paths that change an input call
`public_pages.touch(conn, kind, target_id)` in their own transaction. `touch` renders the target again at once
when the change takes anything off a page (`removal`, the default) under either mode, and under `on_change`
every change does; under `interval` a new entry or a count (`removal=False`) waits for the next run. A
render that finds the inputs' digest unchanged leaves the row alone, so the ETag and the sitemap's `lastmod`
move with the inputs and not with the safety net. A render that fails takes the target's pages off (in a
savepoint, so the writer's own transaction goes on) instead of leaving a stale page. At start the hub clears
every page and renders all again before it serves any; a worker repeats `render_all` every
`MAITY_PUBLIC_PAGES_INTERVAL_HOURS`. The settings `touch` reads are set once at startup
(`public_pages.configure`), because the write paths do not carry them. The sitemap lists the stored rows
with their `lastmod` and becomes an index with `/sitemap-<n>.xml` parts above 50,000 URLs or 50 MB;
`robots.txt` closes every reserved first segment of §16.11 (as `/word/` and `/word`, so that a handle
`word-x` stays open, the legal pages too) while pages are on, and names the sitemap only while it lists a URL;
the parts of a sitemap are cached like it and are not served on the join host.

**Reason:** the contract wants the removal in the transaction that changed the input, which only the writer
can give; a registry keeps each kind's rendering next to its inputs and gives the writers one call to make.

**Rejected alternatives:**
- Rendering only by the interval worker: a page that has to go would outlive its input for hours.
- Rendering on request and caching: the contract stores the page, and the first crawler after a change
  would pay for the render.
- Each write path rendering its own pages: the same decision about `on_change`, `interval` and failure in
  twenty places.
- Touching with the settings passed through every call: the writers (a profile, a card, a membership) have
  no reason to know the hub's settings.

## A person's page exists by their choice, and `touch` is called wherever that can change

**Id:** 833b0f1f-5dad-43c8-b7e6-a22cdaa26c9f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A person's page", "What is never served"); the review of the engine step (#723) on a process without the app
**Revisit when:** a person can be shown on the page of a project they are a member of (step 4), a second place sets `public_profile`, or a handle can be renamed (#523): the rename is one more path that must `touch` the person, or the page stays under the old handle

The kind `person` renders `/{handle}` for a human with `public_profile` on, an active account, no
suspension, not deleted and no hold of moderation on the profile (`public_people.served`); the page has the
display name, the handle and the bio as text, escaped. `PATCH /me` (a human only, an agent is `humans_only`) sets
`public_profile` and `public_bio` and touches the page in the same transaction; `public_bio` is plain text of
at most 280 characters without a C0 control character or a bidirectional override (`control_character`,
`too_long`), an empty text clears it. The account deletion also clears `public_profile` and `public_bio` (§2.9: the profile is deleted with the person), so no personal text stays in the tombstone and `targets` no longer lists the person. The paths that take a page away or bring one back call `touch` as well:
`moderation.apply` for the account it concerns (a hold, a suspension, a dismissal), `moderation.unsuspend`,
the approval of a registration, and the account deletion. A process without the app (`maity-hub account unsuspend`) calls `public_pages.configure` first, for the
reason in the entry below.

**Reason:** the page is the person's, so the one switch is theirs; every other way the page can become wrong
(an account that is suspended or gone) is a transition the hub itself makes, and each of them names the page in
its own transaction. The bio refuses control characters and bidirectional overrides and isolates because on a
public page they could reorder or hide text to make one person's words read as another's.

**Rejected alternatives:**
- Deriving `public_profile` from a project's page: a person who is in no public project would have no
  page, and the choice would not be theirs.
- Keeping the bio in the settings JSON of the account: the length and character rules are a column's job and
  the bio is read on every render.
- Rendering a person's page for any member of a public project: the contract shows members by their own
  choice only.

## A process without the app configures the public pages itself before it changes an input

**Id:** 1f71e412-807f-4f8a-ac2b-0da5cd71f8fb
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the review of the engine step (#723) of the card tsk-w89mspg3gwx1
**Revisit when:** `public_pages.touch` loads the settings itself, or a second command of `maity-hub` changes an input of a page

`public_pages.touch` reads the settings (`MAITY_PUBLIC_PAGES` and the render mode) that `public_pages.startup`
sets once when the app starts, because the write paths of the hub carry none. A process that changes an input
without the app, today `maity-hub account unsuspend`, would find no settings and `touch` would do nothing: a page
that has to go would stay until the next interval. So such a command calls `public_pages.configure(settings)`
before it changes the input.

**Reason:** the write paths (a profile, a card, a membership) have no reason to know the hub's settings, and
passing them through twenty calls was the alternative that cost more than one line in each command.

**Rejected alternatives:**
- `touch` loading the settings from the environment on its own: a second place that parses them, and a process
  with other settings than the app would disagree with it.
- A silent no-op without configuration, as before: a removal that does not happen is the one failure this
  engine must not have.

## A person's links are names the hub builds into links, and each reader gets only what the value admits

**Id:** 05d38e67-97ac-4fee-b0ac-e0f75c03862f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A person's links"), the maintainer's decision of 2026-10-30 (names, not URLs; five independent values); the card tsk-xr6fqx8e0vw5
**Revisit when:** follow exists (the value `friends` starts to mean something), or an eighth network is added

`human.website`, `human.social` (an object of names) and `human.links_visible` (`private` by default) are
set by `PATCH /me` for a human only; `person_links.checked` validates every field and answers `invalid` naming
each failure (`website`: `format` or `too_long`; `social.<network>`: `format` or `unknown`; `links_visible`:
`unknown`), all or nothing. `social` merges by network, `null` or an empty text clears one. The hub stores the
names (the host of a Mastodon name and a Bluesky handle lower-cased) and builds the link when a link is shown
(`person_links.address`); Discord has no public profile address and is shown as the name. A reader gets
`website` and `social` in the member views of a shared project only when the value admits them (`admitted`):
`everyone` all, the person themself always, `colleagues` and `friends_and_colleagues` a human who is an active
member of a project the person is an active member of (agents never), `friends` nobody until follow exists. The
member views take the reader as a parameter (`links`); no event does, because who may read them depends on the
reader, so a change is `member_updated` with `changed: ["links"]` and a reader reads the member again. The
person's page shows them, with `rel="me nofollow"`, only under `everyone`.

**Reason:** a link built from a name always goes where its label says, which a stored URL would not guarantee,
and the reader-dependent visibility cannot go into an event that goes to all.

**Rejected alternatives:**
- Free URLs for the networks: a "GitHub" label could point to any site.
- The links in `member_updated`: every project member would receive links their reader may not see.
- Cumulative levels (colleagues including friends): the maintainer chose independent values, `friends_and_colleagues`
  being its own.
