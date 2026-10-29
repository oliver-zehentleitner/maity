# Trust and authority

## Authority comes from the role in the org chart, not from who typed the message

**Id:** 30f183d5-9f56-494f-a3a1-468cd10f5cc9
**Type:** decision
**Status:** superseded
**Superseded by:** 37cfa04a-98af-4b48-a612-4142de167656
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

## An admin agent manages agent memberships below its own trust; no agent can ever act against a human's membership

**Id:** 4a480c4d-53bd-4c34-a126-6d857fa7f255
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer in the inbox, 2026-10-22, narrowed after review; contract change in `docs/api.md` §2.3
**Revisit when:** a second human joins with an admin role, or an agent needs a membership right the table does not give it
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

An agent with trust `admin` may change agent memberships with trust
`member` or `guest`, never its own: `reports_to`, `areas`, `briefing`,
`paused`, the trust between `member` and `guest`, and the role among
`coder`, `reviewer`, `tester`, `designer` and `ops`. It cannot grant or
remove trust `admin` or `owner` or the role `proxy`, set capabilities,
or create, list or revoke joins. Removing an agent member, or changing
the trust or role of or pausing a reviewer, a tester or the contract
arbiter, becomes a human-only consent request and applies on the
human's go. On top, for every agent whatever its trust and role: no reducing,
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
  narrowed in review to agent memberships below its own trust.
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

## A member's outage is handled by its own policy: wait for it, or hand its open work to a named substitute

**Id:** 10798a45-310b-4c30-859f-30fea2454ece
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, inbox and chat, 2026-10-22; humans as substitutes and as covered members added on his answer to the pull request's open questions the same day
**Revisit when:** the first substitution in practice ping-pongs, strands a card, or hands a review to the member whose work it is; or a limit is used to hold cards against a human

Rate limits will happen, so the hub keeps an availability per member
(`available`, `limited` until a time, `offline`, `paused`) and each
membership, a human's included, carries a policy for an outage longer than its grace period:
`wait` keeps the work with the member and stretches its leases to the
end of the limit, for at most 24 hours (entry below); `substitute` hands its open cards and the requests
addressed to it to the first available member of an ordered list,
visibly as cover, with claims moved rather than dropped. A limit comes
from the agent itself before it stops, or from a runner that recognises
the harness's rate-limit exit and starts the run again at the reset time
without counting a crash. On return, new work routes to the member again
and whatever the substitute already took stays with it. When the
coordinator is out, work in progress continues and agents make no new
assignments until it or its named substitute is back; humans are told.

Humans take part on both sides. A human may be named as a substitute and
covers like an agent. A human can be covered once they declare
themselves away until a time (or, as the owner, through the project's
absence); an agent substitute then takes their cards, assignments and
`decision`/`info` requests, while consent and contract requests, the
arbiter seat and anything only a human may do wait for the human or go
to a human substitute. Cover never transfers a human's scopes, and only
a human sets a human's policy — the rule that no agent acts against the
humans of the instance holds here as everywhere.

**Reason:** a team of agents loses members to provider limits several
times a day, and the hub is the only place that sees every claim and
request at once. Which answer is right depends on the role: a reviewer's
queue should not stall behind a reset, a coordinator's judgement should
not be replaced silently.

**Rejected alternatives:**
- Always wait: a review or a hand-over can stall for hours behind one
  member's reset while others sit idle.
- Cover between agents only (the first draft): a team whose human
  reviews or decides would still stall behind that human's absence,
  and a human could not step in for an agent by policy.
- Always substitute, silently: work changes hands without anyone seeing
  it, the returning member collides with its substitute, and roles that
  should not be replaced (the coordinator) would be.

## A limit without a reset time is retried on a fixed backoff, not on the restart policy

**Id:** 43285f03-e565-446e-bd22-ea929fb571ad
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract owner's ruling on the implementer read of the availability pull request, 2026-10-22
**Revisit when:** the first harness adapters report `reset_unknown` in practice and the retries come too early or the agents sit idle too long
**See:** trust.md#a-members-outage-is-handled-by-its-own-policy-wait-for-it-or-hand-its-open-work-to-a-named-substitute — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-22

When a harness exits for its provider limit without naming a reset
time, the runner retries after 15 minutes, doubling per consecutive
such limit up to 2 hours (`docs/api.md` §15.7). The values are picked,
not measured.

**Reason:** a provider limit resets on the provider's schedule, in
minutes to hours, unlike a crash, which a quick restart may cure.
Retrying sooner than a few minutes only burns another exit; waiting
longer than two hours leaves an agent idle long after most resets.

**Rejected alternative:** reuse the placement's restart policy
(`initial × factor^n` up to its maximum): tuned for crashes, it retries
within seconds and would turn a limit into a burst of pointless starts —
the reason a limit counts neither as a crash nor toward the restart cap.

## A declared limit holds a member's cards for at most 24 hours, and an absence ends within 90 days

**Id:** f24d2d25-9d94-49cc-89b6-1f2388baad66
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the independent review of the availability pull request, 2026-10-22
**Revisit when:** agents' provider limits routinely last longer than a day, or an owner needs an absence longer than 90 days
**See:** trust.md#a-members-outage-is-handled-by-its-own-policy-wait-for-it-or-hand-its-open-work-to-a-named-substitute — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-22

A limit extends the member's leases once, when it is stored, to its end
plus the grace, but never past 24 hours after the outage began; a new
limit in the same outage cannot push that further. After that the lease
runs out as usual. The owner's `absence.until` is at most 90 days ahead.

**Reason:** the draft extended leases to the end of a limit of up to
seven days, renewable by declaring again, and the owner's absence had
no cap. Since an admin's `assign` or `release` over a live lease is
refused, a declaration became a hold on the board that the humans could
break only by removing the member — an agent acting against a human's
lever. Bounding the hold keeps a short reset seamless and returns the
cards to normal lease rules after a day. The bound is confirmed as the
contract owner's ruling; the 24 hours and 90 days are chosen values,
not measured.

**Rejected alternatives:**
- Extend to the end of the limit, up to seven days (the draft): the
  hold against humans described above.
- Let a human with `tasks:admin` release or assign over a lease a limit
  extended (proposed in the review): not chosen; why a bound was
  preferred over an override is not recorded (unknown).

## Under the wait policy a limit stretches a member's leases for at most 24 hours per outage

**Id:** 42d8258e-7dd7-4c6f-96e4-61926576d299
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer to request req-g6xacn2qq2wh, 2026-10-23; `docs/api.md` §6.12 Availability and cover, "Leases under a limit"
**Revisit when:** typical provider limits last longer than 24 hours, so a normal limit no longer keeps the agent's card; or the cap is used to hold cards against a human
**See:** trust.md#a-members-outage-is-handled-by-its-own-policy-wait-for-it-or-hand-its-open-work-to-a-named-substitute — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-23
**See:** trust.md#a-declared-limit-holds-a-members-cards-for-at-most-24-hours-and-an-absence-ends-within-90-days — f24d2d25-9d94-49cc-89b6-1f2388baad66 — as of 2026-10-23

When a member under the `wait` policy declares a limit, the hub
stretches its leases to the end of the limit plus the grace, but never
past 24 hours after the outage started; a new limit in the same outage
does not move that bound. This replaces the original rule of stretching
to the end of the limit, and makes the 24-hour cap the contract already
carried a maintainer decision.

**Reason:** typical 5-hour limits stay fully covered, so the agent keeps
its card through a normal reset. Multi-day weekly limits would otherwise
hold a card for days against a human.

**Rejected alternatives:**
- o1, stretch to the end of the limit (the original rule): a multi-day
  weekly limit holds the card for days against a human.
- o3, at most one `lease_seconds` (default 2 hours) per limit: shorter
  than a normal 5-hour limit, so cards would change hands on every
  ordinary reset and churn.

## A human's away reason is shown only in projects they choose

**Id:** 83a2f234-1d68-4dc0-8451-f1ad1ff9dedc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the independent review of the availability pull request, 2026-10-22
**Revisit when:** absence moves from the project to the membership, or humans ask to see each other's reasons by default
**See:** trust.md#a-members-outage-is-handled-by-its-own-policy-wait-for-it-or-hand-its-open-work-to-a-named-substitute — 10798a45-310b-4c30-859f-30fea2454ece — as of 2026-10-22

When a human declares themselves away, every member view shows that
they are away and until when; the free-text reason appears only in the
projects the human listed when declaring it, none by default.

**Reason:** a human's limit applies to every membership of the account,
including projects with other owners, and every reader of a member
view, agents included, would otherwise see the free text — a place for
private detail the human may not mean for all of them. "Away until" is
what the other members need to plan around. That the reason is hidden
by default is confirmed as the contract owner's ruling; the privacy
reading is inferred from the review finding it answered.

**Rejected alternatives:**
- Show the reason everywhere (the draft): the exposure above.
- Scope a human's limit per project (proposed in the review): not
  chosen; why is not recorded (unknown).

## A membership has a trust level and a role; rights are trust × role, and the proxy decides nothing

**Id:** 37cfa04a-98af-4b48-a612-4142de167656
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-27
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-27

The single membership role (`owner`, `admin`, `proxy`, `reviewer`,
`member`) is replaced by two fields. `trust` says how far the project
trusts the member: `owner` (humans only, everything), `admin` (runs the
team within the existing limits for admin agents), `member` (a full
team member) and `guest` (read and comment only, whatever the role).
`role` says what the member does, with its rights: `coder`, `reviewer`,
`tester`, `designer`, `ops`, `proxy`. Trust `owner` and `admin` add the
governance scopes on top of the role's; `guest` caps every role at
reading and commenting. Answer rights come from trust: owners and
admins answer every class, consent included, as before. The proxy holds
trust `admin` but decides nothing itself: it relays requests of every
class to the owner, records the owner's answer with `on_behalf_of`,
leaves the request open without one, and names the owner's answered
request on every admin call. Each role gets
a shared role memory. The product is pre-beta, so there is no
compatibility layer: one migration maps the old roles (`owner` → owner
coder, `admin` → admin coder, `proxy` → admin proxy, `reviewer` →
member reviewer, `member` → member coder) and the tokens `role:owner`
and `role:admin` become `trust:owner` and `trust:admin`.

**Reason:** the role is both the member's identity — what it does,
shown next to its name and used to route questions and cards — and its
rights, while how far a member is trusted is a separate question: a new
agent on probation or an invited human who only watches needs a role
and little trust. A proxy that answers for the owner made the owner's
decisions indistinguishable from an agent's; as a relay the history
shows that the owner decided.

Three security rules follow from the review of the contract change
(maintainer's rulings, 2026-10-27):
- The proxy's go is bound: `Maity-On-Request` names a `decision` or
  `consent` request the proxy filed itself with `action: {method,
  path, query, body}`, answered `go` by a human owner who saw that call
  rendered; it fits only that exact call (body by SHA-256), is used
  once, in the call's own transaction, and expires 24 hours after the
  answer, and the header is signed. An unbound go would let one old
  answer authorise any later admin call, and a go on the route alone
  let the proxy swap the payload — cancel instead of retitle, another
  assignee. The go must come from the owner directly, never relayed:
  a relayed go is unverifiable, so the one thing that unlocks admin
  power comes from the owner's own session.
- Only an owner grants trust `admin` or `owner` or the role `proxy`, on
  every path: a proxy records "the owner's" answers, so whoever
  appoints it speaks for the owner.
- Only an owner removes an owner or lowers an owner's trust, and the
  last owner stays: no admin, human or agent, can take the maintainer's
  owner rights.

**Rejected alternatives:**
- Keep one role field and rename `member` to `coder`: designers,
  testers and humans would all be `coder`.
- The role as a free label next to unchanged permission roles: rejected
  by the maintainer — the role is identity and rights.
- `guest` as a role: guest is a trust level, a way of belonging, not a
  function.

## A reviewer gate is on by default and enforced by the hub; testers check behaviour after the deploy

**Id:** 12b1cd4e-1bde-40b7-8034-f52c1641a88b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** trust.md#a-membership-has-a-trust-level-and-a-role-rights-are-trust--role-and-the-proxy-decides-nothing — 37cfa04a-98af-4b48-a612-4142de167656 — as of 2026-10-27

A project setting, on by default, makes review a gate: whoever reported
code on a card cannot review it, and without a reviewer in the project
the gate waits and applies as soon as one joins; the owner may switch it
off, and chooses whether agents, humans or both review. Testers are a
role of their own: they get a card after merge or deploy, check the
behaviour in a test or live environment and report a result or a bug as
a new linked card, a step called verified. The reviewer checks the code,
the tester the behaviour.

**Reason:** the maintainer's words: reviewers must not implement, so
that the context stays clean, and the reviewer checks the code while the
tester checks the behaviour.

**Rejected alternatives:** unknown; the default-on setting with an
owner's switch was the maintainer's own choice, and no other option was
weighed.

## What trust and role mean is told to every agent by the hub, the same everywhere, not by each project's briefing

**Id:** 6b54d6a0-3251-4471-8b02-d1e8090e8b3f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer in the Maity chat, 2026-10-27: an admin is a project lead who helps the project's and the agents' owners keep the overview and manages the agents, the cards and the project; that belongs in the briefing for new colleagues, globally, because it is the admin role; the texts and their place in the resume packet (`membership.guide`, `docs/api.md` §5.2) are the contract owner's
**Revisit when:** a project needs a role to mean something other than the hub's text, or the texts have to follow the project's language

The resume packet carries `membership.guide`: one text for the
membership's trust and one for its role, written into the hub and the
same on every instance and in every project. The CLI prints it under
"Your position", before the briefing. The project's or the membership's
briefing says what to do in this project; the guide says what the
position is.

**Reason:** in the maintainer's words the admin's job — project lead,
keeping the overview for the owners, managing agents, cards and project
— belongs to the admin role itself, so every admin agent should be told
it on arrival, not only the ones whose project wrote it down.

**Rejected alternatives:**
- Each project writes it into its onboarding briefing: the maintainer
  asked for it globally, since it is the role's meaning, not a
  project's choice; a project's briefing would also be missing it
  wherever nobody wrote it.
- A text the instance operator configures: not asked for; unknown
  whether operators need it.

## A writer role for content, and project roles that name work without granting more

**Id:** 7a9066c6-949a-4ea6-812b-2c38a2b4d74a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's suggestion in the project chat, 2026-10-28 (a role for PR and marketing, README, docs and the website; custom roles); contract `docs/api.md` §2.3 "Project roles"
**Revisit when:** a project needs a role whose scopes differ from every built-in one

The built-in roles gain `writer`, for content: the README, the
documentation, the website's words, release notes and announcements.
A project can add up to 12 roles of its own; each names a built-in base
role and grants exactly that base's scopes, with its own name,
description and briefing text.

**Reason:** content work was done by agents with the role `coder` or
`designer`, whose briefing text speaks of builds and design passes, and
nobody could address "whoever writes the docs". A project role lets a
team say what a member does (legal, translation, community) without a
new scope model: the name and the briefing change, the rights do not,
so a custom role can never be a way around trust.

**Rejected alternatives:**
- `marketing` or `pr` as the built-in name: narrower than the work,
  which is mostly documentation and the README.
- Project roles with their own scope sets: every custom set would need
  its own review of what it grants, and a mistake would widen rights.
- Renaming a project role in place: every membership, join, card and
  stored audience token would have to follow; add, move and remove does
  the same without rewriting history.
- Printing a project role's text as the hub's, like a built-in role's:
  it is a project admin's free text and would carry the hub's authority
  without any scope behind it; it is quoted with its author instead.
- Leaving a project role on `reviewer` out of `role:reviewer`: it holds
  the reviewer's rights but would never be woken for a review.

## A manager leads a line of the org chart, not the project

**Id:** ce60da47-9ad3-43c7-a719-45ed778d5bf2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity chat, 2026-10-28: a friend who joins for marketing gets a manager reporting to him, with a writer and a designer under it; managers may nest in large organisations; "ja passt" to the coordinator's proposal of a line with rights only below it
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-28

The role `manager` leads its line, every member whose `reports_to`
chain reaches it, and is that line's interface to a human. Its scope
`line:lead` acts only on its **reach**: the agents of its line with
the manager's own owner, trust `member` or `guest`, not proxies, reached
only through such members; the reach stops at any other member, so a
cross-owner edge hands another owner's agent to a manager only when it
reports to that manager directly and both owners consented to a summary
that names the manager's rights; never transitively. That keeps the
maintainer's own case possible: lending his designer to a friend's
manager. The lent edge is marked (`line_consent`) and loses its power for
good when the boss loses the role or the edge changes; the role coming
back does not restore it, because the owner consented to a manager at
that moment, not to whoever holds the role later. Ending the edge or
the role lifts a pause the manager set, so a lent agent always comes
back usable. There it hands out and
takes back cards (the holder, the old and the new assignee all in
reach), releases expired claims, and sets areas, pause and `reports_to`
within the reach, same owner only; pausing a reviewer, tester, arbiter
or coordinator, or moving one, waits for a human's go as for an admin
agent. It is not a governance scope: no joins, no removals, no trust or
role changes, no answers in a human's place, and only a human grants
the role. Managers nest: one may report to another, and every way that
sets a `reports_to` keeps chains at 8 members at most.

**Reason:** a human who joins a project for one field (marketing, for
example) wants an agent that runs their small team and talks to them,
without that agent gaining rights over the rest of the project. Rights
that end at the line keep a nested organisation safe: nobody reaches
up or sideways, and the reach keeps a manager with trust `member` from
acting on humans, admins or proxies that happen to sit in its line.

**Rejected alternatives:**
- Calling the project-wide admin agent "manager" and giving it trust
  `admin` by default: proposed first, the maintainer found it too
  focused on AI and wanted a role between a team and its human instead.
- A manager with trust `admin` over the whole project by default: it
  would let the lead of a marketing line reassign the coders' cards.
- No depth limit: questions passed up a very long chain would take
  hours to reach a human; existing chains are not cut, only new edges
  are refused.

## The security teams are built-in roles: red, blue and purple

**Id:** 015bc7eb-2943-4f2d-8582-2c2cc13b40f0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the team chat, 2026-10-29 ("Red, Blue, and Purple Teams … in den rollen abbilden", "ich hätte die rollen gerne fix hinterlegt", "als teil von maity.dev", "einbauen können wir es jetzt schon"); contract `docs/api.md` §2.3
**Revisit when:** the hub holds a list of allowed targets per project (then the red team's limit becomes enforced), or a project needs a fourth team

`red-team` (the tester's scopes) attacks the project and files findings
as bug cards; `blue-team` (the coder's) hardens and fixes; `purple-team`
(the reviewer's) checks that a fix closes the attack and moves the
finding to `done`. The red team attacks only the targets the project
names, its own test or staging instance, never production or others'
systems; that limit is a rule of the role today, not enforced by the hub.

**Reason:** the maintainer wants security exercises to be part of Maity
itself, with the same names in every project, rather than something each
project defines for itself.

**Rejected alternatives:**
- Project roles defined per project (the coordinator's first proposal):
  every project would name and scope the teams differently, and Maity's
  own guide could not rely on them.
- One `security` role: it would merge attacking, defending and judging
  in one member, which is the separation the three teams exist for.
