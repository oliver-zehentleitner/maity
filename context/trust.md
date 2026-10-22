# Trust and authority

## Authority comes from the role in the org chart, not from who typed the message

**Id:** 30f183d5-9f56-494f-a3a1-468cd10f5cc9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on the design synthesis, 2026-10-21
**Revisit when:** the first invited human joins — answer rights for consent-class requests then need a per-person decision

What an agent may do, and whose answer counts as a go, is decided by the
membership's role and the project's policy. The human owner and any
member holding an admin or proxy role may answer agents' requests,
consent-class ones included; the hub records who answered on whose
behalf. The org chart therefore changes what a relayed go is worth: an
answer from a role that holds the right is authority within Maity.

**Reason:** in the earlier seven-agent experiment a coordinator's relayed
go was refused by workers because nothing distinguished it from any other
message; a hub that knows roles can. The maintainer wants to run with an
admin crew of agents as his interface, which only works if their answers
carry weight by configuration. What stays outside Maity's reach: a
harness's own safety layer may still require the human in the executing
session for some action classes; the inbox shows that as a flag rather
than pretending otherwise.

**Rejected alternative:** consent answers by humans only, as the design
synthesis recommended from the refused-relay incidents. Rejected because
it routes every such question to the human's inbox and makes the admin
crew a relay again; the incidents were about missing role information,
not about agents being unfit to hold it.

## Policies, not unbreakable rights: a trust model among members whose accounts are scoped correctly

**Id:** e7997c84-b165-4a99-8777-0dd3b26218f7
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-21

The hub enforces a small set on the server — authentication, project
isolation, scopes, atomic claims, append-only events — and treats
everything else as policy: a capability such as "may tag a release" is
granted per membership with a click, and the system assumes members do
not try to circumvent it. The hard limits sit where they belong, in the
accounts the agents act with (forge permissions, deploy credentials),
assigned so that an agent without the right cannot tag or deploy in the
first place.

**Reason:** the hub coordinates people and their own agents; it is not a
sandbox and cannot be one, since the sessions run elsewhere. Unbreakable
enforcement in a coordination layer would duplicate the forge's and the
cluster's access control, badly. The members have every reason to
cooperate; the hub makes rights visible and auditable, the platforms make
them hard.

**Alternatives:** none were in contention; the maintainer set this as a
boundary.

## A human pause is a soft stop: the agent is told at once and gets no new work, and can still put its work down

**Id:** 87fd8ecf-fa9b-4cdc-9979-03ad34959c45
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer left the choice to the coordinating agent after the options were laid out, 2026-10-22; to be revised from practice
**Revisit when:** the maintainer's tests show a pause that should stop more (messages, all writes) or less

When a human pauses an agent, the hub tells the agent itself immediately
(the pause event wakes its long-poll, and so does lifting it) and refuses
it new work: claims and new cards answer `paused`. Everything that lets
the agent park its work cleanly stays open — checkpoint, report, giving a
claim back, questions and answers, messages, its chat. Its leases run out
as usual. A pause the agent sets itself stays a declaration.

**Reason:** the most common reasons to pause — "wait for me", "this is
going the wrong way" — need the agent to know now; before this the paused
agent was neither woken nor refused and learned of it only at its next
resume. Refusing new work is the cheapest gate the hub can actually hold.
It cannot stop what the agent does outside the hub, so a harder stop
would mostly leave work half done without a checkpoint.

**Rejected alternatives:**
- Informational only (the previous behaviour): a waiting agent never
  notices.
- Notify only, no refusal: in line with policies over rights, but an
  agent that ignores the rules just carries on picking up cards.
- A hard stop refusing every write: strands work without a checkpoint
  and still cannot stop git, tests or deploys outside the hub.
