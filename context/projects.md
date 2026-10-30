# Projects

## The project overview reuses the project and member reads; one new endpoint carries only the counts and recent reports

**Id:** f55d74ac-1758-4318-8d81-e28dee965939
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner, 2026-10-22; the maintainer approved the overview page the same day; contract in `docs/api.md` §6.11
**Revisit when:** the hub serves the change ticker's merge items (§17; the contract alone does not count): its merge items are then added to `reports`, de-duplicated by pull request number, not a replacement for the card reports; or the overview needs data no existing read has

The overview page reads the project (`GET /projects/{slug}`: name,
state, repository URL, the Keep the Why export with its dashboard links,
the policy preset) and the member list as they are. It adds one
endpoint, `GET /projects/{slug}/overview`. That endpoint holds only what
no existing read gives cheaply: card counts per status, counts of the
open requests the caller may see, and the latest report of the ten most
recently reported cards. The two links are not new settings. The
repository stays a human-only `project:admin` field, and the Keep the
Why dashboard URL still comes from the repository's own
`.keep-the-why`.

**Reason:** the counts would otherwise cost the browser a full paging of
every card and every open request, which the hub answers with one
grouped query each. Leaving the project and the member view out of the
new endpoint keeps a single place for their shapes and for their
visibility rules (the member view's admin-only fields above all). The
dashboard already holds both for its header.

**Rejected alternatives:**
- One aggregate with everything, project and members included. One
  call, but two places would return the member view, and both would have
  to get its admin-only fields right.
- `counts` parameters on `GET …/tasks` and `GET …/requests`. No new
  path, but two paged lists would gain a second response shape, and
  "the latest reports" would still need its own ordering.
- Paging in the browser. No contract change, but many calls on a large
  board, and the cost grows with every closed card.
- A project setting for the repository or Keep the Why link that an
  admin agent may set. §2.3 keeps `repository` for humans, and the Keep
  the Why URL has no override by an earlier decision (§6.1, §11.3).

## A closed project refuses additions, never removal

**Id:** e9c3b578-c282-43c1-b5f4-4a494ae0464e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's rulings of 2026-10-22 on the group-chat, attachment and card-link contracts (`docs/api.md` §6.1, §9.2)
**Revisit when:** a project state is added that should refuse more than additions, or an operator needs an archived project frozen for an audit or legal hold

In a project that is `archived` (until 2026-10-27 also `accepted`, which
migration 0094 maps to `archived`), a write that adds one of the
following is refused with `project_closed`: a claim, a card, a group
chat, a participant added to one, an upload, a card link, a note.
Posting messages stays allowed, in project messages and in group chats
alike (a message that names an attachment adds an upload and is refused
with it): the rule refuses creating chats and adding participants, not
talking in them. A write that takes
something out stays allowed whatever the state: leaving or removing a
participant, redacting a message or a note, deleting an attachment,
removing a link, resolving a note. One rule for every feature, so that
each contract does not invent its own reading of "closed".

**Reason:** removing harmful or private content must stay possible
after a project closed. Read-only applies to adding, not to removal: a
secret pasted into a chat or a private file attached to a message has to
be removable whatever state the project is in.

**Rejected alternatives:**
- An archived project read-only for every write (the first attachments
  draft): it keeps harmful or private content in place for good.
- Leaving the state's effect to each feature: three contracts already
  read "closed" three different ways.

## A project sets its own onboarding: a default briefing and whom a new member checks in with

**Id:** 62cbc05a-f046-48e4-8ec0-2a9e5bf7aa31
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's message of 2026-10-23; contract in `docs/api.md` §6.1, §5.2, §2.3
**Revisit when:** projects need different onboarding per role or per area, or a check-in needs to gate work rather than advise
**See:** join.md#the-join-carries-the-agents-briefing-it-reaches-the-agent-only-after-the-exchange — c383b1fe-0eb4-454c-8a5a-1919f21b820f — as of 2026-10-23
**See:** trust.md#an-admin-agent-manages-agent-memberships-below-its-own-trust-no-agent-can-ever-act-against-a-humans-membership — 4a480c4d-53bd-4c34-a126-6d857fa7f255 — as of 2026-10-23

A project carries `settings.onboarding`: a default briefing, and
`check_in_with` — a member, a role, or the coordinator — to whom a new
member reports before it takes work. A membership without a briefing of
its own gets the project's in its resume packet, marked as the project
default and not copied onto the membership, so a later change reaches
every such member; its own briefing, once set, wins. Until the member
has written to its check-in target or held a claim, its packet names whom
to check in with. Every project starts with a check-in with the
coordinator and no briefing text, and a project without the setting
behaves the same, because absent means that default. A human with
`project:admin` sets it, and so does an admin agent; it is the one
project setting an agent may change.

**Reason:** three agents joined without a briefing, their resume told
them nothing, and they idled for two hours; the coordinator's welcome
arrived as an event, but an agent reads its briefing first. The
maintainer: new members report to the coordinator after onboarding and
are told there how to start and how things work; that differs per
project, so it is a project setting the coordinator or an admin can set.
The admin agent may set it because an onboarding text is coordination,
not the rule set every agent loads, which stays a human's.

**Rejected alternatives:**
- Briefings only per membership, as before: a human has to write one
  for every agent, and every join without one leaves the agent idle with
  nothing to go on.

## The project badge is opt-in and shows counts only

**Id:** c436ef08-627d-46c9-b3c9-92b1b0fdf3e4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision with the designer, 2026-10-25; contract in `docs/api.md` §6.20, §6.1
**Revisit when:** public projects or join requests exist, or a badge variant needs more than counts

A project can serve a README badge at `GET /badge/{slug}.svg`, public
and unauthenticated. It is off unless the project's policy sets
`badge` to `members` or `agents_online`; while it is off, and for an
unknown or closed project, the answer is the generic `not_found`, so
the URL never tells whether a project exists. The badge carries
numbers only: how many humans and agents are active members, or how
many agents are online now. It never carries a name, a handle or an
avatar.

**Reason:** the badge reveals a project's team size and presence to
anyone who holds the URL, so switching it on is the owner's choice per
project, not a default. Counts are the whole of what leaves the
project through it: a name on a badge would identify people and agents
outside the project, where the member view's visibility rules do not
reach.

**Rejected alternatives:**
- An always-on badge: it leaks presence by default, for every project,
  to anyone who guesses a slug.
- A badge with member names or avatars: it identifies people and
  agents outside the project.
- A redirect to shields.io: an external dependency, and the hub would
  still have to expose the number for it to render.

## Changing the project badge needs no reason

**Id:** edccf213-6a0c-40e7-b448-ac1413eb3321
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision in the team chat, 2026-10-29; contract in `docs/api.md` §6.1, §6.20 (#617)
**Revisit when:** another policy field turns out to be as purely presentational as the badge
**See:** projects.md#the-project-badge-is-opt-in-and-shows-counts-only — c436ef08-627d-46c9-b3c9-92b1b0fdf3e4 — as of 2026-10-29

A `PATCH` whose policy change is `badge` alone takes `reason`
optionally; its `policy_changed` carries `reason: null` when none was
sent. Every other policy field keeps its reason, and a badge change
sent together with another policy field or with `state` still needs
one. The event and the `rules_version` bump stay, so the switch is
still visible to everyone.

**Reason:** the maintainer found the reason prompt in the project
settings a needless step for the badge. The badge only decides what a
README shows; it changes nothing about how the project works, who may
do what or how cards move.

**Rejected alternatives:**
- Keeping the reason for the badge like for every policy field (the
  state before): it asked for an audit note on a choice that guards
  nothing.

## The memory provider is chosen at creation, Keep the Why preselected; the setup is an agent's work through cards and pull requests

**Id:** 822d63b0-99da-4092-aaef-93c0674934a2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** maintainer decision, 2026-10-25, extended by the maintainer's request of 2026-10-30 (CI linter, published dashboard with a chosen path); contract in `docs/api.md` §6.1, §6.21, §5.2, §6.4
**Revisit when:** a second memory provider is added, or the setup needs more than a pull request
**See:** scope.md#agents-are-brought-not-run-the-hub-organises-the-sessions-do-the-work — 517defc6-720e-4a17-90fb-a061279c8fee — as of 2026-10-25
**See:** scope.md#keep-the-why-stays-external-and-optional-the-hub-never-reimplements-it — a498e8a8-092d-44e1-9c4a-50c6aa3d1105 — as of 2026-10-25

`POST /projects` takes `memory.provider`, `none` or `keep-the-why`,
with `keep-the-why` preselected; the boolean `keep_the_why` stays as a
readable alias so nothing breaks, and `PATCH` may change the provider.
With the provider come prefilled setup options — set Keep the Why up
in the repository, add its badge to the README, add the Maity badge to
the README (the last one offered under `none` as well), and since
2026-10-30 run `ktw-lint` in the repository's CI and publish the Keep
the Why dashboard where the repository publishes its documentation
(GitHub Pages, GitLab Pages), under a path the creator may change
(default `keep-the-why-dashboard`), with the `dashboard-state:` line set
so the overview links it (the maintainer's request of 2026-10-30). The
path is a URL path below the published documentation site, and the line
gets the URL of the dashboard's `state.json` below it, for the root and
for every child with its own `.keep-the-why`. A repository without CI
gets a workflow that runs only the lint step. These details are the
contract's reading of that request, settled in the review of #715, not
words of the maintainer. And for every
ticked option the hub opens one card of kind `setup` at creation, or
when the repository is set later: `open`, claimable under the claim
policy, at the repository root, with a pull request against the default
branch as its acceptance and never a direct push. The resume packet
names the open setup cards to the agents that join until they are done;
the owner may assign them like any card. Maity itself never stores
project memory; the hub holds operative coordination data only.

**Reason:** the hub never writes into repositories and runs no agents
(`scope.md`, the two entries cited above), so the only place a
repository can be set up is an agent's workspace, and a card is how
work reaches an agent — the first agent that joins finds the setup
waiting instead of a human having to pick an agent first. Preselecting
Keep the Why makes the default project documented from day one, while
`none` keeps the hub complete without any provider. A provider field
rather than a boolean leaves room for a second provider without a
second contract change.

**Rejected alternatives:**
- The hub performs the setup itself through the forge API: it would
  need write access to repositories, against the boundary in
  `scope.md`, and would turn the read-only probe into a writer.
- The owner must pick an agent first and hand it the setup: blocks the
  setup until a human acts, where a self-claimable card lets the first
  agent that arrives take it.
- A boolean `keep_the_why` only: cannot express a second provider
  later; it stays as the alias of `memory.provider`.
- `dashboard_path` as a directory in the repository: Pages sources
  differ per forge and setting (`/docs`, a `gh-pages` branch, GitLab's
  `public/`), so a directory says nothing about the URL. The URL is what
  the creator sees and what the hub needs.
- The page's URL in `dashboard-state:`: the hub reads JSON from that
  line (§11.3); a page URL would leave every member at
  `ktw_unavailable`.
- A hub setting for the dashboard URL: the repository stays the one
  source of the Keep the Why links (§6.1).

## The swarm is a statistic: a section of the project's Overview, shown to the world only on a public project's page

**Id:** bfe4c4a6-b600-40ea-9038-d69ffb99f46f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 (card tsk-w89mspg3gwx1); contract `docs/api.md` §6.22, §16.9, §16.11
**Revisit when:** an owner wants one view across all their projects (stage 2), or a project wants its numbers public without a public page
**Supersedes:** cf9bc176-3287-46e5-8bac-e11b872448d0

The swarm's numbers — the window counters per member and in all, and
who is at work — are a section of the project's Overview for members
(since 2026-10-30 the Overview's own Swarm tab, `overview/swarm`).
There is no Swarm tab, no separate public swarm address and no
`swarm_public` switch any more. A project whose page is public (§16.9)
shows the same statistics reduced to agents, and only agents whose
owner's profile is public, without presence: the page is a stored file
rendered on change, and presence changes all the time.

**Reason:** the swarm turned out to be a statistic about the project,
not a place of its own; it belongs where the project is summarised. A
second public switch next to `public_page` would let a project be
"public" in two different ways, with two answers to what a visitor may
see. Dropping presence from the public version follows from the stored
page and keeps a person-shaped pattern (when an owner's agents are at
work) off a page meant for search engines.

**Rejected alternatives:**
- Keep the public swarm page and its switch next to the public project
  page: two public surfaces for one project, each with its own rules.
- Show presence on the public page: it would have to be rendered on
  every presence change or be stale by design.

## The swarm page shows the team at work to members, and a reduced, agents-only version to the world when the project switches it on

**Id:** cf9bc176-3287-46e5-8bac-e11b872448d0
**Type:** decision
**Status:** superseded
**Superseded by:** bfe4c4a6-b600-40ea-9038-d69ffb99f46f
**Evidence:** confirmed
**Source:** the maintainer's decisions in the inbox, 2026-10-25 (the idea, then the scope: project, members, public per project); contract `docs/api.md` §6.22, policy `swarm_public` in §6.1
**Revisit when:** an owner wants one view across all their projects (stage 2), or public projects exist (then the public swarm page is part of the public project view)

Each project has a swarm page: who is online, who holds what, and the
window counters per member — cards done, reviews given, pull requests
merged, handovers, claim-to-done and review-to-done medians — derived
from the hub's own rows, never stored. Members see all of it. A project
may switch on a public version, served without a session: agents only,
names and counts and presence, no humans, no card titles, no avatars,
the totals recomputed over agents. It is off by default, per project,
like the badge — and it shows more than the badge: the agents' names,
their owners' handles and when they are at work.

**Reason:** the swarm is the thing Maity is about, and showing it is
what makes a project's README badge worth clicking through; the counters
are the first answer to "does this team work". The public version
exposes names and presence patterns of agents, which the badge does
not, so it is a human's deliberate switch and not a default; the board
itself stays private; humans are kept off it because a person's working
hours are theirs, while an agent's presence is what the owner put it
there for.

**Rejected alternatives:**
- Public by default: a project should opt into being watched.
- Humans on the public page: their presence pattern is personal data
  for no gain; the public page is about the agents.
- Card titles on the public page: the board is members' business; the
  count says enough.
- Measuring tokens or cost: the hub counts no tokens (`scope.md`).

## Keep the Why is guaranteed by the hub: a commitment at resume, a reminder, the owner's notification, and a why on every code report

**Id:** 7c1a4f0e-2b8d-4c6e-9a3f-5e2d8b7a1c90
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-25, in the project's chat, after the team rule of `process.md` was recorded the same day; contract in `docs/api.md` §6.23, §6.1, §5.2, §6.6, §8.2, §13, §18.1
**Revisit when:** the probe can read a file at a pull request's head (then the hub can verify the referenced entry instead of trusting the reference), or a project needs a different reminder interval than 30 and 60 minutes, or a second memory provider needs a commitment of its own

A project whose memory provider is Keep the Why makes every agent carry
it, through the hub rather than through a rule the team remembers:
`policy.keep_the_why` is `required` by default under that provider. At
resume the agent is told so and confirms once per instance (`maity ack
keep-the-why`), with one deadline per instance — 30 minutes after its
first resume in the project — that survives sessions: at the deadline an
instance that has not confirmed is reminded with an event that wakes it
and the member view marks it, and 30 minutes later its owner gets a
notification; each once per outstanding commitment. A
code report carries `why`: the reference to the entry that keeps the
change's reasoning, or a stated reason why this change has none; a code
report without it is refused. The hub reads no repository for any of
this: it records the commitment and the reference; whether the entry is
there and good remains the review's gate.

**Reason:** Keep the Why is part of the project, so every agent must use
it, and a rule written in `context/` only reaches the agents that read
it and the reviewers who happen to ask. The maintainer wanted Maity to
guarantee it as a system: tell the agent in its briefing, have it
confirm, remind it, and tell the owner when the confirmation does not
come. The reference on the report makes the commitment checkable per
change without the hub reading repositories (`scope.md`), and puts the
one fact the reviewer needs — which entry, or why none — where the
review already looks.

**Rejected alternatives:**
- The team rule alone (`process.md`): it depends on who reviews and on
  the agent having read it; it stays as the interim and as the reviewers'
  gate.
- Refusing work until the confirmation (no claim, no report before the
  ack): an agent that cannot confirm would be shut out of all work with
  nobody told; the reminder-then-owner path keeps the human in the loop
  instead.
- Verifying the referenced entry against the repository at report
  time: the hub would read repository files, which `scope.md` keeps out
  of V1; deferred to a probe read at the pull request's head.
- A confirmation per session rather than per instance: a confirmation
  every resume would be noise for the long-running agents of this
  project; per instance keeps it one honest act per worker.
- A clock per session (reminder 30 minutes into a session, the owner
  at 60): an agent that resumes every few minutes — the normal
  heartbeat of the agents here, since every resume closes the previous
  session — would never reach either mark, and nobody would learn that
  it never confirmed. The deadline belongs to the commitment, which is
  per instance, so it survives the sessions.

## Maity tells every agent how to load Keep the Why and lets it adopt the project's personal defaults

**Id:** 4859417a-15f0-44c1-821e-cc80f888e34d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answers in the Maity chat, 2026-10-27 ("Maity soll das gewährleisten", defaults for project and personal settings); an incident the same day: the coordinating agent worked for hours without the skill; contract in `docs/api.md` §6.23
**Revisit when:** the skill ships through a channel every harness installs from by itself; or an agent harness needs a load instruction the `load` text cannot express
**See:** projects.md#keep-the-why-is-guaranteed-by-the-hub-a-commitment-at-resume-a-reminder-the-owners-notification-and-a-why-on-every-code-report — 7c1a4f0e-2b8d-4c6e-9a3f-5e2d8b7a1c90 — as of 2026-10-27

The resume packet's `keep_the_why` block tells the agent how to install
the skill (the skills installer, or a Git fallback for a machine without
Node), how to load it per harness, and where the project's
`.keep-the-why` is. The CLI prints this first, before the briefing. A
project policy, `keep_the_why_defaults`, decides whether the agent adopts
the personal settings the repository offers without asking its human
(`adopt`, the default) or runs the skill's personal wizard with them —
only on a machine with no personal file for the project yet; an
existing one is never overwritten or re-asked.

**Reason:** the commitment at resume only made the agent say that it
uses Keep the Why. It did not get the skill onto the machine. An agent
started outside its clone never read the repository's `AGENTS.md`, found
no installed skill and had no `npx`, so it confirmed nothing and wrote
entries from the format alone. Each new agent machine would also ask the
owner the personal wizard again. The hub still reads no repository: it
hands out instructions and a path, and the settings stay in
`.keep-the-why`, where the skill expects them.

**Rejected alternatives:**
- Leave installation to each agent's operator: the gap that caused the
  incident.
- Vendoring the skill into every project repository: the skill's own
  setup advises against it, and copies drift from the published
  version.
- Storing the personal defaults in Maity's project settings: a second
  source next to `.keep-the-why` that the skill does not read.
- Setting `personal-defaults-policy: auto-accept` in the agent machine's
  `~/.keep-the-why/config`: that changes the machine for every project;
  a session instruction scoped to this project does the same.

## Projects live in their owner's namespace, owner/slug, as on a forge; old names stay aliases; the change is made once in v1 before the launch

**Id:** 281820c9-2286-45c4-9389-603b7e8a3923
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the chat, 2026-10-27 ("ja unbedingt jetzt vor launch"), on the contract owner's proposal; the three details (human owners only, aliases on rename and transfer, old addresses forwarded) in the inbox; contract in `docs/api.md` §6.25
**Revisit when:** organisations become namespace owners (they share the namespace of human handles); or the one-segment API routes are found in use after the release (then a `v2`-style period, §1.6)
**See:** naming.md#a-handle-is-a-renameable-alias-of-a-fixed-id-old-handles-stay-reserved-for-that-id — d5a4542f-63cc-4c1c-962e-f1c02df48ee9 — as of 2026-10-27

A project is addressed as `<owner>/<slug>` — in the API
(`/projects/{owner}/{slug}/…`), the dashboard, the badge, the public pages
and every reference shown outside the project. The namespace owner is
a human or an organisation (see 33f520b9-5aaa-4aed-96f4-e90bf3749c56),
the creator or the organisation it names; a slug is unique within that
namespace only. A
rename or a transfer keeps the old full name as an alias that is never
given away; a request on an alias is served like one on the current
name. The one-segment API routes are gone; an old path is simply
`not_found` (the path-routing decision of 2026-10-29,
e34ae588-4dbc-423c-8da8-29fc62436cb5, removed the `client_outdated`
answer, the frozen `legacy_slug` and the old badge, swarm, `#/p/…` and
webhook addresses that had been kept during the move). A slug may never
be one of the words that follow a project in a route, and the
dashboard's first path segments are reserved as handles (§16.11). A
transfer needs the receiver's consent, and the namespace owner cannot be
demoted or removed while the project lives under their name.
The revisit point on organisations was settled by the organisations
decision of 2026-10-28: they share this namespace as a second kind of
owner. The aliases from a rename or a transfer stay (see e34ae588 for
why they are a feature, not legacy).

**Reason:** with self-registration on maity.team an instance-wide slug
would let the first comer own `shop` or `blog` for everyone, the
problem global agent handles already solved with `owner/handle`
(naming.md). The owner's handle is the one name every project already
has exactly one of, it is unique instance-wide and renameable through
aliases, so `owner/slug` needs no registry and reads as what it is. The
change touches every project route, which §1.6 would serve as `v2`; but
before the launch every caller is one of the project's own clients, so
one coordinated release costs less than carrying two route trees, and
a two-segment path `/projects/a/b` cannot be served in both forms
without guessing.

**Rejected alternatives:**
- Keeping instance-wide slugs: first come, first served for common
  names on a shared SaaS, and no way out once a name is taken.
- A `v2` path next to `v1`: the clean form after a launch, here a second
  route tree to maintain for callers that do not exist yet.
- Serving the old and the new routes side by side under `v1`:
  `/projects/maity/rules` is both "rules of maity" and "project rules of
  owner maity"; any tie-break rule silently misroutes someone.
- An opaque project id in the API and owner/slug only in the dashboard:
  stable paths, but agents and humans would read and write two names for
  one thing, and every log line and link would need a lookup.

## A project has a fixed id beside its full name; a runner keys a workspace on the id

**Id:** d1d2d3df-3216-41d9-ab69-8ee183a05f71
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the CLI implementer's contract question while building the runner side of the project namespace, 2026-10-27, ruled by the contract owner; contract in `docs/api.md` §6.25 and §15.5
**See:** projects.md#projects-live-in-their-owners-namespace-ownerslug-as-on-a-forge-old-names-stay-aliases-the-change-is-made-once-in-v1-before-the-launch — 281820c9-2286-45c4-9389-603b7e8a3923 — as of 2026-10-27

A project carries an opaque `id` that no rename or transfer changes. The
API still addresses projects by `owner/slug`. A runner keeps each
workspace under the project's id and the clone name, and its placement
view carries the project's earlier full names, so that a configured
project list written with an old name still matches.

**Reason:** a runner that keyed its clone directory on the full name
would put the next pickup after a rename into a new, empty directory.
The old clone, holding the agent's credential, would be orphaned, and
"continue the existing workspace" would silently fail. Agent and clone
name alone do not identify a workspace either, because one agent can
hold clones of the same name in two projects.

**Rejected alternatives:**
- Keying on the full name and moving the directory on every rename: the
  runner would have to learn of renames reliably while offline, and a
  missed one strands the clone.
- Mapping old names to new ones from the aliases at pickup: it works
  only while the runner still has the alias history, and it couples the
  workspace to naming.

## A project moves through plan, build, review and launch; 'released' is a separate mark that tightens the rules for good

**Id:** de8abccf-94dc-4947-9926-463aa13edd8f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day; why leaving launch is ungated: the Grok review of PR #644, 2026-10-29
**See:** projects.md#a-closed-project-refuses-additions-never-removal — e9c3b578-c282-43c1-b5f4-4a494ae0464e — as of 2026-10-27

A project's state is plan (concept and contracts, no implementation
cards), build, review (feature stop, load test, acceptance; the former
freeze), launch (live) or archived. Separately, 'released' is set once,
with the first release tag, and never cleared: from then on interfaces
change only with versioning and a transition period, migrations stay
backward compatible and the release checklist is mandatory. After a
launch the project returns to build, still released. Moving to launch
needs the owner's go. Only entering launch is gated: leaving it, back to
build or into review or archived, is any admin's transition with a
reason, as between every other pair of states (§6.1). Why leaving is
free is inferred, not stated by the maintainer: the go is for taking the
project live, the commitment to users, and stepping back from it is
ordinary work. Everything else here is confirmed.

**Reason:** before anyone uses a project, interfaces can change freely,
as owner/slug was changed on Maity itself today; afterwards they cannot.
That difference is a property of the project's history, not of its
current phase, so it is a mark, not a state.

**Rejected alternatives:**
- 'Released' as a fifth state: it would be lost on the next move back to
  build.

## Public projects and profiles follow the forge model: public on the free tier, private later as a paid feature

**Id:** 038e685e-62bb-4f21-be5d-ab4a58b9c444
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#later-stages-agreed-in-principle-and-deliberately-not-in-v1-public-projects-and-discovery-sponsoring-and-credits-a-managed-instance-per-customer-federation — 54e1a38b-1e54-480f-87f2-014139a563d1 — as of 2026-10-27

Each project is public or private; on the free tier it is public, and
private comes later as a paid feature; existing projects stay private
until their owner switches. A public project shows its overview, a
read-only board, the team with the org chart, the swarm and the ticker;
cards labelled 'security' stay internal until done. Never public: the
inbox and requests, chats and messages, card notes, memory, preferences,
briefings, away reasons, runners and placements, and any address. The
owner's address `/<owner>` (the path-routing decision of 2026-10-29,
e34ae588-4dbc-423c-8da8-29fc62436cb5) is a public profile: avatar, name,
public projects and their own agents with presence.

**Reason:** the maintainer orients the hosted offering on the forge
model, where public is the free default and privacy is paid for; the
coordination traffic itself stays private because it carries personal
and security detail.

**Rejected alternatives:**
- Showing only the overview and the team, and making security cards
  public too: both offered as options and not chosen; no reason was
  given beyond the proposal's comparison with security advisories on a
  forge.

## Organisations are a second kind of namespace owner beside humans, in the same owner/slug namespace; their owners own every project, admins and members only what they are added to

**Id:** 33f520b9-5aaa-4aed-96f4-e90bf3749c56
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-28 (request req-nj9xa739bacm); the details are the contract owner's; contract in docs/api.md §6.26
**Revisit when:** private organisations are taken up as a paid feature, or an installation on a forge organisation is to serve a Maity organisation (docs/api.md §11.4, "Follow-up")
**See:** projects.md#projects-live-in-their-owners-namespace-ownerslug-as-on-a-forge-old-names-stay-aliases-the-change-is-made-once-in-v1-before-the-launch — 281820c9-2286-45c4-9389-603b7e8a3923 — as of 2026-10-29

Any approved human may create an organisation (at most five as owner
by default, an instance limit) and becomes its first owner. Its handle
shares the namespace of human handles, with the same syntax, reserved
words, uniqueness and aliases, so a project of an organisation is
`<org>/<slug>` like any other. An organisation has owners, admins and
members, all humans who joined by consenting to an invitation, and
always at least one owner. Every owner holds trust owner in every
project of the organisation, kept by the hub; admins add and remove
members and admins and create projects; members create projects only
when the organisation allows it. Projects move into and out of an
organisation by the existing transfer; an owner of the receiving
organisation speaks for it, an admin needs one owner's go. An
organisation is deleted only while it owns no open project, and its
handle is never released. Its page is public only by its owners' choice
and never lists its members. A project of an organisation reads its
repository with the forge grants of the owner who confirmed it, until
that person stops being an owner; forge installations on organisations
stay a follow-up. Moderation suspends the organisation, never its
people's accounts. Private organisations come later as a paid feature.

**Reason:** a team's projects should not hang on one person's account,
and the namespace decision already foresaw organisations sharing the
namespace of human handles, as on a forge, where users and
organisations are both owners in one name space. Giving ownership to
the organisation's owners alone keeps the strong project rights in few
hands while the organisation can still grow. The details follow the
same care. An invitation answers the same way for every handle, and
its item carries nothing that differs between a person and nobody, so
inviting never becomes a probe for who has an account. An organisation
holds no forge grant of its own while forge organisation installations
are not linked; the owner who confirms the repository lends theirs and
is named as `confirmed_by`, so whose access reads it is always one
named person, and it stops when they stop being an owner. A suspension
targets the organisation, never its people, since a project report
says nothing about each member's own conduct. The owner limit gates
only creating an organisation: becoming an owner by invitation or
promotion is someone else's word as well. An admin's transfer in needs
one owner's go, because only owners carry the rights an organisation's
projects confer. Every change of owners or projects runs under one
lock on the organisation, so the last owner and the owners' memberships
cannot be lost to two changes at once. Two open invitations may reach
one human under a handle and an alias; the first `go` withdraws the
others in the same transaction rather than the second being refused
when it is made, because refusing it would mean resolving the typed
value to a human and telling the inviter so, the very probe the uniform
answer exists to prevent. Invitations for the role `owner` are revoked
by owners only, as only owners issue them. A human who owns both
organisations keeps their membership through a transfer between them,
as a receiving human does, so the move is not a removal with its
consequences followed by a join of the same person.

**Rejected alternatives:**
- Organisations in a namespace of their own (`/orgs/<x>/…`): an
  organisation's projects would either collide with a human's of the
  same name or need a prefix in every address; the decision was one
  shared namespace, as forges have.
- Automatic project membership for every organisation member: it would
  give every member of an organisation every one of its projects,
  however large the organisation grows; only owners get it, everyone
  else is added per project.
- Telling the inviter that a handle is unknown: it turns the invitation
  into a probe for accounts.
- A forge grant of the organisation itself: it needs an installation on
  the forge organisation, which is a follow-up.
- Suspending the accounts of an organisation's owners with it: it
  punishes people for a project report without a decision on each of
  them.
- Refusing a second invitation that reaches an already invited human
  under another name (`invited` resolved through aliases): it tells the
  inviter that two names are one account.
- Ending and re-creating a shared owner's membership on a transfer
  between organisations: the removal's consequences (§6.2) and a
  `member_joined` for someone who never left.

## A member's own settings in a project override their personal defaults

**Id:** b880260a-094c-4045-989e-6a737f314e79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the team chat, 2026-10-29 ("machen wir das als muster, dort defaults setzen die aber pro projekt überschrieben werden können"); contract `docs/api.md` §6.2 "A member's own settings in a project"
**Revisit when:** a setting needs a third level (an organisation's default between the person's and the project's)

Settings that concern how a human works in a project, not how the
project works, live in two places: the human's account holds the
personal default, and the human's membership holds an override per
project, `null` meaning "use my default". They are the member's own and
apart from the project's settings, which the owner and admins keep. In
the dashboard both are one Settings view of the project with two tabs,
the project's and the member's own (`settings/mine`), since 2026-10-30
on the maintainer's word ("ich würde nur ein settings machen und darin
zwei unter seiten/tabs"); a separate My settings view next to Settings
was two entries for one question. The
first is the threshold after which the human hears of their agents that
are not listening; the firewall for one's own agents (card
tsk-5c6hw63ncq3m) follows the same shape.

**Reason:** the maintainer wants one place to set a value once and a way
to differ in the projects where it matters, without asking a project's
owner.

**Rejected alternatives:**
- One value per project set by the project's owner: it decides for every
  member how they want to be told about their own agents.
- Only a personal value: a member cannot treat a busy project
  differently from a quiet one.

## A change of the hub's own rules text bumps every project's rules version once

**Id:** bea10667-bbe1-4cf3-a93b-7eeabe50eb1c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's decision of 2026-10-30 on a hub agent's question while building the duty line (card tsk-n6b8q0tz9yt2); contract `docs/api.md` §6.9 (#731)
**Revisit when:** agents receive the rules by push instead of reading them at resume, or the generated text moves out of the hub's code

The generated rules contain text that lives in the hub's code: the duty
line, the briefs per trust and role, the attachment rule. That text
counts as an input of the rules. Each project stores a digest of the
generated text it was last bumped for; a hub that starts with a
different digest bumps that project's `rules_version` once, with
`rules_changed`, under the project lock. A new project starts with the
current digest. A session switching duty bumps nothing, since the duty
line differs per caller.

**Reason:** agents read `rules.markdown` only when the rules version
moved since their cursor. Without a bump, a running agent keeps the old
duty line until some unrelated project input changes, which can be
days; the point of the duty line was that nobody has to tell each agent
by hand.

**Rejected alternatives:**
- Bump on every hub version: wakes every agent of every project on each
  deploy for text that usually did not change.
- No bump; the new text arrives with the next project input or a resume
  without cursor: leaves running agents on old instructions for an
  unknown time.
- Compare per agent at resume: the packet would need the text's digest
  per session, and an agent that never resumes again would never see it;
  a project-level bump reaches it through the event it already waits on.
- One digest for the whole instance instead of per project: a project
  created or bumped in between would be bumped again for nothing, and
  the once-only guarantee would need a lock of its own; the project lock
  already serialises the bump.
