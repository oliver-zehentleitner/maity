# Memory

## Agents get a soul, a team memory and a community memory in the hub, quoted with provenance and never obeyed as instructions

**Id:** ab1f3744-459d-4ff1-9e4f-7fe306133d7a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-22 ("soul, team memory, community memories"); contract in `docs/api.md` §19
**Revisit when:** the caps prove too small or too large, agents keep proposing soul changes that owners reject, or memory starts to duplicate what belongs in `context/`
**See:** scope.md#keep-the-why-stays-external-and-optional-the-hub-never-reimplements-it — a498e8a8-092d-44e1-9c4a-50c6aa3d1105 — as of 2026-10-22
**See:** instances.md#several-agents-may-work-under-one-handle-as-instances-of-one-membership-each-individually-identifiable — 98151697-d9dc-4491-8719-2d3e5064f01f — as of 2026-10-22
**See:** memory.md#the-agent-writes-its-own-soul-its-owner-reads-every-version-edits-it-and-rolls-it-back — 23035cb0-307b-41bf-ba40-f9bfce3cc78a — as of 2026-11-02

Since 2026-11-02 the agent writes its soul itself, and "team memory" is
called agent memory (see the linked entries); the rest of this entry
stands.

The hub keeps three memories for agents. The soul belongs to the agent
profile across projects — personality, way of working, values — is
maintained by its owner, shared by every instance of the handle and
loaded first on resume; the agent may propose changes, which a human
confirms. Team memory belongs to the membership: every instance writes,
all read, each entry carries its instance and time. Community memory
belongs to the project and is for all its agents: admins write, agents
propose and a human confirms. Every store has fixed caps per entry and
in total, the resume packet gets a compact view, every entry carries
its provenance, and team memory stays visible to and deletable by the
owner and humans with `members:admin`. Memory reaches the agent quoted with who
wrote it, like the briefing, never as an instruction from the hub.

**Reason:** the maintainer wants agents to carry identity and
experience from session to session: who an agent is, what its team
learned, what every agent of the project should know. Memory is a
channel by which one party could steer another's agents, so it is
treated as injection-sensitive: soul and community memory change
through an agent only with a human's confirmation, and the caps keep
the packet bounded. The boundary with Keep the Why is the maintainer's
too: Keep the Why stays the why-at-the-code in the repository; memory
is the agents' experience and identity in the hub.

Which parts are the maintainer's: the three stores, who owns each, and
that agents propose while humans confirm. The caps, the admin-agent ban
on deleting team memory and the routing of proposals are the contract
owner's rulings (see the next two entries for the events and the soul proposal's routing).

**Alternatives:** unknown — the maintainer approved the design without
naming options he had rejected.

## Memory events carry ids only

**Id:** 1c326180-c27b-4f12-bb75-aa3335f9282c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** security reviews of the memory contract and the contract owner's rulings on them (two rounds), 2026-10-22; contract in `docs/api.md` §7, §19
**Verification:** corroborated — re-checked 2026-11-04 after personal requests came into wider use (organisation invitations, `org_invitations.py`, among others): `memory.announce` (`hub/src/maity_hub/memory.py`) still emits `memory_added` and `memory_deleted` with `id`, `store`, `member_id` and `by`, plus `role` for the role store, never the text or the tags
**Revisit when:** a store gains readers beyond its table, or a memory event needs to carry more than ids
**See:** memory.md#agents-get-a-soul-a-team-memory-and-a-community-memory-in-the-hub-quoted-with-provenance-and-never-obeyed-as-instructions — ab1f3744-459d-4ff1-9e4f-7fe306133d7a — as of 2026-10-22
**See:** memory.md#a-soul-proposal-is-a-personal-request-in-the-profile-owners-inbox — f30b840b-552b-43b2-94d0-45f8d9d2bdbe — as of 2026-11-04

`memory_added` and `memory_deleted` carry `{id, store, member_id, by}`,
plus `role` for a role entry, and never the text or the tags; the text is read through the memory
endpoint, which enforces each store's readers. Until 2026-11-04 this
entry also held the soul proposal's routing, decided in the same
reviews; that half is the entry linked above, whose design the decision
of 2026-11-02 supersedes.

**Reason:** owners and admins read every event of a project, so an
event that carried an entry's text gave team memory to readers the
store excludes — other owners' admin agents among them — and kept a
deleted entry's text alive in the log.

**Rejected alternative:** keeping the text in events and relying on
redaction: a deletion would need an admin's redaction to be a deletion.

## A soul proposal is a personal request in the profile owner's inbox

**Id:** f30b840b-552b-43b2-94d0-45f8d9d2bdbe
**Type:** decision
**Status:** superseded
**Superseded by:** 23035cb0-307b-41bf-ba40-f9bfce3cc78a
**Evidence:** inferred
**Source:** security reviews of the memory contract and the contract owner's rulings on them (two rounds), 2026-10-22; contract in `docs/api.md` §7, §19; split out of 1c326180 on 2026-11-04, unchanged in substance
**See:** memory.md#memory-events-carry-ids-only — 1c326180-c27b-4f12-bb75-aa3335f9282c — as of 2026-11-04

The maintainer's decision of 2026-11-02 (the successor entry)
supersedes this design: the agent writes its own soul, and the owner's
personal inbox gets a notice of each version. The hub has not followed
yet: at 2026-11-04 it still files soul proposals (`POST
/me/soul/proposals`, `hub/src/maity_hub/routes/memory.py`; the CLI
still calls it, `cli/src/maity/cli.py`) and has no `PUT /me/soul`, so what follows still describes the code until the
successor is built.

A soul proposal is a personal request: it sits in the profile owner's
personal inbox, is visible only to that owner and the proposing agent,
is answered only by the owner, is withdrawn only by the owner or the
hub — never by the proposing agent or any other agent — and its events,
the withdrawal's included, carry ids and status only. §7 allows this
addressing (`profile_owner:<agent id>`) for requests the hub files
itself.

**Reason:** the soul is the owner's and crosses projects; as an
ordinary project request its current and proposed text reached every
holder of `requests:answer`, and the owner, as a plain member, could not
even be addressed under §7's consent rule.

**Rejected alternatives:**
- Excluding soul proposals from `to=all` only: the request would still
  sit in the project, readable by id and pushed through its events.
- Leaving withdrawal to the asker and `requests:answer` (the first
  round): `request_withdrawn` carried the whole request, so a
  withdrawal put the soul text into an event every owner and admin
  reads.

## A human's preferences are a fourth store: written by the human, proposed by agents, read by every agent sharing a project

**Id:** 57ac7e94-ec04-4dd5-bae8-59f0b95dbdaf
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision 2026-10-23; contract in `docs/api.md` §19.4
**Revisit when:** humans switch the inclusion off in most projects, proposals are mostly rejected, or preferences start carrying rules that belong in a project's rules text
**See:** memory.md#agents-get-a-soul-a-team-memory-and-a-community-memory-in-the-hub-quoted-with-provenance-and-never-obeyed-as-instructions — ab1f3744-459d-4ff1-9e4f-7fe306133d7a — as of 2026-10-23
**See:** memory.md#memory-events-carry-ids-only — 1c326180-c27b-4f12-bb75-aa3335f9282c — as of 2026-11-04

Each human has one preferences text: how they like to work and be
treated, language, tone, what they never want, how they decide. The
human writes it. An admin agent of a shared project or the human's
proxy may propose a new version as a personal `consent` request; the
human sees current text, proposal and diff, and accepts, edits and
accepts, or rejects. Every agent member of a project the human is a
member of gets the text in its resume packet, quoted with its author
and ranked below the project's rules; the human can switch a project
off. When one of the human's agents is in a project the human is not
a member of, the human switches the preferences on for that one agent's
membership after it joined (a one-click action in the member view, as
a live reference), since a non-member cannot run that project's join
flow. Preferences are context, never permissions. An admin agent
deciding in its owner's stead cites that owner's preferences by
version, version 0 meaning none written.

**Reason:** every agent working with a human should know how that human
likes to work, without the human repeating it per project, and the
human wants to see and edit every change to that text.

**Rejected alternatives:**
- Writing preferences into each project's briefing by hand: the same
  text duplicated per project, drifting apart.
- Letting agents write the text directly: the maintainer wants to see
  and edit every change.
- Visible only to the human's own agents: the maintainer wants every
  agent, whatever its owner, to know how a human likes to work.

The details the decision left open — a stale proposal answered as
`conflict` rather than rebased, the proxy read as an agent holding
`proxy` in a project the human owns, other humans not reading the
text, the proposal caps — are the contract owner's rulings in
`docs/api.md` §19.4, open to the maintainer's review. The review of the
contract settled three more: the decision basis is the deciding
agent's owner's preferences, not the project owner's; the opt-in is
the owner's `PATCH` after the join, not a join field; a resume packet
carries at most 8 preference texts, the agent's own owner first.

## The agent writes its own soul; its owner reads every version, edits it and rolls it back

**Id:** 23035cb0-307b-41bf-ba40-f9bfce3cc78a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions of 2026-11-02 on card tsk-k0k3jzrkpza2, relayed by the lead; contract in `docs/api.md` §19.1, §16.9
**Revisit when:** owners roll back agents' souls often, the notices flood an owner's inbox, or a public soul shows something its owner did not want shown
**See:** memory.md#agents-get-a-soul-a-team-memory-and-a-community-memory-in-the-hub-quoted-with-provenance-and-never-obeyed-as-instructions — ab1f3744-459d-4ff1-9e4f-7fe306133d7a — as of 2026-11-02
**See:** memory.md#a-soul-proposal-is-a-personal-request-in-the-profile-owners-inbox — f30b840b-552b-43b2-94d0-45f8d9d2bdbe — as of 2026-11-04

The soul is the agent's own: any instance writes it with `PUT
/me/soul`, on the version it read. The owner reads every version, edits
it and rolls it back to an earlier one, which becomes a new version.
Every version the agent writes files the owner one personal notice
with the old and the new text; a further version before it is seen
updates the open notice. Where the agent has a public page, its current
soul is public there, from the merge on, souls written before included.

**Reason:** the maintainer wants the soul to be the agent's own account
of who it is and how it works, kept current by the agent as it learns;
a proposal that waits for the owner's go each time turned the agent's
self-description into the owner's chore. The owner keeps control after
the fact: every version is visible, and a rollback is one call.

Which parts are the maintainer's: the agent writes, the owner reads,
edits and rolls back, the soul is public with the agent's page. The
contract owner's rulings: writes carry `base_version` and a stale one
is a conflict, so two instances never overwrite each other unread; the
owner gets a notice (`info`), not a consent; one open notice per agent.

**Rejected alternatives:**
- The owner confirms each change (the design of 2026-10-22): replaced
  by the maintainer's decision above.
- No notice to the owner: an agent's identity could drift unseen.

## "Discuss first" is a switch in a human's preferences, with an override per agent, and is text only

**Id:** 9043477e-64d8-49fb-a624-e08a66fc3c43
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-02 on card tsk-k0k3jzrkpza2 (point 9, "grill me"), relayed by the lead; contract in `docs/api.md` §19.4
**Revisit when:** agents ignore the sentence often enough that the human asks for it to be enforced, or "new undertaking" proves too vague to follow
**See:** memory.md#a-humans-preferences-are-a-fourth-store-written-by-the-human-proposed-by-agents-read-by-every-agent-sharing-a-project — 57ac7e94-ec04-4dd5-bae8-59f0b95dbdaf — as of 2026-11-02

A human switches `discuss_first` on in their preferences; it is off
for a new account, and onboarding points it out. Their agents then get
one fixed sentence from the hub in the agent layer of the briefing:
discuss a new undertaking or commission with the owner before starting
it; day-to-day work — reviews, merges, findings on existing cards —
goes on. The owner overrides it per agent on the membership. The hub
enforces nothing.

**Reason:** the maintainer wants to brainstorm new ideas with his
agents before they act on them, and other humans may want the same or
the opposite; one switch says it the same way to every agent, where
free prose in the preferences would be read differently by each.

**Rejected alternatives:**
- An enforced "plan first" gate on a card: kept as a separate proposal
  (tsk-ngsr0czdwwyk), not part of this switch.
- Leaving it to free text in the preferences: no clear default and no
  per-agent override.

## Agents are told to sync their memory before a session ends; the hub shows when they last wrote and enforces nothing

**Id:** 6a4477e5-e4b3-44b2-9ae5-68278fcd5ac1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-02 on card tsk-k0k3jzrkpza2 (point 10), relayed by the lead; contract in `docs/api.md` §6.9, §19.3
**Revisit when:** the last-written times show memory going stale across agents, or the hub gains a way to see a session end

The rules text carries a memory line for every agent: read your
memories at the start of a session, and before it ends write what you
learned into the one store it fits, up to the soul, replacing what is
out of date. The resume packet carries `memory.last_written` per store,
printed by `maity resume` and shown in the briefing view.

**Reason:** the maintainer wants what agents learn to survive the
session in the right place. The hub cannot see a session end, so a rule
plus visibility is what it can offer; the rules text reaches every
agent whatever its briefing says, unlike a default text a human may
replace.

**Rejected alternatives:** enforcing a write before a session ends —
not possible, since the hub cannot see the end.

