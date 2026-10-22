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

## `reports_to` forms a tree; removing a member clears it on everyone who reported to them

**Id:** b242eda7-abc7-489f-af49-d7b7d7bf37c5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract change in `docs/api.md` §6.2, 2026-10-22, for the maintainer's need to re-hang members in the organisation chart; the check moved to the PATCH alone in the hub's follow-up (`docs/api.md` §6.2), re-confirmed by the coordinator, 2026-10-22
**Revisit when:** a member has to report to more than one member, or the organisation needs a relation a tree cannot express
**See:** https://github.com/oliver-zehentleitner/maity — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-10-22

A `reports_to` that names the member itself, or a member that already
reports up to it, is `invalid` (`details.fields.reports_to: "cycle"`),
checked on the PATCH against the project's current members. A join adds no
edge to the chain: a join for an agent that is already a member must name
its current `reports_to` (anything else is `differs_from_membership`), and
nobody reports to a new agent yet, so a join has no cycle to check. Removing a member sets `reports_to` to `null`
on everyone who reported to them, with a `member_updated` event for each.

**Reason:** the maintainer re-hangs members in the organisation chart,
and the dashboard got an edit dialog for it; until then the hub accepted
any `reports_to`, cycles included. The contract states the aim of the
removal rule — the chain never names a former member; why a cycle is
refused beyond that is not written down (an organisation view drawn from
the chain could not place a member inside one).

**Alternatives:** unknown — for the removal in particular, whether
re-hanging the reports onto the removed member's own `reports_to` was
considered is not recorded.

## An admin agent manages agent memberships below its own role; no agent can ever act against a human's membership

**Id:** 4a480c4d-53bd-4c34-a126-6d857fa7f255
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer in the inbox, 2026-10-22, narrowed after review; contract change in `docs/api.md` §2.3
**Revisit when:** a second human joins with an admin role, or an agent needs a membership right the table does not give it
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

An agent with `admin` may change agent memberships with role `member` or
`reviewer`, never its own: `reports_to`, `areas`, `briefing`, `paused`,
and the role between `member` and `reviewer`. It cannot grant or remove
`proxy`, set capabilities, or create, list or revoke joins. Removing an
agent member, or changing the role of or pausing the reviewer or the
contract arbiter, becomes a human-only consent request and applies on
the human's go. On top, for every agent whatever its role: no reducing,
removing or pausing a human's membership, no revoking a human's
sessions or credentials, no change to instance-admin status, human
accounts or ownership, no archiving or deleting a project, no change to
the human-decision policy fields or the rules text — each `forbidden`
with `humans_only`, enforced as one table in the hub's tests. A briefing
records who set it and its version; the owner can read past versions.

**Reason:** the maintainer wants the admin agent to change members,
above all when the maintainer asks for it, and set one limit: no agent
may ever be able to harm the human — taking away the human's admin
rights was the example given. Why removals and changes to the reviewer
and the arbiter in particular need a human's go is not recorded.

**Rejected alternatives:**
- The full `members:admin` scope for the admin agent, as first asked:
  narrowed in review to agent memberships below its own role.
- Dropping `members:admin` from the hub's human-only list wholesale:
  every other use of the scope (runners, placements, enrollments, the
  owner and credential fields, the start-consent policy) stays human-only.

## Members sharing an environment are warned, never refused

**Id:** abd84bd0-a085-4d5a-b3b0-f8358c12e444
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-22; contract change in `docs/api.md` §5.2, §5.3 and §8.2
**Revisit when:** a shared environment leads to an incident the warning did not prevent, or declared ids turn out to be spoofed in practice
**See:** process.md#reviewer-independence-assumes-separate-environments-two-identities-in-one-workspace-mixed-up-credentials — 5380a247-324f-4ab8-92c6-37350e02b0cb — as of 2026-10-22

On resume a client may declare `environment: {home, workspace}`: two
ids derived per hub from a random secret the client keeps in the OS
user's home and in the state directory (an HMAC of the hub's URL, so the
same place gives unrelated ids on two hubs). They are declared, never
verified, and the hub only compares them. When open sessions of
different members declare the same home or workspace, their member views
carry
`shared_environment`, the dashboard warns — the members can read each
other's credentials, and a review between them is not independent — and
recommends separating them, and a `shared_environment_detected` event
goes to the owners and admins without waking any agent. Nothing is
refused.

**Reason:** the maintainer's decision: warn and recommend separating,
refuse nothing. Its reason beyond that was not stated.

**Rejected alternative:** refusing a session that shares an environment
with another member — excluded by the decision; why is not recorded.

## The instance admin is the earliest human, sees counts only, and opens no project

**Id:** 705196ad-8610-4905-ba14-d9fbc3aebbad
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract change in `docs/api.md` §6.2 and §16, 2026-10-22
**Revisit when:** the accounts design lands (granting further admins, suspension, audit)

`instance:admin` is a human-only scope held by the earliest-created
human — the one `maity-hub owner create` made. It lists the hub's users
with counts and timestamps only (memberships, agents, last sign-in), and
never passwords, tokens, credentials or content; being instance admin
opens no project. For `members:admin` callers, and for an owner on their
own agents, the member view adds the owner and credential counts, which
never appear in events.

**Reason:** the earliest human matches the migration the accounts
design plans; everything else about admins — granting more, suspending,
audit — waits for that design. Why the list stops at counts and opens
no project is not stated beyond the contract's rule itself.

**Alternatives:** unknown; the accounts design's draft names the path
`/admin/humans` instead of `/admin/users`, left open.
