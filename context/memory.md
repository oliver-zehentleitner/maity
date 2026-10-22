# Memory

## Agents get a soul, a team memory and a community memory in the hub, quoted with provenance and never obeyed as instructions

**Id:** ab1f3744-459d-4ff1-9e4f-7fe306133d7a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-22 ("soul, team memory, community memories"); contract in `docs/api.md` §17
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
owner and `members:admin`. Memory reaches the agent quoted with who
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

**Alternatives:** unknown — the maintainer approved the design without
naming options he had rejected.
