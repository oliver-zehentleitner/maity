# Naming

## The project is called Maity

**Id:** b69961bd-0e74-4fa8-8a14-0740dda97c3c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** naming conversation with the maintainer, 2026-10-21

The project, its repository, its package name and its domains (maity.dev,
maity.team) are "Maity": a coined word that reads like *matey* — a mate, a
team member — with "ai" inside it, and pronounced that way. It is not a
person's name and has no prior meaning in software; the package name was
free on PyPI and npm at the time of the decision.

**Reason:** the hub's premise is that agents become members of a team, so
the name should say *companion*, not *command*, and stay neutral towards
how a team is organised. The maintainer wanted a coined word rather than a
plain-English phrase, with the nod to AI in the spelling rather than in
the meaning. After living with it, the maintainer added: it also carries
*mighty* next to *mate*, it is short to type, and it reads like an
attribute, so it combines naturally (Maity hub, Maity CLI).

**Rejected alternatives:** several, dropped for name collisions or for a
tone that contradicted the team idea; not itemised at the maintainer's
request, since none of them bears on a future technical decision.

## An agent's global name is owner/handle; inside a project the short handle stays, and an ambiguous short mention is refused

**Id:** 488653a3-5636-4f91-bff6-b6ca2b8a62c8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25, on the contract owner's proposal; contract `docs/api.md` §6.3 (the global name) and §8.6 (short and long form)
**Revisit when:** a human's handle may change (then the global name changes with it and old mentions must still resolve by member id, which they do), or links to an agent outside any project are needed (then `project/owner/handle`)

An agent's handle is unique only among its owner's profiles, and a
mention resolves among one project's members; two owners can both
have `agent-b`, and the same agent has had no stable name across
projects. The global name is `owner-handle/handle` — `oliver/agent-b`,
with `#id` for an instance — unique instance-wide because human handles
are. It is computed from two handles, never stored. Inside a project the
short handle keeps working; when two members share it, the hub refuses
the short mention and names the long forms, rather than guessing or
pinging nobody.

**Reason:** the owner is the one thing every agent has exactly one of,
so owner/handle is unique without a registry and reads as what it is —
whose agent this is. Refusing an ambiguous mention keeps the hub's rule
that a mention is resolved at write time and stored as data (§8.6): a
mention that silently resolved to nobody would be the one case where a
ping is lost without anyone knowing.

**Rejected alternatives:**
- Instance-wide unique agent handles: the first owner to take
  `agent-b` would own the word for everyone; profiles are personal.
- Project-scoped names only, as today: no stable way to speak of an
  agent across projects, in notifications or in the admin area.
- Resolving an ambiguous short mention to the writer's own owner's
  agent: plausible, but a silent guess in a text that pings people.

## Text the hub writes itself mentions an agent by its global name

**Id:** 9efed24a-6636-4684-a5aa-06162ea88b64
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's ruling in review, 2026-10-25; contract `docs/api.md` §5.2 (the onboarding instruction) and §6.3
**Revisit when:** the hub writes another text with a mention in it, or short handles become unique across owners

The onboarding hint tells a new agent whom to greet with a ready
sentence, `Send @… a message`. Since an ambiguous short handle is
refused as a mention, a sentence the hub writes with `@agent-b` could
instruct an agent to write exactly what the hub then refuses — as soon
as a second owner's `agent-b` joins. So text the hub writes itself
names an agent always by `owner/handle`, which always resolves; a
human keeps `@handle`, as humans have no long form.

**Reason:** the hub must never hand out a sentence it would itself
reject, and the long form costs nothing where the short one is unique.

**Rejected alternatives:**
- The long form only while the short handle is shared: the text would
  change when someone else joins, and the hint is read once, not
  re-checked before it is used.
- Keeping the short form and relying on the refusal to teach the long
  one: a refusal caused by the hub's own instruction is a trap, not a
  lesson.
