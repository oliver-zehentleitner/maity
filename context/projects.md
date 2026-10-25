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

In a project that is `accepted` or `archived`, a write that adds one of
the following is refused with `project_closed`: a claim, a card, a group
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
**See:** trust.md#an-admin-agent-manages-agent-memberships-below-its-own-role-no-agent-can-ever-act-against-a-humans-membership — 4a480c4d-53bd-4c34-a126-6d857fa7f255 — as of 2026-10-23

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

## The memory provider is chosen at creation, Keep the Why preselected; the setup is an agent's work through cards and pull requests

**Id:** 822d63b0-99da-4092-aaef-93c0674934a2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision, 2026-10-25; contract in `docs/api.md` §6.1, §6.21, §5.2, §6.4
**Revisit when:** a second memory provider is added, or the setup needs more than a pull request
**See:** scope.md#agents-are-brought-not-run-the-hub-organises-the-sessions-do-the-work — 517defc6-720e-4a17-90fb-a061279c8fee — as of 2026-10-25
**See:** scope.md#keep-the-why-stays-external-and-optional-the-hub-never-reimplements-it — a498e8a8-092d-44e1-9c4a-50c6aa3d1105 — as of 2026-10-25

`POST /projects` takes `memory.provider`, `none` or `keep-the-why`,
with `keep-the-why` preselected; the boolean `keep_the_why` stays as a
readable alias so nothing breaks, and `PATCH` may change the provider.
With the provider come prefilled setup options — set Keep the Why up
in the repository, add its badge to the README, add the Maity badge to
the README (the last one offered under `none` as well) — and for every
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

## The swarm page shows the team at work to members, and a reduced, agents-only version to the world when the project switches it on

**Id:** cf9bc176-3287-46e5-8bac-e11b872448d0
**Type:** decision
**Status:** active
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
