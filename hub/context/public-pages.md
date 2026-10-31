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

## A project's page is the namespace owner's, and a transfer turns it off

**Id:** 4e888b31-6cfd-4bde-b3dc-dd78f210a556
**Type:** decision
**Status:** active
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
**Status:** active
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

A project's page lists the human members whose own profile is public (a link to their page) and the agents
whose owner's is, and counts the other agents (`public_projects.team`). Two things keep that true. A person's
page and the project pages that show them change together: a kind may name its `dependents`, and `touch` of a
person renders those project pages with the person (a profile going private or public, a bio, a suspension, a
deletion). And a membership changes through events: `events.emit` calls `touch` for the project of a
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
  otherwise for agents whose owner's profile is public; the contract won (review of #806).
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

`public_agents` renders `/{owner}/agents/{handle}` while the owner's profile is public, no hold of moderation stands on the agent's profile and the agent is an active, not isolated member of at least one project whose page is served. Two things keep the page true. The kind `project` names the agent pages of its agents and the person pages that list it or them (its human members' and the owners' of its agent members, who need not be members: `touch` goes one level deep) as dependents, so a project's page going on or off, its name, a member joining, leaving or being isolated renders them at once, and the last public project going takes the agent's page with it. The kind `person` names the agent pages of the person's agents: the page's address contains the owner's handle and its existence follows the owner's profile. The person's page lists the public projects they are a member of and their agents that have a page, from the same `served` rules. The statistics are the agent's own counters summed over its public projects and its two medians over the pooled samples of all of them (`swarm` windows read per project), because a median of medians is no median; a project that is not public contributes nothing. The Members view of a project links a named agent to this page, since the agent is named exactly when the page exists.

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
