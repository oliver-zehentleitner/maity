# Public pages

How the hub stores and serves the pages a search engine can read (`docs/api.md` §16.9).

## A public page is a row of `public_page`, served by the app shell's route

**Id:** 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b
**Type:** decision
**Status:** superseded
**Superseded by:** 70c80e4f-bf45-430d-beb2-7abbab2c8e4c
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
only when a page is served. The join host sends a page's address on to the same path on the public host.

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
**Status:** needs-review
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("How the pages are made", "Removing something is never left to the interval"); the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** a page kind needs inputs no write path can name, or the renders of one transaction become too slow to run inside it

Its Revisit-when condition fired (the renders became too slow to run inside the writer's transaction):
narrowed by deafb243-f385-4108-8de4-81fc8f9a7872, only the removal stays in the writer's transaction and the
render follows the commit.

Each kind of page (a person, a project and its views, an agent, an organisation) registers how to render the
pages of one target and which targets exist (`public_pages.Kind`). The write paths that change an input call
`public_pages.touch(conn, kind, target_id)` in their own transaction. `touch` renders the target again at once
when the change takes anything off a page (`removal`, the default) under either mode, and under `on_change`
every change does; under `interval` a new entry or a count (`removal=False`) waits for the next run. Where
and when that render runs, and the time limits on it, are entry deafb243 below. A
render that finds the inputs' digest unchanged leaves the row alone, so the ETag and the sitemap's `lastmod`
move with the inputs and not with the safety net. A render that fails takes the target's pages off (in a
savepoint, so the writer's own transaction goes on) instead of leaving a stale page. At start the hub renders
all again before it serves any (within a budget, deafb243); a worker repeats `render_all` every
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

## A touched page is taken off in the writer's transaction and rendered after its commit; one render and a start have time limits

**Id:** deafb243-f385-4108-8de4-81fc8f9a7872
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-qzvb0c0abm3a (hardening asked for by the maintainer, 2026-11-04; the maintainer's yes to rendering outside the write transaction and to "page off" at a start the same day); the lead's answers on the card's plan (2026-11-04: dependents off with the target, 30 s and 2 s as settings, the contract sentence in the same change); `docs/api.md` §16.9; `public_pages.touch`, `_render_after_commit`, `refresh`, `render_all`, `startup`, `Worker._run`, `_unrendered`; `events.scratch`, `events.on_commit`; the review of #1364 (several workers per pod, a removal racing a render on PostgreSQL)
**See:** public-pages.md#a-page-is-rendered-again-in-the-transaction-that-changed-its-input-by-a-registry-of-kinds — b7a13a49-7c56-49d6-bc18-4622b21d0077 — as of 2026-11-04
**See:** public-pages.md#a-card-event-renders-only-the-projects-own-page-and-only-when-it-may-take-a-ticker-item-off — 721bcdfa-9464-4b57-b885-a1455f5adbb8 — as of 2026-11-04
**Revisit when:** a writer needs its page rendered before its answer returns, a render needs the writer's uncommitted state, or one target's render legitimately takes longer than `MAITY_PUBLIC_PAGES_RENDER_SECONDS`

Inside an `events.transaction`, `touch` no longer renders. A change that takes anything off a page deletes the
pages of the target and of its dependents in the writer's transaction, so nothing removed is served for a
moment, and every touched target is queued in the transaction's `events.scratch`, each once. After the commit,
`events.on_commit` renders each in a transaction of its own, in the same request, so the page is back when the
answer arrives. A write that rolls back renders nothing, and its deletions roll back with it. A `touch` from a
plain `engine.begin()` (no `on_commit` there) renders in that transaction as before. `refresh` treats a render of
one target that takes longer than `MAITY_PUBLIC_PAGES_RENDER_SECONDS` (default 2) as a failed one: logged, the
pages deleted. A starting process renders for at most `MAITY_PUBLIC_PAGES_STARTUP_SECONDS` (default 30); the
pages of the targets not reached by then are deleted. Each worker's first pass renders every target that has
no stored page, before its prepared kinds, whichever process did the start: with `MAITY_WORKERS` above 1 the
start runs in the supervisor's parent, which runs no worker and hands nothing to the spawned workers. A
removal takes the per-target lock that `refresh` takes before it deletes, the targets in one order, so a render
of the same target that is still running writes its page before the delete and not after it. On PostgreSQL the
writer waits for the renders and removals of its targets that hold or wait for that lock before it: a render as
long as it runs, a removal until its writer's transaction ends (SQLite writes one transaction at a time anyway).

**Reason:** CPython holds the interpreter lock while a render runs, and a render inside the writer's transaction
also held what that transaction holds: the project row, and on SQLite the database's one write lock, so every
other write waited for it. A start that renders every page before it serves can outlast its startup probe, and
a process killed there starts again in the same state. Deleting in the transaction keeps what §16.9 asks of a
removal; only the render, which shows the state after the change, moves after the commit.

**Rejected alternatives:**
- A queue rendered by the worker thread: the answer would come before the page, and every test and client that
  reads the page after a write would have to wait for it.
- Rendering after the commit without deleting first (721bcdfa's rejected form): a removal would stay on the
  page until the render, and a failed render would leave it there.
- Deleting only the target's own pages on a removal, not its dependents: a removed name would stay on a card
  page until that page is rendered again.
- Stopping a render that runs too long: a running render cannot be interrupted from another thread; the limit
  can only judge it once it ends.
- Keeping the targets the start skipped in the starting process's memory for its worker: with several workers
  per pod the start runs in the parent, and module state does not survive a spawn, so those pages stayed off
  until the first interval pass. Handing the list on through the environment or a file was rejected too (a
  worker the supervisor starts again would read a stale list), and so was a table (a second record of what
  the missing rows already say).
- Deleting without the per-target lock and accepting the window: on PostgreSQL a render already running when
  a removal commits wrote the removed content back until the removal's own render ended.

## A person's page exists by their choice, and `touch` is called wherever that can change

**Id:** 833b0f1f-5dad-43c8-b7e6-a22cdaa26c9f
**Type:** decision
**Status:** superseded
**Superseded by:** 3da2d551-c8a5-420d-b777-b3be88121199
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

## Every active account has a page and an open project names its members; `public_profile` decides how much the page shows

**Id:** 3da2d551-c8a5-420d-b777-b3be88121199
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-02, relayed by the lead on card tsk-my5gvj4warte (the card's body and the lead's answers on it); for who is online, the maintainer's answer the same day (request req-jkqzzy638k10): yes in principle, but a person must be able to turn their online status off in the settings; contract `docs/api.md` §2.7.1, §6.22, §6.27, §16.9
**Revisit when:** a person needs to work in an open project without being named there, or a profile that is off should keep a visitor from its page altogether
**See:** https://github.com/oliver-zehentleitner/maity — 038e685e-62bb-4f21-be5d-ab4a58b9c444 — as of 2026-11-02

It supersedes 833b0f1f, whose `touch` paths stay as written there. `public_profile` defaults to on, and the migration `20261102110000_profiles_public` switched every
existing account on; an instance that upgrades later has its accounts of that moment switched the same
way, so its operator tells their users first (the changelog says so). `public_people.served` no longer reads it: every active account that is not suspended
or deleted and whose profile is under no hold of moderation has its page at `/{handle}` and is named on the
pages of its open projects, by handle, on the Overview, Board, Members, Organisation, a card's page and the
snapshot alike, who is online included (on `main` before, an online member with the profile off was only
counted); the setting to keep one's online status off the public pages came on its own card (54823a3a), and
this change goes to production only together with it; `public_projects.team` counts nobody it does not name, so "and N more agents" is gone. The
switch decides what the page shows: on, the bio, the links under `everyone` and the public projects; off,
only the name, the handle and the agents, with `noindex` in the page and its headers (`public_page.indexed`,
which the sitemap also skips). With the profile off, the bio, the links and the list of projects are for the
members of a shared project, in the dashboard (`GET /people/{handle}`). The registration's link page says
that the name and the handle are public, that the name need not be the real one, and that the profile is
public by default (the public projects, the text and links one chooses to show) and can be turned off in the
account. An agent's page links
its owner's page, which now always exists while the owner has an account in good standing.

**Reason:** an open project follows the forge model the maintainer chose for projects and profiles
(038e685e): on a forge every contributor is named by handle on the work and has a profile page. Who acts in
a project that is open by choice is part of what it shows; what stays a person's choice is what is personal
(bio, links, the list of projects), and a name that need not be the real one keeps a person's identity theirs.

**Rejected alternatives:**
- A profile that is off is only counted, never named (the rule until then): the Board and the card pages
  would show holders and note authors as "a member", and an agent's page could not name whose agent it is
  without publishing what its owner withheld.
- No page at all with the profile off: a name on a project's page would lead nowhere, and an agent's page
  could not link its owner.
- Switching existing accounts only after a notice and a waiting period: the mechanism was struck from the
  contract with #1176; the instance's existing users are told before the deploy instead.

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

## A project's page is the namespace owner's, and a transfer turns it off

**Id:** 4e888b31-6cfd-4bde-b3dc-dd78f210a556
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A project's page"), §6.25, §16.8; the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** step 4c shows members and agents on the page, or the page's text may be written by someone other than the namespace owner

`project.public_page` (`off`/`on`) and `public_about` (Markdown, at most 4 KiB as bytes, under the landing page's
rules) are columns of the project, not of its policy, and `PATCH /projects/{owner}/{slug}` sets them only
for the namespace owner, a human; for a project of an organisation any owner of it (`_namespace_owner_only`,
the rule of the repository confirmation). Another admin of the project has `project:admin` for everything
else and is `forbidden` here. The event `project_updated` names `public_page` with its value and
`public_about` as `true`/`false`, never the text. The kind `project` renders `GET /{owner}/{slug}` (name,
full name, state, the text with `rel="nofollow ugc"` links) while the page is on, the project is not
archived, no hold of moderation stands on it, and its namespace owner is served: an active, not suspended,
not deleted human, or an organisation that is not deleted and carries no hold. Turning the page on is
refused with `moderation_hold` while a hold stands (§16.8). A rename, a state change, the owner's account
being suspended or lifted, an organisation's suspension or deletion and a moderation hold or its lifting
call `touch` in their own transactions. A transfer sets `public_page` to `off` and its consent request says
so: the receiver decides whether the project is public under their name.

**Reason:** a public page speaks under the namespace owner's name, so its existence and its words are
theirs, and what moves with a transfer must not publish under a name the sender never chose.

**Rejected alternatives:**
- Letting every `project:admin` set it: a co-admin could publish text under the owner's name.
- Putting the choice in `policy`: policy is for what the team agrees; the contract keeps the page out of it
  so that a preset change never publishes a project.
- Keeping the page on after a transfer: the receiver would be public without having said so.

## A person's links are names the hub builds into links, and each reader gets only what the value admits

**Id:** 05d38e67-97ac-4fee-b0ac-e0f75c03862f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A person's links"), the maintainer's decision of 2026-10-30 (names, not URLs; five independent values); the card tsk-xr6fqx8e0vw5
**Revisit when:** follow exists (the value `friends` starts to mean something), or an eighth network is added

`human.website`, `human.social` (an object of names) and `human.links_visible` (`private` by default) are
set by `PATCH /me` for a human only; `person_links.checked` validates every field and answers `invalid` naming
each failure (`website`: `format` or `too_long`, a host that is a DNS name without port, user part or IP literal;
`social`: `format` when it is no object; `social.<network>`: `format` or `unknown`; `links_visible`: `unknown`,
`null` included), all or nothing. `social` merges by network, `null` or an empty text clears one, and
`social: null` clears every network. The hub stores the
names (the host of a Mastodon name and a Bluesky handle lower-cased) and builds the link when a link is shown
(`person_links.address`); Discord has no public profile address and is shown as the name. A reader gets
`website` and `social` in the member views of a shared project only when the value admits them (`admitted`):
`everyone` all, the person themself always, `colleagues` and `friends_and_colleagues` a human who is an active
member of a project the person is an active member of (agents never), `friends` nobody until follow exists; under a hold on the profile (§16.8) `everyone` acts as `colleagues`
(`admitted(held=…)`). The member views take the reader as a parameter (`links`); no event does, because who may read them depends on the
reader, so a change is `member_updated` with `changed: ["links"]`, sent only when a stored value changed, and a reader
reads the member again. The
person's page shows them, with `rel="me nofollow"`, only under `everyone`.

**Reason:** a link built from a name always goes where its label says, which a stored URL would not guarantee,
and the reader-dependent visibility cannot go into an event that goes to all.

**Rejected alternatives:**
- Free URLs for the networks: a "GitHub" label could point to any site.
- The links in `member_updated`: every project member would receive links their reader may not see.
- Cumulative levels (colleagues including friends): the maintainer chose independent values, `friends_and_colleagues`
  being its own.

## The dashboard's view of a person reads `page_served` from the store, and hides every unseen case behind one `not_found`

**Id:** 4423561d-6f8e-4ad5-8729-0b896fb37e3c
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** `docs/api.md` §6.27 (contract #738), §6.10 ("Who may read an image"), §6.26; implementation of `GET /people/{handle}` (tsk-4ar8vw61fvj0), 2026-10-30
**See:** public-pages.md — 833b0f1f-5dad-43c8-b7e6-a22cdaa26c9f — as of 2026-10-30
**See:** public-pages.md — 05d38e67-97ac-4fee-b0ac-e0f75c03862f — as of 2026-10-30
**Revisit when:** the organisation's page kind is rendered, or handle aliases resolve (§6.24)

`routes/people.py` answers `GET /people/{handle}` for a signed-in human. `page_served` is `true`
when public pages are on and the store holds the page (a `public_page` row of the kind and target);
for a person `public_people.served` must hold as well, so a hold or a suspension counts at once. A
project with a served page is one with a `project` row in the store. Reading the store, not the
switches, is what "the hub serves the page now" means: a project's page kind is rendered since
step 4a (§16.9) and an organisation's is not yet, so an organisation is not served whatever its switch
says, and the answer never offers a page the visitor would not get. An unknown name, an agent's handle (they never resolve as an owner), a
deleted, suspended or pending account, a deleted organisation, and a person or an organisation
that shows the caller nothing are the same `not_found`. `avatar_url` comes only where
`avatars.may_read` lets the caller read the image; the organisation's picture got its rule there
(its members and the members of its projects, §6.10), which the image route had lacked. The answer
is `private, no-store`, a value `middleware.ROUTE_CACHE` now admits. `website` and `social` come
from `person_links.admitted` and `person_links.shown`, the member views' rule, the hold rule
included (under a hold on the profile `links_visible: everyone` counts as `colleagues`). A link
the caller is admitted to is enough for the person to be found; a person with no link has none
to admit.

**Reason:** the store is the one place that knows what a visitor gets; the switches say what
someone chose, not what is rendered. One `not_found` keeps the endpoint from telling which
accounts and organisations exist (§6.26).

**Rejected alternatives:**
- `page_served` from the switches (`public_profile`, the organisation's `public_page`): right only
  once every kind renders, and it would offer "View public page" for an organisation the hub does
  not serve yet.
- Answering a hidden account with its own error (`suspended`, `pending`): tells a stranger the
  account exists.

## The repository is on a public page only while the forge's last answer said it is public

**Id:** 915033f2-a416-41e1-b75a-2eb6dec9d9ca
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("Repository visibility"), §11.4; the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** the forge reports visibility on an event the hub already receives (a webhook), or another forge than GitHub is read

`project.repository_public` is null until the hub looked, true when the forge's last answer said
`private: false`, false for anything else. The probe's sweep asks first, before every other read and for
every project that has a public page and a GitHub repository, also one the hub can no longer read
(`probe.observe_visibility`, `Forge.repository_public`), through whatever grant reads the project (the
instance's token, an installation or the owner's token), and a read the forge does not answer never ends the
round. The hub's own token asks the forge itself, not the ten-minute cache of the visibility check that guards
its other reads, and an answer that is not public drops that cache entry. The answer is stored under the
project's lock and only while the page is on and the repository is the one that was asked: a `PATCH` of the
repository while the forge answered clears the value and is not overwritten. A change calls `touch`, at
once when the repository turned private. An answer the forge does not give (a 404, no `private` field, a
refusal, a spent budget) is stored as private: the contract says a repository the hub could not read counts as
private, so a short outage takes the URL off the page until the next round. A new repository URL clears the
value, and so do the page going on or off and a transfer: an old `true` rendered when the page comes back
would show a URL that turned private meanwhile until the next round, and after a transfer one the old owner's
look found. The page prints the URL as a `nofollow ugc` link only while the value is true.

**Reason:** the page is public, the repository may be private, and only the forge knows; showing a private
repository's URL is a leak that cannot be taken back from a crawler.

**Rejected alternatives:**
- Deriving it from the grant that reads the repository: a private repository read through an owner's grant would
  look public to the page.
- Asking the forge on every render: the renders run in the writers' transactions, which hold no connection to
  the forge (§11.4).
- Keeping the last known answer through an outage: the contract names the unreadable case private, and an
  outage on the instance's side would otherwise leave a URL on the page that turned private meanwhile.
- The visibility read last in the sweep, like the other reads: the sweep ends at the first read the forge does
  not answer, so a repository that turned private could stay on the page for as long as any other read failed.

## A page that shows people is rendered again with them, through dependents and the member events

**Id:** dd4a04fc-9382-4966-b77e-0d9aba7c9fcb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A project's page", "How the pages are made"); the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** a page shows a fact of a person that no event of a membership or of the person's page announces

A project's page lists every human member (a link to their page) and every agent (`public_projects.team`);
since 2026-11-02 whatever their profile says, and a person or agent under a hold is left out, not counted
(entry 3da2d551). Two things keep that true. A person's
page and the project pages that show them change together: a kind may name its `dependents`, and `touch` of a
person renders those project pages with the person (a name, a hold, a suspension, a deletion). And a membership changes through events: `events.emit` calls `touch` for the project of a
`member_joined` (an addition: it waits for the run under `interval`) or a `member_updated` (a removal, an
agent profile deleted among them) when the project's page is on, so the many places that add or remove a
member need no call of their own. Every `member_updated` counts as a possible removal and renders at once
(a trust or role change included): telling apart what changed would be a second place that must know every
field the page shows, and the render is cheap next to that. An isolated agent (`isolated_since`) is neither
named nor counted. Two inputs are not a membership event: an agent's `display_name`
(`PATCH /agents/{id}` calls `public_projects.touch_of_agent`) and a hold of moderation on the agent's own
profile, which takes the agent off the page like the hold on a person; the hold's resolution reaches the page
through the owner's profile, whose dependents are the projects of their agents.

**Reason:** the places that change a membership are a dozen, the events they all write are the one thing they
share; and a person's profile is shown on pages they have no event on.

**Rejected alternatives:**
- A call in each place that adds or removes a member: a dozen places, and the next one forgets.
- Reading the people when the page is served: the contract stores the page and takes a person off in the
  transaction that changed it, not on the next request.
- Re-rendering every public project when any profile changes: a profile touches the pages of the projects its
  person (or their agents) belongs to, and only those.

## The statistics on a project's page are the agents' of the last 30 days, and the counts wait for the run

**Id:** de730cff-6c6d-45ce-953a-75a3a2b58067
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("A project's page"), §6.22 ("reduced"); the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** a count must follow a card at once, or §6.22 changes what a public page carries of the agents

`public_projects.agent_statistics` folds the swarm window (`swarm.CACHE`, the one the members' Overview
reads, kept for an hour) over the last 30 days with `include` admitting only the memberships of agents, so a
human's cards, reviews and merges, and a contribution without a member, appear nowhere on the page; an
isolated agent's work is left out like the agent itself (the team list does not name or count it). The page
shows what §6.22 ("On a public page") lists: the totals (cards done, reviews given, pull requests merged,
handovers, the two medians), `cards_done_per_day` over the agents, and a row with the same counters for each
agent the page names (a public owner profile, no hold, not isolated: `members` of the fold, with `handle` and
`display_name`); never who is online, no card and no human. The totals count every agent that is not
isolated, also one the page does not name. These counts change with every card, and no write path of a card calls
`touch`: they arrive with the next render of the page (any change to what the page shows, and the worker's run
every `MAITY_PUBLIC_PAGES_INTERVAL_HOURS`), and the window itself may be an hour old. §16.9 holds counts
back under `interval` and the safety net under `on_change` is for exactly this. `swarm.CACHE.get` runs in the
transaction that renders and keeps the window for an hour: with a cold cache it is built from that
transaction's uncommitted state and stays if the transaction rolls back; only counts are affected, and the
members' Overview reads the same cache.

**Reason:** the contract reduces the statistics to the agents so that publishing a project does not publish its
people's work; and a render on every card would make the card's transaction pay for a page nobody reads at that
moment.

**Rejected alternatives:**
- A `touch` in every card write: the cards are the hub's busiest writes, and a count is not something that
  has to go.
- Totals only, the rows per agent left to the agent's page: this was the first reading, and §6.22 says
  otherwise for the agents the page names; the contract won (review of #806).
- Folding over everyone and hiding the humans' rows: the totals would still carry the humans' work.

## The Board, Members and Organisation are a second kind of page that follows the cards at once

**Id:** 6b0e2f4a-7d51-4c38-9a6e-3f1c8d5b2e97
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("The public views of a project"); the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** the Board's card events become a cost the busiest projects notice, or a view shows a count

`public_project_views` registers the kind `project_views`, one target per public project and three pages
(`/board`, `/members`, `/organisation`). The kind `project` lists it as a dependent, so everything that
renders a project page (a switch, a hold, an archive, a rename, an owner's suspension, a member change) renders
the views with it, and a person's page lists both kinds. The Board is the one part that follows the cards:
`events.emit` touches `project_views` alone for a card event (`task_created` as an addition, the others as
possible removals), so a title, a status, a label or a holder is on the page in the card's own transaction,
while the project page and its statistics are not rendered again. A card under a moderation hold is
filtered out of every column and the hold's resolution touches the views, so a card cancelled by `remove`
never shows its title. No migration: the views are rows of `public_page` like every other page.

**Reason:** the contract names a card's title, status, label and holder among the inputs that render at once,
and the Board is the only view they reach; a separate kind keeps a card event from paying for the statistics
and the people of the overview.

**Rejected alternatives:**
- The views as three more pages of the kind `project`: every card event would render the statistics fold
  and the team again, and the entry on the statistics' wait for the run would no longer hold.
- No card hook, the views only on the worker's run: §16.9 renders edits of a shown text at once, and a
  hidden card would stay on the Board until the next run.
- Three kinds, one per view: the three share one query for the people and one rule for who is named, and a
  member change touches all of them.

## An agent's page follows its public projects and its owner, and a median is pooled, not averaged

**Id:** 6ac39513-fcf3-476d-9d49-e682cfc21626
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 ("An agent's page", "A person's page"), §6.22; the plan of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5
**Revisit when:** an organisation's page lists agents, or §6.22 counts a median over something the window does not keep

`public_agents` renders `/{owner}/agents/{handle}` while the owner has a page (since 2026-11-02 every active account without a hold, whatever its `public_profile`, entry 3da2d551), no hold of moderation stands on the agent's profile and the agent is an active, not isolated member of at least one project whose page is served. Two things keep the page true. The kind `project` names the agent pages of its agents and the person pages that list it or them (its human members' and the owners' of its agent members, who need not be members: `touch` goes one level deep) as dependents, so a project's page going on or off, its name, a member joining, leaving or being isolated renders them at once, and the last public project going takes the agent's page with it. The kind `person` names the agent pages of the person's agents: the page's address contains the owner's handle and its existence follows the owner's account and holds. The person's page lists the public projects they are a member of and their agents that have a page, from the same `served` rules. The statistics are the agent's own counters summed over its public projects and its two medians over the pooled samples of all of them (`swarm` windows read per project), because a median of medians is no median; a project that is not public contributes nothing. The Members view of a project links a named agent to this page, since the agent is named exactly when the page exists.

Since #1176 and the profile change of tsk-my5gvj4warte (both 2026-11-02) the page no longer depends on its owner's `public_profile`: it names and links its owner, whose page exists with the profile off too, and Board and Members always name the agent (entry 3da2d551).

**Reason:** an agent belongs to several projects and the page speaks for all the public ones; a page that is stored and taken off in the changing transaction needs every input to name the pages that show it.

**Rejected alternatives:**
- Medians of the per-project medians: the figure would not be a median of anything, and a project with three samples would weigh as much as one with three hundred.
- Rendering the agent pages only from the worker's run: the contract takes a page off at once, and a renamed handle would leave the old address standing.
- One page per agent and project: the contract has one page under the owner's page.

## A project's links share the website rule as one function, and change the project like any setting

**Id:** 66b41773-d5d3-447c-b130-b98e5477e37a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-ayaav7naskbe, taken over from #846 with its review (the rule copied from `person_links`, `project_updated` with a list); the coordinator's go for the object form, 2026-10-31; docs/api.md §6.11, §16.9
**See:** https://github.com/oliver-zehentleitner/maity — 11b7e786-ecf7-4971-ae04-48760fd1fd41 — as of 2026-10-31
**Revisit when:** a person's website and a project's link need different rules beyond their length

`project_links` checks each link with `person_links.website_problem`,
which takes the length as a parameter (200 for a website, 500 for a
link). A PATCH merges by key as a person's `social` does. A change puts
`"links": true` into the PATCH's one `project_updated`, beside the other
settings it changed; the links are read from the project, not the
event. The public page asks `project_links.public` which links to show:
a link on the repository's host whose path starts with the repository's
path, compared segment by segment and without case after decoding
percent-escapes and resolving `.` and `..` as a browser does, only while
the repository is public; every other link as set. The page's digest holds
the shown links, so a change renders it again.

**Reason:** §6.11 says "as for a person's `website`", and two copies of
that rule would drift apart. Every other settings change in
`project_updated` is a key in the `fields` object, so a second event, or
a list just for links, would make readers handle two shapes.

**Rejected alternatives:**
- A rule of its own in `project_links` (#846): the same checks twice.
- `fields: ["links"]` in an event of its own (#846, the contract's
  first wording): the only `project_updated` with a list.
- Comparing the path as a string prefix: `acme/maity-other` would count
  as inside `acme/maity`.
- Comparing the raw segments (review of #884): `x/../maity`, `%6Daity`,
  `%2e%2e` and `%2F` resolve into the repository's path in a browser but
  not in the comparison, so a private repository's issues would show.
- Only `/` as the separator (delta review of #884): browsers read `\` in
  an https URL as `/`, so `acme\maity` lies inside the repository; `\` is
  therefore a separator after decoding.

## A new project is public for its namespace owner, and the hub's own look at the repository decides before anything is stored

**Id:** 7bc52549-f0eb-4596-800d-e3ec61b563a8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §6.1 and §16.9 (#865, #875); the card tsk-es3adbcyvy4v from the coordinator, 2026-10-31; the implementation of `create_project` and `patch_project`
**Revisit when:** the instance offers a way to ask the forge without a token for a repository that is public, or the dashboard's create form needs the hub's answer before it sends
**See:** public-pages.md#a-public-page-is-a-row-of-public_page-served-by-the-app-shells-route — 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b — as of 2026-10-31

`POST /projects` stores `public_page: on` for a creator who owns the namespace (for an organisation, one of its owners)
and `off` for anyone else; `off` is taken from anyone, `on` from an owner only. When a `repository` comes with the call
(or later with a `PATCH`), `routes/projects._looks_public` asks the forge once, with the hub's own reader
(`Forge.repository_public`: anything but `private: false` counts as private), and the page stays `off` unless the answer
was public. The call is made before the transaction opens, so no database transaction waits on the forge, and a first
answer of public is stored in `repository_public`, so the page need not wait for the probe's round. A `PATCH` that
changes the repository to one the hub does not see public turns an `on` page `off` and writes `project_updated`; the
same pass as any other way the page stops being served (`agent_owners.reconcile`, here also archiving) follows.

A hub without its own forge token sees no repository public, so there every project with a repository starts `off` until
its namespace owner turns the page on. The look is made for every caller that does not send `off`, a member of an
organisation who is no owner included, whose project starts `off` anyway: the role is only known inside the transaction,
and reading it beforehand would read the same rows twice for one request, so one uncached forge request is spent instead.

**Reason:** a project is public by default so a new project is findable and its outside agents are allowed (the
maintainer's decision, 2026-10-31), but creating one must never publish what the creator could not see the hub see: a
private repository's name and a page that links it. Looking before the transaction keeps a slow forge from holding a
write lock; storing the first answer avoids a window in which a page of a public repository shows no link.

**Rejected alternatives:**
- Create the project `on` and let the probe turn it off: for the length of a round a private repository's page is public.
- Look inside the transaction: a slow or down forge would hold the project's rows, and the call still has to answer.
- Treat an unreadable repository as public: the contract says no answer counts as private (§16.9), and the unreadable
  case is exactly the private one without a grant.

## Visitors read the app from one route over stored rows, and the member routes stay closed

**Id:** eb7fd1c7-d4f1-478f-b77f-bb6878cd515a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's words of 2026-11-01 on the card tsk-jj1tfre7n6zb (logged out sees what logged in sees, read-only, nothing private, "as on GitHub"); the lead's approval of the plan; `docs/api.md` §16.9
**See:** public-pages.md#a-public-page-is-a-row-of-public_page-served-by-the-app-shells-route — 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b — as of 2026-11-01
**Revisit when:** visitors need a read a stored row cannot answer, such as search or paging through a whole board

`GET /public/pages/{path}` answers the `data` the page's render stored beside its HTML. A visitor's read costs
one row, every removal rule of the pages holds without being written twice, and a field is public only if the
renderer puts it there.

**Rejected:**

- A visitor caller in the member routes, with their fields filtered: the routes return members' data by
  default, so a field added later would be public unless someone remembered to exclude it, and every route would
  need its own review. Here the default is that nothing is public.
- A second renderer querying per request: the same output at the cost of a query for every anonymous call.
- Parsing the stored HTML in the browser: a page's markup would become an interface.

`refresh` compares `view` and `data` as well as `inputs`, since a change may reach `data` without touching the
HTML. Such a change keeps the row's `lastmod`, because the sitemap's date says what a crawler can read. Rejected:
`data` in the digest, which would move that date.

## A visitor on the way to a public page never ends at the login

**Id:** 439a36e9-c05c-4c87-a3d3-1cd2ff5061d7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report of 2026-11-01 on the card tsk-jj1tfre7n6zb (public projects and the profile "always login"); reproduced in a browser without a session; `docs/api.md` §1.1, §16.9, §16.11; for the Overview's addresses the card tsk-n2ymkzczcya5
**Revisit when:** the login is no longer the way a mail link goes on after a sign-in

The pages themselves worked; the shell around them does not know visitors and shows the login. So `/explore`,
which the landing page's button named and nothing served, is now a page for everyone, a slash at the end of a
page's address leads to the page, and the join host keeps `/<owner>/<slug>…`. A dashboard address under a
public project stays the login and links the page. A signed-in non-member first went to `?as=public`; since
2026-11-02 they read the same view in the app at the same address (70c80e4f), and since 2026-11-03 the
Overview's own addresses show the public overview to a visitor too (`web/context/routing.md`, 66f1d8b8). `/explore`
is rendered per request behind the public cache: it shows only what the pages show, and a stored row would
need a new input for every project. The board leaves out a `security` card until it is done, as the model
of public projects (projects.md, 038e685e) said and the code did not.

**Rejected:** redirecting a dashboard address to the public page: a card's link from a mail would end there
after a session expired, instead of going on after the sign-in.

## A visitor gets the stored page inside the app shell, and `?as=public` the bare page

**Id:** 70c80e4f-bf45-430d-beb2-7abbab2c8e4c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's words of 2026-11-01 on the card tsk-jj1tfre7n6zb (logged out sees what logged in sees, read-only); the plan the lead approved
**See:** public-pages.md#a-public-page-is-a-row-of-public_page-served-by-the-app-shells-route — 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b — as of 2026-11-02
**Revisit when:** the shell's scripts grow slow enough that the page's text is what most visitors read

A public address now serves the shell with the row's title, description, share tags, canonical link and text
placed in it, so a crawler and a reader without scripts still read the page and the dashboard takes over at the same address.
The row, its removal and the sitemap stay as they were; a page is still a row, and the decision between page and
shell still falls in the shell's route. A failed read of `data` leaves the page's text standing instead of the login.
The marker on the shell counts for the first drawing only; a later visit to the login inside the same load is the
login, not this page.

**Rejected:** a separate address for the app view (two addresses for one thing, as a forge has one); a script tag in
the stored page alone (the bare page's policy allows no script, and the row would hold the shell's file names).

## The public Why is a stored row, an exception to "the export stays in memory"

**Id:** aed779e9-be9c-40d2-a7ea-217cee06e470
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's decision of 2026-11-02 on the card tsk-jj1tfre7n6zb
**Revisit when:** the export's read must reach every replica at once, which a read per process does not do

The view keeps counts, the family's links and attention titles of a public repository in `public_page`, beside
the other views. Its export is read ahead of the interval render with the instance's token alone, in a cache of
its own, because the members' cache may have read with an owner's grant. A render stays off the network, as it
runs in a transaction. The price is a view up to one interval old; a repository turning private empties it with
the look that finds it. Each replica holds its own read and only one renders a pass, so a render with no read, or
an older one by `observed_at`, keeps the stored view instead of emptying it, and every process reads once at start.
A failed read keeps it too, as a failure says nothing about the export; a read that finds the repository names no
export any more empties it.

**Rejected:** answering `why` at request time from the memory cache: §11.3 would stay untouched, but the route
would need a rule for the one kind without a row, and search engines would lose the page.

## An organisation's page reads none of its members

**Id:** 3f7a9d24-6c1e-4b58-9e02-7d41c8a5b6f3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9; the build on the card tsk-jj1tfre7n6zb

`render_org` does not query `org_member`, so a mistake there cannot name one. An organisation without a page has no
row, which makes a private organisation and an unknown handle the same `not_found`. A project moved to another
owner has its page turned off rather than appearing under the new one unasked.

**Rejected:** a list of the organisation's members with public profiles: §16.9 says who belongs to it is not public.

## A card has its own page at its dashboard address, with its text

**Id:** e3bcdf82-e7f1-447d-becd-43171c8cd513
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer to req-0qvbrqwddkc6 of 2026-11-02 (a card's text public, as an issue on a forge); the plan the lead approved on tsk-1g5f436h6ez1
**See:** public-pages.md#a-visitor-gets-the-stored-page-inside-the-app-shell-and-aspublic-the-bare-page — 70c80e4f-bf45-430d-beb2-7abbab2c8e4c — as of 2026-11-02
**Revisit when:** card writes grow slow enough that a render per write shows

A card of a project with a public page is a third kind of page, `card`, at `/{owner}/{slug}/tasks/{id}`, the address
a member opens, and the Board links each id to it. It carries the title, status, label, the holder as the Board
names them, and the body as Markdown without raw HTML (`ugc`, as the project's About). A `security` card has a page
only once it is `done`, a held card none; the moderation paths and every card event call `touch` for it, as they do
for the Board, so the page follows the card in the same transaction. History, requests and links stay out. The notes
were left out at first, as the side that could be widened while the maintainer had not decided; they followed the
same day (see the next entry). Naming the holder as the Board does ties the page to the holder's profile: a person's
change renders the card pages held by them or their agents (`pages_of_member`), and an agent's name or a membership
change renders the project, whose dependents are all its cards.
Every card of the project has a page, also a closed one older than the Board's 30 days or beyond its limit: an
issue stays at its address after it is closed, and a link from a mail or a commit must not break when the card
leaves the Board.

**Rejected:**
- The text on the Board itself: the Board would carry up to 200 bodies per column, and a card would have no address
  to link from a mail or a commit.
- Rendering every card of the person's projects on a profile change, as a project's `touch` would: most of those
  cards do not name the person.
- Pages only for the cards the Board lists: a card would lose its address 30 days after it closed.
- A separate public address such as `/{owner}/{slug}/cards/{id}`: two addresses for one card, against the rule
  that a public page has the address a member opens (§16.11).

## A card's notes are public on its page, as comments under an issue

**Id:** 9e1bb9f3-01aa-4629-82ff-74d340febbd7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-02 on tsk-1g5f436h6ez1 (notes in open projects are public; memory stays private and holds what is sensitive); the plan the lead put on tsk-3w6mf8v40jeh
**See:** public-pages.md#a-card-has-its-own-page-at-its-dashboard-address-with-its-text — e3bcdf82-e7f1-447d-becd-43171c8cd513 — as of 2026-11-02
**Revisit when:** a card's notes grow long enough that its page needs paging

The card's page lists its notes oldest first, each with its author named as the Board names a holder, its date, its
state once resolved, and its body as Markdown without raw HTML. A redacted note keeps its place and shows as removed;
neither its text nor the redaction's reason is published, since a reason may repeat what was removed. A resolved
note shows its state but not its `resolution` (who, when, why): the reason is written to the note's author and
the card's people, as a redaction's is, and the state alone says what became of the note. A note's own
events (`note_added`, `note_resolved`, `note_edited`) and its redaction call `touch` for the card, and an author's profile change
reaches the page through the person's dependents, as a holder's does. Notes have no moderation target of their own:
they follow the card's hold and the `security` rule with it.
An edited note shows its new text with "edited by", the editor named as an author is, the date and the edit's reason;
the old text is gone with the render in the same transaction (`context/cards.md` 0e6b3b31). Unlike a redaction's
reason, an edit's reason is published: the maintainer decided it is shown with the edit mark to every reader, and its
writer knows that, while a redaction's reason is written for the members (2026-11-02, tsk-bj9yb4d8f2cg).

**Rejected:**
- Only open notes: an incorporated or dismissed note is part of the discussion an issue keeps, and the page would
  change meaning when a note is resolved.
- Showing a redacted note's reason: it is written for the members and may name what was removed.

## A public project shows a snapshot of its ticker and who is online, rendered on a timer, never live

**Id:** 65c0167c-f61c-419a-9506-8d9453edd482
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-02 on tsk-hsq3ns8ryd7d (visitors see what is happening as a snapshot, no live connection; humans shown online too); the plan the lead approved on that card
**See:** public-pages.md#a-card-has-its-own-page-at-its-dashboard-address-with-its-text — e3bcdf82-e7f1-447d-becd-43171c8cd513 — as of 2026-11-02
**Revisit when:** the load test of the live ticker for visitors has run

The project's page carries the newest ticker items a visitor may read and who is online, decided in the hub per
item by the card page's rule: a merge only from a repository last seen public and only when every linked card has a
page; a decision only on such a card; deploys, releases, notes, renames and jour fixe reports never, since their
text names what the card rule does not cover. `public_snapshot.Worker` renders every public project page again every
`MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES` under one `worker_runs` claim; presence is read at that moment. A card change
that may take a ticker item off renders the project page at once, so a removal never waits for the timer; a new
item waits for it. Who is online is counted as the names are shown: a member the page does not name (a profile
under a hold, a person who keeps their online status off) is not counted either, since a count beside the names
would point at them; the contract always said so, and the hub counted them until the online switch's change. Known and left so: a decision's text keeps
the card's title from the moment it was decided, since a ticker item is stored text; a later rename does not change it.

The load grows with the page cache, not with connections: a visitor reads a stored row behind the public cache and
reloads to see more, and the hub's cost is one render per project per interval, whatever the number of visitors.
`data.online.as_of` changes with every render and is stored with it, while the HTML, its ETag and the sitemap's date
change only with what the page shows.

**Rejected:**
- A live connection for visitors (a stream or polling the ticker): its load grows with every open tab, and it waits
  for a load test.
- Rendering on every ticker item and presence change: presence changes all the time, and every agent's heartbeat
  would render a page.

## A card event renders only the project's own page, and only when it may take a ticker item off

**Id:** 721bcdfa-9464-4b57-b885-a1455f5adbb8
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** production incident of 2026-11-03 after the deploy of `634f0f60`: `lock_project` waits on the maity project ended in statement timeouts (57014, 503); the holder was idle in transaction with in_state 0 s while its age grew, its last statement the `moderation_hold` read of a card page's render; the lead's go on this fix the same day; the review of #1277 (the member events as a follow-up, card tsk-2k10yf9w7kzw)
**See:** public-pages.md#a-public-project-shows-a-snapshot-of-its-ticker-and-who-is-online-rendered-on-a-timer-never-live — 65c0167c-f61c-419a-9506-8d9453edd482 — as of 2026-11-03
**See:** public-pages.md#a-page-is-rendered-again-in-the-transaction-that-changed-its-input-by-a-registry-of-kinds — b7a13a49-7c56-49d6-bc18-4622b21d0077 — as of 2026-11-03
**Revisit when:** the API can set the `security` label or move a card out of `done`, or another input of the ticker's card rule appears

`events.emit` holds the project row (`lock_project` is its first statement). For a card event of a public project
it renders the Board and the card's own page as before, and the project's page only when the event may take a
ticker item off: a label change, or a status change of a `security` card (`_hides_ticker_entries`, the two inputs
of `public_cards.shown`; a hold is `moderation.apply`'s). That render is `touch(..., dependents=False)`: the
project's own page, none of its dependents, since only that page shows the ticker. Everything else reaches the
page with the snapshot worker. Through the API this render does not happen today: `security` is not a label the
API sets, and `done` has no way out; the rule guards imported cards and a later change of either.

**Reason:** from the ticker's change on, every card event except a creation called `touch(conn, "project", …)`
with its default `removal`, which renders the project's page and every dependent at once: the views, the org,
the agent and person pages, and every card page of the project. On a project with many cards each claim,
report or edit made hundreds of short queries inside the transaction that holds the project row, and every other
write to the project waited behind it. Single-server setups are affected the same way; nothing here is opt-in.

**Rejected alternatives:**
- Rendering the project page with its dependents on every card event (the state before): the incident above.
- Dropping the at-once render and leaving every card change to the snapshot worker: a removal from a public page
  never waits for a timer (`docs/api.md` §16.9), and a hold or an imported `security` card still needs it.
- Rendering after the commit, outside the lock: the removal belongs to the transaction that changed the input
  (b7a13a49), and a second transaction after the commit could fail and leave the page stale. Taken up since in
  a form that answers both (deafb243): the removal still deletes the pages in the writer's transaction, and
  only the render follows the commit.

The member events take the same path with one filter (tsk-2k10yf9w7kzw): a `member_updated` whose `changed`
fields are all in `events.UNSHOWN_MEMBER_FIELDS` renders nothing. These are the language (one event per project of
the person, each under that project's row), the line consent, and a dormant instance or outage policy, which only
change who is online and so wait for the snapshot. Every other member change, a join, and an update that names no
`changed` fields still renders the project page with its dependents, since a member's name stands on the card
pages they hold. Rejected: naming the fields a page shows instead (an allowlist), because a field added later
would silently leave a stale name on a public page; a field missing from the list only costs a render.

## A person can keep their online status off the public pages; their projects' pages then neither name nor count them

**Id:** 54823a3a-96be-4484-9689-8059201b1bb3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer of 2026-11-02 on request req-jkqzzy638k10 (an open project may name who is online, but a person must be able to turn that off in the settings); the maintainer's answer the same day on request req-dv6p6588avjn (option b: a project's page neither names nor counts a person who turned it off, the instance-wide counts still count them); the lead's choices on card tsk-my5gvj4warte the same day (the switch covers the person only, not their agents), which the maintainer approved; the maintainer's answers of 2026-11-03 on requests req-h6z5ddvkeest (the registration note names the switch) and req-yv0z4eq2pwk2 (`people_online` keeps counting, and the account says so); contract `docs/api.md` §16.9 ("Online on public pages")
**See:** public-pages.md#a-public-project-shows-a-snapshot-of-its-ticker-and-who-is-online-rendered-on-a-timer-never-live — 65c0167c-f61c-419a-9506-8d9453edd482 — as of 2026-11-02
**Revisit when:** the maintainer wants the switch to cover a person's agents, wants `people_online` to leave them out after all, or a project's page gets another count of who is online

`human.public_presence` (default `true`) is set in Your account next to `public_profile`. While it is `false` the
snapshot's Online on the person's projects leaves them out entirely: no name, and not in `online.humans`. The
landing page's `people_online` still counts them: it covers the whole instance and names no project; the badge
counts agents only. Turning the switch off takes the person off at once, as every
removal from a public page is; turning it on waits for the next snapshot. The switch never covers the person's
agents: an agent is public work, named by its handle like everywhere else on the page. Since the switch starts on,
the note under the display name at registration says so before the account exists, beside the public profile
(the maintainer's decision on request req-h6z5ddvkeest, 2026-11-03, card tsk-en9mm6x2v3s0).

Known and left so: the landing page's number and the sum of the project pages' numbers can differ by the people who
turned the switch off. On an instance with a single public project whose landing page shows `people_online` (a
self-hosted instance, typically), that difference is at most the number of members online with the switch off
(exactly that when every human of the instance is a member of that project), and when there is exactly one it can
be that person; the two numbers are computed on different timers, which blurs it but does not
close it (found in the review of the contract). The maintainer decided on 2026-11-03 (request req-yv0z4eq2pwk2)
that `people_online` keeps counting them, and that the note under the switch in the account says so: the start
page's number still counts you, without your name (card tsk-en9mm6x2v3s0).

**Rejected:**
- Counted, not named: "humans online" minus the names shown is exactly the one person who turned it off, however
  many members a project has (found in the review of the contract); the maintainer chose to leave them out of the
  count instead.
- Leaving the person out of the instance-wide counts as well: no project is named there, so nothing points at
  anyone, and the landing page would need a filter of its own.
- A second switch for the person's agents: not wanted now; the lead puts it to the maintainer.
