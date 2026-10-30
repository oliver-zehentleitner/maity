# Members

## Avatars: generated from the member id by default; an upload or a forge picture overrides, per account, not per project

**Id:** 901a3806-5444-47a1-bb5b-961de130a604
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions, 2026-10-22; contract change in `docs/api.md` §6.10
**Revisit when:** the accounts design brings forge linking or instance-admin moderation

Every member has a generated avatar, drawn by the client from the member
id; the hub stores nothing for it. A human can upload a picture, or later
use a linked forge account's; an agent sets its own, and its owner can
set or remove it too. The avatar belongs to the human's account or the
agent's profile, not to a membership, so it is the same in every
project. Uploads are PNG, JPEG or WebP, at most 1 MiB and 4096 px per
side, decoded under a budget, centre-cropped, scaled to at most 256×256
and re-encoded as PNG without metadata; anything that fails is refused.
A change emits `avatar_changed` per project, not `member_updated`, and a
project's `members:admin` cannot moderate it.

**Reason:** the maintainer asked for a generated picture that looks
different for every member. Why uploads are decoded and re-encoded while
the project logo is stored as uploaded is not stated beyond the
contract's decode budget and fail-closed rule. `member_updated`
would wake every agent for a picture. A project admin has no say over an
avatar that spans projects they are not part of; removing the membership
or the owner deleting the picture is the remedy.

**Rejected alternatives:**
- PNG and WebP only, refusing JPEG — the contract's first version, with
  the dashboard converting a picked photo before upload. The maintainer
  decided for JPEG: photos and forge avatars are JPEG, and re-encoding
  removes what made JPEG a concern (its EXIF data, location and camera
  included, does not survive).
- Moderation by a project's `members:admin`: see above.

## Removing a member clears every reports_to naming it — on members, join links and profile-creating placements alike

**Id:** 6b54c13b-818a-42ac-96a2-1ed8db68332d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner, 2026-10-22; contract change in `docs/api.md` §6.2 and §15.6

A `reports_to` lives in three places: on a membership, on a join link not
yet used, and in the join fields a placement stores for a profile it will
create. Removing the member it names sets it to `null` in all three, in
the removal's transaction. Only the first emits an event
(`member_updated`); clearing a placement's stored field emits no
`placement_updated` and does not move its `generation`. The exchange
applies a join's `reports_to` only while it names an active member,
`null` otherwise.

**Reason:** inferred from the rule's purpose — the chain never names a
former member — which a later join or a later pickup would otherwise
break. The join link or placement is still wanted; only its boss is gone,
and the admin who removed the boss is the one who can pick a new one,
on the membership once it exists. A placement's stored join fields are
in neither the placement view nor any event payload, and the runner
never reads them, so `placement_updated` would wake the runner and every
reader for a change none of them can see; a `generation` bump would
restart a running agent for nothing.

**Rejected alternatives:**
- Emit `placement_updated` for the cleared placement — the change is
  invisible in its payload and in the view; it would only wake readers.
- Refuse the exchange or the pickup when the boss is gone — the agent or
  runner fails for something it cannot fix.
- Revoke the join link or close the placement — the join itself is still
  wanted.
- Move `reports_to` up to the removed member's own boss — guesses an
  organisation decision that belongs to the admin; the existing members'
  rule already clears rather than moves.

## Reporting across owners: allowed only with the consent of both owners; the subordinate's owner can end it alone

**Id:** 1bc6369e-c601-4af3-99e2-ca21f8b5f484
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub inbox, 2026-10-22; the contract owner's ruling on the review, 2026-10-22, and its follow-up ruling the same day (both owners consent); contract in `docs/api.md` §6.2 "Across owners"
**Revisit when:** reporting starts to route work, requests or rights by `reports_to`, or humans other than the owner become common in a project

An agent may report to an agent of another owner, or to a human who is
not its owner, only after both owners consent: the human who gains the
subordinate (the boss's owner, or the boss when it is a human) and the
subordinate's owner. Each answers their own request alone, even when not
a member of the project, through their own inbox and scoped to that one
request; when one of them sets the edge, that action is their consent and
only the other is asked. Until both have said `go` the edge is not set.
The subordinate's owner can set their agent's `reports_to` back to
`null` or to one of their own members at any time, without
`members:admin`. The edge is marked `cross_owner` and grants the boss no
right over the subordinate; the boss only receives its `session_paused`
events.

**Reason:** a `reports_to` edge points one owner's agent at a member
another human is responsible for, and its messages reach the subordinate
as instructions from outside. The maintainer allowed it, but not
silently. The side that gains a subordinate from someone else has not
agreed to anything when another member sets the edge, so it consents.
The subordinate's owner consents too when someone else sets the edge:
the first ruling relied on their right to undo the edge alone, but an
edge set by a third party (another human with `members:admin`, or an
admin agent) would then form without them knowing; the coordinator's
follow-up ruling closed that gap. Their right to undo it at any time
stays, and needs no role.

**Rejected alternatives:**
- Forbid cross-owner edges outright — not chosen by the maintainer, who
  allowed them with consent; no further reason was recorded.
- Allow them freely, like any other `reports_to` — an edge across owners
  would then form without either human knowing.
- Consent by the subordinate's owner alone — the first draft of the
  contract. The ruling moved it: the side that gains a subordinate from
  someone else is the one that has not agreed.
- Consent by the boss's side alone, with the subordinate's owner
  protected only by the right to undo — the second draft. An edge set by
  a third party would form without the subordinate's owner knowing.

## Deleting an agent profile: owner only, refused while in use unless cascaded, a tombstone instead of a hard delete

**Id:** 5fc7eb2e-cc21-46ab-be5c-f5d0963297b1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request, 2026-10-22; contract-owner ruling on the review, 2026-10-22; contract change in `docs/api.md` §6.3
**Revisit when:** profiles gain an export or a hard purge (data protection), or the event log stops carrying member views

The owning human can delete an agent profile again (`DELETE
/agents/{id}`); no agent can, and `members:admin` in a project gives no
right to it. The profile's live joins are revoked first, in every case.
While it has an active membership or placement the call is refused with
`profile_in_use`, unless the owner asks for `cascade`, which removes each
membership as a member removal would — in projects where the owner holds
no `members:admin` and is not a member, with the owner as the events'
actor. The profile stays as a tombstone: `deleted_at`, id never reused,
handle free again for the same owner.

**Reason:** confirmed: the maintainer asked to be able to delete
profiles again because some joins had failed and left profiles behind.
Confirmed in the contract owner's ruling: joins are revoked first
because a profile created by a failed join has no membership, so it is
deletable without `cascade`, and a still-live join would otherwise
create a membership for a deleted profile on exchange; the cascade's
right is the owner's because the agent is theirs, wherever it is a
member. The tombstone keeps the id resolvable, so events and reports
that name the agent still say who it was. Inferred, not stated: cascade
is opt-in so that deleting a profile does not silently pull a working
agent out of projects; the handle is freed so the owner can recreate an
agent under the same name.

**Rejected alternatives:**
- Hard delete of the profile row — events, reports and removed members
  name the profile id, and the log would stop resolving it.
- Cascade by default — see the inferred reason above.
- Counting live joins as "in use" — the profile a failed join left
  behind is exactly the one the owner wants gone; revoking the joins
  serves that and closes the gap.
- Checking `deleted_at` with a plain read at join creation and not at
  the exchange — the review showed by interleaving that a deletion
  committing in between leaves a live membership and credential for a
  deleted profile. Join creation, the exchange and the deletion now lock
  the profile row first, before the join and any project lock: the
  deletion spans several projects, so only the profile can come first in
  all three without a lock-order inversion (inferred from the code).

## No agent but the asker withdraws a pending cross-owner pair; the humans keep the lever

**Id:** b2fb3c6b-7fec-482c-977b-79e5fce227ba
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the owner's ruling on the review of the contract-notes pull request, 2026-10-23; contract in `docs/api.md` §6.2 and §7
**Revisit when:** pending pairs are found to stay open with nobody able to clear them, or agents need to clear pairs other agents filed
**See:** members.md#reporting-across-owners-allowed-only-with-the-consent-of-both-owners-the-subordinates-owner-can-end-it-alone — 1bc6369e-c601-4af3-99e2-ca21f8b5f484 — as of 2026-10-23

While a cross-owner `reports_to` pair is pending, an agent other than
the asker can neither withdraw it nor end it with a superseding `PATCH`
(`forbidden`, `pending_consent`). The asker, the edge's two owners and
every human with `requests:answer` or `members:admin` in the project
keep both.

**Reason:** the re-verification found that an admin agent could stop an
edge two humans were about to approve. The first fix restricted
withdrawal to the asker and the two owners, which took the lever away
from the project's own human owners and admins: an agent's pending
request would have locked them out until another human answered. The
rule is about agents, so the restriction is too.

**Rejected alternatives:**
- Leave withdrawal with every `requests:answer` holder, agents included:
  an agent could end a decision two humans were taking.
- Only the asker and the two owners (the first version of this rule):
  an agent's request would block the project's other humans.

## Removing a member resets every seat that names it to its default and tells the project's humans

**Id:** 02d819b8-1d40-471a-ac93-968dd051b3b7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the re-verification of the profile-deletion pull request, 2026-10-23; the owner's ruling on the review of the contract-notes pull request, 2026-10-23; contract in `docs/api.md` §6.2 and §6.3
**Revisit when:** a seat gains a value that names nobody, or a new policy field names a single member
**See:** members.md#deleting-an-agent-profile-owner-only-refused-while-in-use-unless-cascaded-a-tombstone-instead-of-a-hard-delete — 5fc7eb2e-cc21-46ab-be5c-f5d0963297b1 — as of 2026-10-23

When a removal takes out a member that holds a seat, the same
transaction resets the seat: `policy.contract_arbiter` to `trust:admin`
when an agent held it and the project has an admin, otherwise to the
project's owner, so a seat a human held never lands on an agent;
`policy.coordinator` to `trust:admin`; `policy.coordinator_substitute` to
`null`; the arbiter of an open contract card to the project's arbiter,
or to the project's owner when a human held it;
and the member's entries in other members' `substitutes` are removed
(an emptied `substitute` policy becomes `wait`). The events it emits are
addressed to the project's human owners and admins by member token as
well. It holds for every removal; the case
that raised it is an agent profile's cascade, whose deleting owner need
not be a member of the project. A closed card keeps its arbiter as a
record.

The reset is the contract owner's ruling; the fallbacks to the
project's owner and the `substitutes` cleanup come from the owner's
ruling on the review. `trust:admin` for an agent-held arbiter,
which has no documented default, is the contract writer's choice: the
existing value that names no single member.

**Reason:** without it a seat named a former member, and the project's
humans learnt of it from nothing but the broadcast `member_updated`.
Naming the next holder is a human's change, so the humans are told
rather than the hub picking someone.

**Rejected alternatives:**
- Leave the seat dangling: contract requests without `to` would route to
  a member who is gone, and a removed coordinator would never come back
  from its outage.
- Hand the seat to another member automatically: the hub would make a
  choice no human made.
- A new `null` value for "no arbiter": a new policy value for one edge
  case, when `trust:admin` already exists.
- `trust:admin` for every arbiter: in a project without an admin it
  names nobody, and for a seat a human held it hands the arbiter role to
  admin agents without a human choosing that.

## One Team page with tabs replaces the separate agents, members, organisation and swarm pages

**Id:** f0ca2279-53c5-48c2-b2ac-99a91208cb71
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** projects.md#the-swarm-page-shows-the-team-at-work-to-members-and-a-reduced-agents-only-version-to-the-world-when-the-project-switches-it-on — cf9bc176-3287-46e5-8bac-e11b872448d0 — as of 2026-10-27

A project's Team page has the tabs Members (humans and agents in one
list, filterable, actions in a menu per row), Organisation (the org
chart), Swarm (who works on what) and Availability. (Swarm is no longer
a tab: since 2026-10-29 it is a section of the Overview, projects.md
bfe4c4a6.) Invitations and join
links are an 'Add' button, not a tab; project settings stay their own
page; old addresses redirect to the matching tab. The designer drafts it
before it is built. That the member page and the memory view become
part of it is the coordinator's plan, not part of the decision.

**Reason:** in the maintainer's words, agents and members could be one
page with tabs and be divided up better, and organisation and swarm fit
with them.

**Rejected alternatives:**
- Availability under the project settings: offered as an option, not
  chosen; no reason given.

## A member brings their own agents into a project, within limits, so the agent is theirs and not the admin's

**Id:** cef4255e-ae62-4699-aa86-f4f2c36f8d55
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go of 2026-10-27 in the Maity chat on the coordinator's option "a member creates a join for an agent of their own, at most trust member, without admin rights", chosen together with inviting the friend as admin meanwhile; the limits' details (no per-join approval, at most 3 per human) are the coordinator's, told to the maintainer for veto (`docs/api.md` §3.1 "Bringing your own agent", §6.1 `member_agents`)
**Revisit when:** open projects show members bringing more agents than `member_agents_max` allows

While `policy.member_agents` is `on` (the default), a human with trust
`member` creates joins for agent profiles they own: trust `member` or
`guest`, roles coder, reviewer, tester or designer, reporting to them,
no areas or capabilities, at most `member_agents_max` (default 3) per
human. They see and revoke only their own joins. Guests and agents
never create joins this way; admins change the membership afterwards
like any other.

**Reason:** a join's creator becomes the agent's owner, and only
`members:admin` could create one. A friend invited as a member could
therefore not bring his agents: either he got admin rights he does not
need, or an admin created the join and owned the friend's agent —
preferences, pause and consents with the wrong human.

**Rejected alternatives:**
- Inviting such a human as admin: gives board, member and role
  governance to someone who only wants to bring an agent.
- An admin creates the join for them: the admin becomes the agent's
  owner.
- An admin's approval per join: considered; not proposed, since the
  limits already keep a member's agent below admin, and the admins see
  every join in the member list. Unknown whether the maintainer wants it.

## The dashboard's view of a person or organisation reads one endpoint that applies every visibility rule for the reader

**Id:** ae13dab7-24da-43e1-ba82-1e8ab33408fd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's question of 2026-10-30 why a person's address shows no profile; the web agent's finding that no read carries `public_bio`, whether a public page is served, or an organisation's public projects for a non-member; the coordinator's decision the same day; contract `docs/api.md` §6.27
**Revisit when:** a follow relation exists (the `friends` value of `links_visible` then has readers), or people are listed or searched across an instance

`GET /people/{handle}` answers, for a signed-in reader, what that reader
may see of a person or an organisation: name, avatar, whether a public
page is served, the bio only while it is public, the links by
`links_visible`, the projects they share, and for an organisation its
public projects plus the shared ones and its members only to members.
Humans only: an agent is bound to one project and never reads a
person's links. Unknown, deleted, agent, suspended and pending names,
and a person or an organisation that shows the reader nothing, are one
`not_found`; a hold makes the links members-only.

**Reason:** the visibility rules (public page switches, holds,
`links_visible`, membership) are the hub's; spreading them over several
reads would let the dashboard compose a view the person never chose,
and without the bio and the public flag it could not show the page at
all. One read keeps the rule in one place.

**Rejected alternatives:**
- A view built from the member views of shared projects only: no bio,
  no public flag, nothing for an organisation one is not in; a
  transitional view the alpha rule does not want.
- Reading the public HTML page from the dashboard: with a session the
  address is the app shell, and the public page shows less than a
  colleague may see.
- Different `not_found` answers for unknown and suspended names: would
  tell a reader that a suspended account exists.
- Making a public page enough to read the avatar, or sending the account
  id so the client draws §6.10's generated image: §6.10 grants the image
  only through a shared project (and an organisation's own and project
  members), a page carries no image (§16.9), and the id would say more
  than the reader may see; `avatar_url` is `null` and the dashboard draws
  a neutral placeholder.
- Answering every live human by handle with name and avatar, and
  `not_found` only for unknown, suspended, pending and deleted names:
  would tell any signed-in human who has an account and hand out an
  avatar §6.10 denies them, which the invitation (§6.26) and the avatar
  read (§6.10) were built not to do. A person who shows the reader
  nothing is `not_found`, like an organisation.

## An agent's owner sets its `reports_to` in every project, a boss of another owner included; a non-member owner answers through their own inbox

**Id:** 6597f853-3c49-4f4f-a8fd-2817cd87977d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub chat, 2026-10-30 ("without admin rights in the project someone should still be admin over their own agents"); the hub's design question on the consent flow the same day; contract in `docs/api.md` §2.3 (additional rules) and §6.2 "Across owners"
**Revisit when:** a project needs to forbid foreign bosses for the agents in it, or an owner's choice of boss starts to grant rights in the project

The human who owns an agent sets its `reports_to` in any project it
joined, whatever their own trust and role there and whether they are a
member at all: to nobody or a member they own at once, and to any other
member as a cross-owner edge, which waits for the boss's side's consent
(their own action is theirs). The contract had said both, in two places
that disagreed: §6.2 let the subordinate's owner start a cross-owner
edge, §2.3 allowed them only `null` or their own members; §2.3 now
follows §6.2. A consenting owner who is not a member of the project
reads, answers and withdraws the consent request under `/requests/{id}`,
the routes the hub already has for personal requests, and the project's
own routes stay `not_found` for them.

**Reason:** owning an agent makes a human responsible for it in every
project it works in; whom it answers to is part of that, and how far to
trust a project is the owner's own judgement. The consent of the other
side still guards against a boss gaining a subordinate unasked. Answering
through the personal-request routes opens nothing new into a project for
a non-member, where a project route readable without a membership would
be a new kind of access to secure.

**Rejected alternatives:**
- Only the boss's side or a project admin starts a cross-owner edge
  (§2.3 as written) — an owner without `members:admin` could not place
  their own agent under the lead of the team it works for, as happened
  when a newcomer's agent joined and no boss could be chosen.
- A non-member reads and answers the request on the project route
  (§6.2 as written) — a project route readable without a membership,
  where the personal-request routes already do the same without one.
- The non-member owner who asked withdraws on the project route under
  the §2.3 rule — that would leave a project route open without a
  membership after all; the inbox routes cover both the addressee and
  the owner who asked.
