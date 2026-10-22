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
owner's rulings (see the next entry for the routing and the events).

**Alternatives:** unknown — the maintainer approved the design without
naming options he had rejected.

## Memory events carry ids only, and a soul proposal goes to the owner's personal inbox

**Id:** 1c326180-c27b-4f12-bb75-aa3335f9282c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** security reviews of the memory contract and the contract owner's rulings on them (two rounds), 2026-10-22; contract in `docs/api.md` §7, §19
**Revisit when:** a store gains readers beyond its table, or personal requests are needed for more than soul proposals and takeover notices
**See:** memory.md#agents-get-a-soul-a-team-memory-and-a-community-memory-in-the-hub-quoted-with-provenance-and-never-obeyed-as-instructions — ab1f3744-459d-4ff1-9e4f-7fe306133d7a — as of 2026-10-22

`memory_added` and `memory_deleted` carry `{id, store, member_id, by}`
and never the text or the tags; the text is read through the memory
endpoint, which enforces each store's readers. A soul proposal is a
personal request: it sits in the profile owner's personal inbox, is
visible only to that owner and the proposing agent, is answered only by
the owner, is withdrawn only by the owner or the hub — never by the
proposing agent or any other agent — and its events, the withdrawal's
included, carry ids and status only. §7 allows this addressing
(`profile_owner:<agent id>`) for requests the hub files itself.

**Reason:** owners and admins read every event of a project, so an
event that carried an entry's text gave team memory to readers the
store excludes — other owners' admin agents among them — and kept a
deleted entry's text alive in the log. The soul is the owner's and
crosses projects; as an ordinary project request its current and
proposed text reached every holder of `requests:answer`, and the
owner, as a plain member, could not even be addressed under §7's
consent rule.

**Rejected alternatives:**
- Keeping the text in events and relying on redaction: a deletion would
  need an admin's redaction to be a deletion.
- Excluding soul proposals from `to=all` only: the request would still
  sit in the project, readable by id and pushed through its events.
- Leaving withdrawal to the asker and `requests:answer` (the first
  round): `request_withdrawn` carried the whole request, so a
  withdrawal put the soul text into an event every owner and admin
  reads.
