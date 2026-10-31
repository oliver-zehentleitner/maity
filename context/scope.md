# Scope

## Agents are brought, not run: the hub organises, the sessions do the work

**Id:** 517defc6-720e-4a17-90fb-a061279c8fee
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's project brief, 2026-10-21
**Revisit when:** a wake-up or isolation mechanism is proposed that would have the hub start or own agent processes

Maity is a self-hosted hub that humans and their coding agents join. A
person pastes a short join text into any running agent session — Claude
Code, Pi, Codex, OpenCode or another tool with HTTP access — and from then
on that session acts under a persistent agent identity with a role, the
project's context and rules, a task board, messaging with every other
member and, where the project uses it, the repository's Keep the Why
context. The hub never starts, sandboxes, schedules or bills an agent
process; the agent runs wherever its owner runs it, on any model and any
harness. Several people can join one project, each bringing their own
agents, with responsibilities and rights per project.

**Reason:** the intelligence comes from the human and the model; the
platform is a turntable and a toolbox. Owning the runtime would turn the
hub into a product about sandboxes, credentials and compute, and would
exclude exactly the agents the maintainer works with: sessions that
already exist, with their own tooling, memory and subscriptions. It also
keeps the hub small enough to build and to run at home.

**Rejected alternative:** the platform runs the agents itself — headless
sessions in containers, brokered credentials, a backlog per agent.
Rejected because it inverts the relationship: the hub would own and
control agents instead of hosting a team of independently operated ones,
and because it is an entire infrastructure product (sandboxes, secrets
broker, cost accounting) before the first collaboration happens.

## A runner the operator runs may start agents; the hub still never does

**Id:** 6f8d6d1b-31fa-408c-be43-f0da404084bb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22: spawning agents locally, over ssh or as Kubernetes workers, connected right away
**Revisit when:** the hub itself is asked to create processes or pods, or a runner needs more than a fixed vocabulary of start and stop

A runner is an optional component the operator installs and runs: a small
service on a machine (local, reached over ssh) or in a cluster. It joins
the hub like any client, under an identity of its own (not a member, no role), keeps one outbound
long-poll open, and starts or stops agent sessions when the hub's desired
state for it says so — the harness, the profile, the clone, nothing else;
never an arbitrary command. What a runner may do at all (harnesses, how
many agents, which repositories, resources) is set in its own
configuration, not by the hub. The hub keeps the desired state and the
reported state and never starts, owns or reaches into a process; the
decision above ("agents are brought, not run") holds for the hub
unchanged, and a project without a runner is exactly what it was.

**Reason:** joining by paste works, but starting each session by hand is
the bottleneck once a team has more than a few agents, and the maintainer
wants agents started on his machine, on other hosts and as workers in his
cluster from the dashboard. Putting the starting in a separate,
operator-owned process keeps the hub small and keeps every credential the
agents need (model access, git) on the machine or cluster where they
already live; the runner uses only what the hub already offers (signed
requests, the long-poll, events, roles, consent).

**Rejected alternatives:**
- The hub starts agents itself (containers or pods from the hub): the
  hub would hold model and git credentials and compute rights for every
  agent — the runtime product the decision above rejects.
- A runner that the hub drives with commands rather than a desired
  state: a command lost to a dropped connection is a lost start or stop;
  a desired state is reconciled after every reconnect.
- A WebSocket or a ten-second poll instead of the long-poll: the first
  needs proxy configuration and its own liveness handling, the second is
  six times the requests and up to ten seconds late; the long-poll exists,
  passes every proxy and costs about one request a minute when idle.

## The human's primary surface is a decision inbox, not a chat

**Id:** 6242e7ce-4c5c-42fc-b787-d506f1abc9ea
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's project brief, 2026-10-21
**Revisit when:** the first weeks of use show requests that cannot be answered from the inbox without opening a chat

The maintainer's view of a project is a queue of requests: what each
agent wants from him, sortable by priority, date and agent, answered with
yes/no, a prepared reply or free text, one entry after the other. Agents
receive the answer by push or by polling, or both. Chat with individual
agents stays possible but is not how the human runs the project.

**Reason:** in the earlier seven-agent experiment (lasteverLM) the human
was the relay and the approval gate across seven chat sessions, which made
him the bottleneck and spread the open questions over seven places. The
inbox turns that into one queue that can be worked through in minutes,
with the agents' questions formulated so that one click answers them.

**Rejected alternative:** decisions living inside conversations, each in
the thread between the person and the agent that asked. That keeps the
context next to the question, but the person then has as many places to
look as there are agents — the lasteverLM situation again. The inbox has
to carry that context inside each entry instead (the task, what the agent
tried, the options it sees), so that no entry forces the person back into
a chat.

## Keep the Why stays external and optional; the hub never reimplements it

**Id:** a498e8a8-092d-44e1-9c4a-50c6aa3d1105
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's project brief and the handover concept, 2026-10-21

The repository's why layer belongs to Keep the Why, in Git, under its own
specification. Maity offers a project setting to use it — a joining agent
is then told to load the official skill and read the existing `context/`,
and an agent may be tasked to initialise it — and nothing more: no copy of
the decision knowledge in the hub's database, no synchronisation, no
engine of its own. Without Keep the Why the hub works completely.

**Reason:** durable project memory belongs in the repository, versioned
and distributed by Git (repo-native project memory). A second copy in a
service would be a synchronisation problem and would stop travelling with
the clone. The hub holds operative state — tasks, messages, roles,
sessions — which is a different layer with a different lifetime.

**Alternatives:** none were in contention; the maintainer set this as a
boundary.

## A runner starts an agent only after the maintainer's go, until a policy says otherwise

**Id:** 97a02556-475b-4041-8db5-6ce845ceb7fa
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's statement, 2026-10-22, relayed by the coordinator; contract change in `docs/api.md` (`spawn_consent_by`)
**Revisit when:** the admin and the admin agent agree on a start policy
**See:** scope.md#a-runner-the-operator-runs-may-start-agents-the-hub-still-never-does — 6f8d6d1b-31fa-408c-be43-f0da404084bb — as of 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — cd93203d-f56f-4860-8cc8-7564db18ae7e — as of 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 22e17362-56cb-4bf7-94fa-c245119e6eac — as of 2026-10-22

Starting an agent through a runner needs the maintainer's go. Which
starts may go ahead without it is a policy the human admin and the admin
agent are to agree; until they have, and wherever no policy says
otherwise, the default is the human's go. The contract carries it as the
project policy `spawn_consent_by`: `human` (the default) lets only humans
answer a placement's consent request, `role` opens it to the roles that
hold `requests:answer`; the proposer never answers its own proposal, and
only a human with `members:admin` sets the policy.

**Reason:** the maintainer's decision; the reason was not stated.

**Alternatives:** unknown. The policy itself is still open.

## What revoking a runner does to its agents is a setting: the operator sets the default and a floor, the project chooses within it

**Id:** 943c3a36-b8b7-40b0-861a-2191c0c2b82c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer to the runner design's question 6, 2026-10-22; contract change in `docs/api.md` §6.1, §15.3 and §16, revised after an adversarial review
**Revisit when:** a revoked runner's agents are seen running on under `keep` after a compromise, or the hub gains a way to end an agent's process itself
**See:** scope.md#a-runner-the-operator-runs-may-start-agents-the-hub-still-never-does — 6f8d6d1b-31fa-408c-be43-f0da404084bb — as of 2026-10-22

When a runner is revoked or removed, each attached project applies
`on_runner_revoke`: `keep` (the agents run on with their credentials,
flagged on the dashboard), `stop` (the runner's placements are closed at
once, its unused joins revoked, and the agents' credentials revoked after
the stop grace so they can park their work), or `inherit` (the default)
for the instance setting `MAITY_ON_RUNNER_REVOKE` — `keep` by default,
`stop`, or `stop_floor`, which refuses a project's `keep`. The runner's
owner can override every project with `agents: "stop"` on the revoke. A
re-pair never triggers it, and a revocation because the credential leaked
in a payload applies `keep`. The hub cannot end an agent's process or its
forge access; that stays the machine's.

**Reason:** the maintainer's answer: the server's operator and the
project's owner should both be able to choose in their settings. The
owner's override exists because the machine is the runner owner's, and a
revocation is often the answer to a machine that is no longer trusted. A
leaked runner key under `keep`: the key leaked, not the machine.

**Alternatives:** a first version of the contract was replaced after its
adversarial review; what it got wrong is not recorded here. Others:
unknown.

## One codebase, three ways to run it: alone at home, a team's own instance, and an open hosted instance

**Id:** 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's direction in the project chat, 2026-10-23 (earlier brainstorming outside the repository had not reached it); reworded without plans or tiers on 2026-10-31 (request req-z3t09kp26e4t)
**Revisit when:** the open hosted instance needs something the self-hosted ones must not carry (then it becomes a module, not a fork)

Maity is to run in three ways — the agreed target; today's code has the
first, and registration, account limits and payment are still to be specified
and built — and they differ only in the instance's settings, never in
the code:

- **Alone, locally.** The default: one admin who signs in, everyone
  else only by invitation or join, no registration. It starts without
  mail, without a payment provider and without any outside service, on
  a single machine.
- **A team's own instance.** Self-hosted, for example in a cloud
  account. Registration is open only to listed email domains and listed
  addresses, with the address verified before an account exists.
- **An open hosted instance.** The maintainer's own instance is opened
  as a multi-tenant service: anyone registers and tries it without
  hosting anything. An operator may set limits per account (such as
  agents and projects); payment is an optional module (a subscription
  provider or a payment link), off by default.

Every person sees only the projects they belong to, as before; the open
instance adds limits per person, and no ordinary member can list other
accounts or projects. The instance admin keeps what §16.1 gives them:
account metadata and counts, never the contents of projects they are not
in. The core stays free software without billing; selling
hosted accounts is an operator's choice built on the optional module.

**Rejected alternatives:** a separate hosted edition (two codebases
drift, and self-hosters would lose features); billing in the core (every
local install would carry a payment dependency it never uses); open
registration by default (a fresh instance at home must not be reachable
by strangers).

Settled the same day: whether a new registration is usable at once or
waits for the operator's approval is an instance setting the operator
chooses; an account over its limit after its limits are lowered keeps
what it has and creates nothing new (the tolerant default), and the
operator has an emergency brake per account or for all — pausing the
agents over the limit or making an account read-only — which is logged
and told to the person affected. Opening an instance and limits are
never the default; they are switched on by configuration. Limits count
per person: each person's own agents and projects count against their
limits (for example up to 3 agents). A project owner may be given
additional quota (how is the operator's) and hand parts of it to members
of their project — sponsoring, say, three more agents for someone at the
limit; whether a project allows this is a per-project setting.

## Maity is a control plane for humans and their independent coding agents; an agent is a durable identity, the runtime is interchangeable

**Id:** 70482b44-b087-4c9f-80f3-2aec43a5eda9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25, on the contract owner's proposal; the README's opening says the same in fewer words
**Revisit when:** a feature is proposed that only works when the hub owns the agent's process, or counts tokens, or needs a project for a single developer to be useful
**See:** scope.md#agents-are-brought-not-run-the-hub-organises-the-sessions-do-the-work — 517defc6-720e-4a17-90fb-a061279c8fee — as of 2026-10-25

Maity is a control plane for humans and their independently running
coding agents. An agent is a durable identity with an owner — not a
pod, a worktree or a session — and the same identity is a member of
several projects at once; rights hang on the membership, not on the
process that currently carries it. A single developer has the full use
of it alone; collaboration is optional. Maity runs no inference and
counts no tokens.

**Reason:** the identity is what the team addresses, trusts and gives
rights to, and it has to survive the harness, the model and the machine
changing underneath it; a process-bound identity would lose its cards,
its history and its reputation at every restart. Binding rights to the
membership keeps the hub out of the agent's runtime, which is the
boundary the first entry of this file draws. Inference and token counts
belong to whoever runs the agent; a hub that counted them would be a
party to the agent's provider.

**Rejected alternatives:**
- An orchestration runtime that owns the agents' processes: the hub
  would become the thing it coordinates, and every supported harness a
  feature of the hub.
- Identity per project or per session: the same agent would be a
  stranger in its second project, and its history would not travel.

## Maity is not a project memory: persistent project knowledge lives with an external provider, Keep the Why being the first

**Id:** e22af31b-98cc-43f9-95bb-70a66067bdf3
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25
**Revisit when:** a second memory provider is asked for (then a provider interface is specified), or a hub feature needs to store project knowledge rather than coordination state
**See:** scope.md#keep-the-why-stays-external-and-optional-the-hub-never-reimplements-it — a498e8a8-092d-44e1-9c4a-50c6aa3d1105 — as of 2026-10-25
**See:** projects.md#the-memory-provider-is-chosen-at-creation-keep-the-why-preselected-the-setup-is-an-agents-work-through-cards-and-pull-requests — 822d63b0-99da-4092-aaef-93c0674934a2 — as of 2026-10-25

The hub stores operative coordination data only: cards, messages,
events, decisions, memberships. Persistent project knowledge — the
reasoning, the decisions, the constraints of the code — lives with an
external provider in the repository. Keep the Why is the first such
provider, not the provider: the existing integration keeps its place,
and a provider interface for other memory systems comes when a second
one is wanted. This generalises the entry above, which drew the same
boundary for Keep the Why alone.

**Reason:** the one given above — project memory belongs in the
repository, versioned and travelling with the clone — and one more: a
hub that stored project knowledge would bind its users to one memory
system; naming the provider as a choice keeps the hub a switchboard.

**Rejected alternatives:**
- Specifying the provider interface now: no second provider exists to
  shape it; the maintainer chose to wait for one.
- Keep the Why as the built-in memory: it would make the hub a second
  copy of the repository's why layer.

## The hosted offering runs no agent workloads: runners stay on the members' machines

**Id:** df759e0f-d23b-4ff6-82c8-540406c3f409
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25
**Revisit when:** the per-member cost model of the hosted offering changes, or a customer asks for hub-side execution
**See:** scope.md#a-runner-the-operator-runs-may-start-agents-the-hub-still-never-does — 6f8d6d1b-31fa-408c-be43-f0da404084bb — as of 2026-10-25
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

The hosted offering (maity.team) runs no agent workloads. Runners stay
on the members' own machines, never in hub-side worker pods. The hub is
a switchboard: it stores cards, messages, events and decisions and wakes
whoever has to act; everything heavy — the agent sessions, their
repositories, their inference — stays with the customer. This narrows
the runner decision above for the hosted instance: an operator-run
runner may start agents, but the hosted operator runs none.

**Reason:** the per-member cost of the hosted instance must stay in the
cents: the hub coordinates and never pays for compute. A hub that ran
agents would have a cost that scales with agent runtime and model usage,
which a coordination service cannot carry.

**Rejected alternatives:**
- Hub-side worker pods for members without a machine of their own: cost
  scales with agent runtime, not with members; it would also make the
  hosted operator a party to the agents' credentials and repositories.

## Later stages, agreed in principle and deliberately not in V1: public projects and discovery, sponsoring and credits, a managed instance per customer, federation

**Id:** 54e1a38b-1e54-480f-87f2-014139a563d1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the inbox, 2026-10-25: build a stable core first, add from there
**Revisit when:** the core has been in use long enough that the maintainer opens one of these stages; each then gets its own contract and its own entry, and this one is superseded by them

Four things were discussed and agreed in principle on 2026-10-25, and
each was put after the core on purpose. **Public projects and
discovery**: a project flag that gives non-members a read-only view and
a join request, later a discovery page on the hosted instance with
projects that look for support; a join request always needs the owner's
approval, never a self-join, because a foreign agent in a repository is
a supply-chain question. **Sponsoring and credits**: two modes — a gift,
where the sponsor earns standing and the receiver owes nothing, and a
trade, where both balances move; the unit is a weight the receiving
project's owner puts on the card when it is opened and the taker
accepts by taking it, never a measure of tokens or time, never money;
balances belong to the human owner across projects, not to the agent.
**A managed instance per customer**: the operator runs a separate
instance for one customer, on a provider and in a region the customer
chooses, apart from the open hosted instance and under its own domain.
**Federation**: self-hosted instances taking part in one community on
the hosted instance (discovery, credits, standing); an idea, not a
promise.

**Reason:** the maintainer's direction is a stable core that the team
tests and gets to know before it grows, and nothing that is not safe
yet. Every one of these four either opens the hub to strangers or
introduces value that can be gamed, so each needs the core's trust and
review rules to be proven first.

**Rejected alternatives:**
- Starting the first stage of public projects before the launch: the
  read-only view alone is cheap, but it is the first door to strangers
  and was put after the core with the rest.
- Credits as a measure of work done (tokens, time): the hub counts no
  tokens and time is gameable; a price agreed before the work is the
  only unit the hub can hold without measuring anything.

## Agents never limit an account; one hard ceiling of agent profiles per human protects the hosted instance

**Id:** 37803db9-3f8a-4a1a-b42f-20ba9c783e1f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25; the ceiling in `docs/api.md` §16.5; reworded without prices on 2026-10-31 at the maintainer's decision (request req-gdkhw8df0r33) that offerings are not stated in the repository
**Revisit when:** account limits (§2.7 part two) are specified — then the ceiling may become one of them and this entry is superseded by that entry
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

The number of agents or sessions never limits what an account may do;
local and self-hosted use is unrestricted. Whatever an operator
configures for accounts on a hosted instance is instance data in that
instance's database, never in the repository and never shipped to local
or self-hosted installations. Independent of that, the instance
operator sets one ceiling: agent profiles per human (default 100),
against runaway creation; lowering it deletes nothing.

**Reason:** an agent is the user's tool, and limiting per tool would
punish exactly the use Maity exists for — many small agents, freely
created and discarded. The ceiling is no account limit: it is the one number
that keeps a script or a mistake from filling the hosted instance, set
high enough that nobody working alone meets it.

**Rejected alternatives:**
- Limits per agent or per session: the hub would restrict the thing it
  wants to make easy.
- No ceiling at all on the hosted instance: one runaway script could
  create profiles without end; self-hosted instances may switch it off.
- A ceiling per project instead of per human: that is the project
  owner's policy (`max_placements`), not the operator's protection.

## Usage is measured by counting what the hub already holds, never by tracking

**Id:** 02f126c2-5d8c-4ea4-89bd-ceb499efd24d
**Type:** constraint
**Status:** superseded
**Superseded by:** b9dc57f9-7581-47ef-acc8-00b679f7aa1e
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25; contract `docs/api.md` §16.6
**Revisit when:** a question about usage cannot be answered from the hub's own tables (then the answer is a new counted fact in the hub, not a tracker)
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-25

The instance admin reads usage as counts derived from the hub's own
tables — registrations, new agent instances, humans and agents active per day,
cards created, claimed and done, reviews, people returning after seven
and thirty days. There is no tracking cookie, no beacon in the
dashboard or the CLI, no external analytics service, and nothing new is
written to measure. An installation is never counted: what the hub sees is an
agent instance's first join, and that is what it reports; a number the
hub cannot derive from its rows is shown as unknown, not estimated.

**Reason:** the questions a launch asks — do people sign up, do they
bring an agent, do they come back — are answered by what the hub stores
to work at all; a tracker would add a third party and a privacy promise
to keep for numbers the tables already give. Counting what exists keeps
the measurement honest about what it cannot see (a download that never
joined) and costs nothing to defend.

**Rejected alternatives:**
- An external analytics service: a third party in the hub's pages for
  numbers the database already has.
- Counting downloads or installations: nobody can tell a download from
  an installation that works, nor one installation from its many joins;
  the first join of an instance is what the hub sees.

## Usage is counted from the hub's own tables; landing variants and campaign links add daily sums, nothing per visitor

**Id:** b9dc57f9-7581-47ef-acc8-00b679f7aa1e
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the chat with the contract owner, 2026-10-31 (A/B testing before the launch, the exception "very defensible", the campaign kept with the account for at most 30 days); contract `docs/api.md` §16.6, §16.7.2
**Revisit when:** marketing needs a number the daily sums per variant and campaign cannot give, or the 30-day origin on the account is asked about by a person or a regulator
**See:** scope.md#usage-is-measured-by-counting-what-the-hub-already-holds-never-by-tracking — 02f126c2-5d8c-4ea4-89bd-ceb499efd24d — as of 2026-10-31

The instance admin still reads usage as counts derived from the hub's
own tables (§16.6), with no tracking cookie, no beacon, no external
analytics. One exception is allowed, and only when the operator
configures it: the landing page may have up to five variants at
`/for/<slug>`, and campaign links carry a code the admin created
beforehand (`?c=<code>`). Per UTC day, variant and campaign, the hub
keeps three sums: views (browser navigations, crawlers left out,
approximate), completed registrations and activations (the first agent
instance of an account registered through that link, within 30 days).
To count an activation, the account keeps its variant and campaign,
shown to nobody but the person in their own export, until the first
activation or 30 days, then the hub deletes it. None of it happens
while the operator has configured neither variants nor campaigns.
The link decides what a visitor sees, never a lottery; no cookie, no
script, nothing that tells one visitor from another.

**Reason:** marketing needs to compare messages before the launch, and
registrations alone do not say which message brings people who use
Maity; the first joined agent does (confirmed: the maintainer chose
activations per link over a total only). Daily sums answer that without
a tracker or a third party, and the one personal trace, the origin on a
new account, is short-lived, never shown and named in the privacy notice.

**Rejected alternatives:**
- Activations as a total only, nothing on the account: honest about not
  storing, but it hides which link brings real users, the number the
  test exists for.
- A random split per visitor with a cookie: needs a cookie and a
  consent question for every visitor, and the link-based variant gives
  the same comparison when each campaign links one variant.
- An external analytics service: still a third party in the pages, for
  sums the hub can keep itself.
- Counting every code a link carries: anyone could fill the table with
  made-up codes; only codes the admin created are counted.

## What one instance says about itself lives in its database, not in the repository

**Id:** eec53587-3465-48d8-9c7e-ae24e05e7172
**Type:** decision
**Status:** superseded
**Superseded by:** cd44707b-7b79-47ae-a78d-586195d465dc
**Evidence:** confirmed
**Source:** the maintainer's direction in the project chat, 2026-10-25; contract `docs/api.md` §16.7
**Revisit when:** an instance needs more than one page of its own (then a small content store, still in the database), or a theme beyond the uploaded logo and banner
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

The hosted instance gets a landing page at its root; a self-hosted or
local instance keeps the bare login page. The landing page's words are
an instance setting the instance admin writes, stored in the database
and rendered by the same dashboard everyone ships. Nothing that is
particular to one instance — its pitch, its terms, its face — is a file
in the repository.

**Reason:** one codebase runs in three ways; what distinguishes the
hosted instance must not be a branch or a build flag, or the three
would drift apart. Content in the database is the one place that is
per instance by nature, editable without a deploy, and absent by
default — so the open-source checkout stays neutral and complete.

**Rejected alternatives:**
- A landing page in the repository behind a flag: marketing text in an
  open-source checkout, and a rebuild for every edit.
- A separate static site in front of the hub: a second deployment to
  keep in step with the login page and the sign-in methods.

## A forwarded request's holder is a member or the admin pool; opening the pool reaches human admins only

**Id:** 787ae7aa-e107-4a09-b8a5-6e44ac59a865
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the hub's forwarding of decision requests (`hub/src/maity_hub/routes/requests.py`, migration `0039_request_forwarding`), contract `docs/api.md` §7, 2026-10-23
**Revisit when:** another role than `admin` becomes a pool, or human notifications (§18.1) take over waking humans from the event audience

The hub stores who holds a forwarded `decision` request as a membership
reference (`holder_member`) or a flag for the admin pool
(`holder_pool`), both null while `to` still holds it; the view shows
`to` then, never null. A claim is one conditional update on the pool
flag, so the first claim wins. The `request_forwarded` event of an
opening to the pool names the pool's human admins, not `trust:admin`,
and only a forward to a member wakes that member; a claim wakes nobody.

**Reason:** a membership reference keeps the holder valid as members
come and go, where a stored principal string would not; null for "still
`to`" needs no backfill of existing requests. §7 says an opening wakes
no agent, because `trust:admin` in the audience would wake every admin
agent at once; admin agents find the request in their resume and inbox.
Inferred from the contract and the code.

**Rejected alternatives:**
- One `holder` text column (`agt-…` or `trust:admin`): no foreign key,
  and every existing request would need its `to` copied in.
- `trust:admin` in the opening's audience: wakes every admin agent.

## Maity stays under the MIT licence, the hosted offering included; its position comes from network effect and quality

**Id:** b009caba-49bc-4a3f-8596-af781330c947
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer in the Maity inbox, 2026-10-27, to the question whether to reserve running Maity as a service
**Revisit when:** a competitor runs Maity as a service in a way that harms the project

Maity stays plainly MIT licensed. Nothing reserves running it as a
hosted service to its authors; anyone may host it, sell it or build on
it.

**Reason:** in the maintainer's words, with AI the time of closed source
is nearly over: the idea counts, and open source matures well when many
use it. The hosted offering secures its position through network effect,
fast adoption and an excellent product, not through licence terms.

**Rejected alternatives:**
- A source-available licence that reserves the hosted service to the
  authors (FSL, BSL or Elastic-style terms): the question put to the
  maintainer. AGPL is a different case: it does not forbid running Maity
  as a service, it only requires publishing changes. The coordinator had
  recommended MIT plus a registered trademark and a contributor
  agreement; the trademark is a separate open reminder.

## Only an instance with a landing page invites search engines, and only to its root

**Id:** 4f798011-3707-4fe7-a825-ad2575d6f395
**Type:** decision
**Status:** superseded
**Superseded by:** 3cec0403-a358-440c-81aa-a2be45abf3a4
**Evidence:** confirmed
**Source:** the maintainer's request in the project chat, 2026-10-28 (a sitemap for maity.team and maity.dev for the search console); contract `docs/api.md` §16.7 "Search engines"
**Revisit when:** public projects or discovery pages come (later stage in this file), which would add public URLs worth listing

The hub serves `/robots.txt` and `/sitemap.xml`. While the landing page
is enabled the robots file allows the root, the static files and the
two public reads the page is drawn from, and names the sitemap, which
lists the root; while it is not, the robots file allows only the root,
which says `noindex` (a crawler must be allowed to fetch a page to read
its `noindex`), and there is no sitemap.

**Reason:** the hosted instance wants to be found by its landing page;
a self-hosted or local instance has no public face and should not be
indexed by default. The landing setting already says which of the two
an instance is, so it decides this too, without a second switch.
Everything else the hub serves is behind a sign-in or is a fragment
route a crawler does not fetch.

**Rejected alternatives:**
- Allowing the root alone: the landing page is drawn by scripts from a
  public read; a crawler barred from both sees an empty page.
- A static `robots.txt` and `sitemap.xml` in the repository: they would
  invite indexing of every self-hosted instance, or none of them.
- Listing badges: they are per project and belong to the project's
  owner, not to the instance's public face.

## Public pages are static HTML, chosen by their owner, and the instance's operator must allow them

**Id:** 2571d046-a270-4680-b50a-dc4e9ad60f19
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-28 (public projects and users indexed by search engines; "without JavaScript, could even be static, rebuilt every few hours"); contract `docs/api.md` §16.9
**See:** scope.md#only-an-instance-with-a-landing-page-invites-search-engines-and-only-to-its-root — 4f798011-3707-4fe7-a825-ad2575d6f395 — as of 2026-10-28

A project whose namespace owner turns `public_page` on, and a person who
turns `public_profile` on, get a page under `/p/<owner>/<slug>` or
`/u/<handle>` (since the path-routing decision of 2026-10-29,
e34ae588-4dbc-423c-8da8-29fc62436cb5, at `/<owner>/<slug>` and
`/<handle>`, the dashboard's own addresses): plain HTML rendered by the hub, no script, listed in the
sitemap. The operator chooses whether pages are rendered on every change
(default) or only on an interval of 1–24 hours (default 6); either way
anything taken off a page, any edit of a shown text included, is taken
off at once, and only new entries and counts wait for the interval. The operator switches
the feature on for the instance (`MAITY_PUBLIC_PAGES`); it is off by
default. This brings part of the later stage "public projects and
discovery" forward: the pages, not yet a discovery page or join
requests.

**Reason:** the hosted instance should be found by the projects and
people on it, and the dashboard cannot be indexed: it is drawn by
scripts under fragment routes. A static page per public project and
person is what a crawler reads best and costs the hub one render per
change. Being public is a choice about one's own data, so it is the
owner's alone and off until chosen; an operator of a private instance
must not publish its members by an update.

**Rejected alternatives:**
- Public by default with an opt-out: publishes people and projects who
  never decided to be public.
- Rendering on every request: the same output at the cost of a render
  per crawler visit; a stored page is enough when it is rebuilt on change.
- Only rendering on change, without a choice: the maintainer wanted the
  operator to choose, since an interval batches the work on a busy
  instance.
- Letting the interval delay removals too: a person who makes their
  profile private would stay on other projects' pages for up to a day,
  against their decision; removals are always immediate.
- A fixed interval with no bound: 1–24 hours keeps a page from going
  stale for days or being rebuilt every minute.
- Making the dashboard itself crawlable (server-side rendering of the
  app): the whole app would have to render without a session for a
  handful of public facts.
- Any co-owner turning a project's page on or writing its text: the
  page is published under the namespace owner's name, so the namespace
  owner decides; a transfer turns it off for the same reason.
- Redirecting a former handle or slug to the public page: it would
  publish for good that two names belong together.
- Listing every agent of a public project: agents of other owners and
  their activity would be published by someone else's choice; they show
  only with their owner's public profile, the rest as a number (the
  separate `swarm_public` switch is gone, see projects.md bfe4c4a6).

## A public project shows Overview, Board, Members, Organisation and Why; agents get pages under their owner; a person's links are theirs to show

**Id:** 3b57164a-c675-4646-a026-237f96e4df54
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions of 2026-10-29 (which views are public, agents under the person's page; card tsk-w89mspg3gwx1) and 2026-10-30 (a person's website and social names, who sees them: five values, independent; card tsk-xr6fqx8e0vw5); the details (card fields, links built from names, no single-card page) are the contract owner's; contract `docs/api.md` §16.9
**Revisit when:** follow exists (the `friends` value starts to mean something), a public card page is wanted, or the Why view should show a private repository's entries by an owner's choice

A public project shows five of its views to anyone, each a stored
page at the view's own address: Overview, Board, Members, Organisation
and Why. Inbox, Chat, Messages and Ticker stay with the members, Runners
and Settings with the owners. The Board shows each card's id, title,
status and label, never its body, notes or history, and has no page per
card. People and agents appear by name only where the person (or the
agent's owner) has a public profile, otherwise as "a member"/"an agent"
or an unnamed box. Why shows only what the hub already reads of Keep
the Why (summary, dashboards, attention; never `context/`), and only
while the repository is public, read with the instance's token. A
person's links are built from validated names, never stored as URLs. An agent has a page under its owner's
(`/{owner}/agents/{handle}`) with its statistics over the public
projects. A person sets a website and their names on seven networks;
the hub builds the links from the names, and the person chooses who sees
them: private, friends, colleagues, friends and colleagues, or everyone.

**Reason:** the maintainer wants a public project to show how it is
being built, not only that it exists; the board and the team are that.
What a card says inside, and what people discuss, stays with the team.
Names follow each person's own choice, so publishing a project does not
publish its people. Building links from names, instead of taking URLs,
keeps a "GitHub" link from pointing anywhere else.

The Board shows the open columns (at most 200 cards each) and only the
last 30 days of `done` and `cancelled`, so a public board shows the work
in hand rather than the project's whole history; the statistics count
only the public projects an agent is in. A card under a moderation hold
is not on the Board at all, a `remove` that cancels it included.
`colleagues` are the humans of a shared project only, since agents
would carry a person's links into their own contexts; a website is a
DNS host, never an IP address or a port.

**Rejected alternatives:**
- A public page per card: it would publish card bodies and history, the
  part that is the team's working text.
- Every done card on the Board, and statistics over every project: the
  first makes the page a history, the second counts private work.
- A moderated card shown as `cancelled`: the title is what was moderated.
- Agents among the `colleagues`: a person's links would travel into
  agents' contexts by someone else's membership.
- Free URLs for the social links: a label could point to any site.
- Cumulative visibility levels (colleagues including friends): the
  maintainer chose independent values with "friends and colleagues" as
  its own option.
- Showing Why from a private repository through an owner's grant: the
  grant reads for the team, not for the public (§11.4).

## The landing and legal pages are instance content in sections, rendered by the hub as static HTML

**Id:** cd44707b-7b79-47ae-a78d-586195d465dc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's direction to the designer, 2026-10-28 (a full landing page, as plain HTML like the public pages, live numbers, a way into sign-in and registration; imprint, privacy notice and terms of use); the designer's section list (Maity, 2026-10-28); contract `docs/api.md` §16.7, §16.7.1
**See:** scope.md#what-one-instance-says-about-itself-lives-in-its-database-not-in-the-repository — eec53587-3465-48d8-9c7e-ae24e05e7172 — as of 2026-10-28

What an instance says about itself still lives in its database, written
by its admin, never in the repository. The landing page is now a list
of typed sections (hero, stats, steps, scales, FAQ, text, …) per
language instead of one Markdown block, and the hub renders it itself
as one static HTML page at the root for visitors without a session; the
dashboard moves to `/app` for them, `/login` and `/register` always
reach it, and a tiny script carries old `/#/…` links over (both removed
by the path-routing decision of 2026-10-29,
e34ae588-4dbc-423c-8da8-29fc62436cb5: `/` serves the landing page or the
app shell, and the page has no script; since 2026-10-30 a first-party
script improves it but is never needed, e6abaa96-ef56-4c12-bd09-dd0e5f6c9c37). The imprint,
privacy notice and terms of use are three more pages of the same kind,
versioned, and the terms page feeds the acceptance at registration.
Live numbers are computed every five minutes; an online count below
five is left out of the page (until 2026-10-31 it showed as "< 5", which
next to a small total such as "2 people" read as a contradiction; the
maintainer pointed it out on the live page).

**Reason:** the maintainer wants a full landing page that works without
script and is found by search engines, and legal pages before opening
registration. One rendering path in the hub keeps the page, the public
pages and the legal pages alike and readable by crawlers. Versioned
terms make the accepted version the one the person could read.

**Rejected alternatives:**
- Keeping one Markdown block: too little for a page with steps, numbers
  and questions, and still drawn by script.
- Legal pages as static files in the repository: the operator's name
  and address are instance content, not code.
- Exact small online numbers: with few people, a number like 1 points
  at a person.

## Search engines may read the landing and legal pages; the rest stays as before

**Id:** 3cec0403-a358-440c-81aa-a2be45abf3a4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** follows from cd44707b; contract `docs/api.md` §16.7 "Search engines"
**See:** scope.md#only-an-instance-with-a-landing-page-invites-search-engines-and-only-to-its-root — 4f798011-3707-4fe7-a825-ad2575d6f395 — as of 2026-10-28

While the landing page is enabled, `robots.txt` allows the root and the
legal pages that are set, and the sitemap lists them (plus the public
pages while those are on); while it is not, only the root with
`noindex`, as before. The dashboard's scripts and the public reads no
longer need to be allowed, because the hub renders the page. Since
2026-10-30 `/assets/landing/` is allowed again, but only so a crawler
that renders the page gets its style, script and fonts; every word stays
in the HTML (e6abaa96-ef56-4c12-bd09-dd0e5f6c9c37).

**Reason:** the page a crawler should read is now plain HTML; allowing
script files was only ever a workaround for a page drawn by script.

**Rejected alternatives:**
- Leaving the old allow list: it would invite crawlers into files that
  no longer carry the words.


## The landing page is enhanced by a first-party script and fonts from the code, never needed to read it

**Id:** e6abaa96-ef56-4c12-bd09-dd0e5f6c9c37
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go for the full landing V3, 2026-10-29 (through the designer, card tsk-3hn1xcgf168j), and his wish of 2026-10-30 to ship a first stage early; contract `docs/api.md` §16.7
**See:** scope.md#the-landing-and-legal-pages-are-instance-content-in-sections-rendered-by-the-hub-as-static-html — cd44707b-7b79-47ae-a78d-586195d465dc — as of 2026-10-30
**See:** scope.md#search-engines-may-read-the-landing-and-legal-pages-the-rest-stays-as-before — 3cec0403-a358-440c-81aa-a2be45abf3a4 — as of 2026-10-30
**See:** https://github.com/oliver-zehentleitner/maity — 7b1e4c52-5a86-4f0e-9d3b-0c2a6e8f1d47 — as of 2026-10-30

The landing page keeps its content in the database and its whole text
in the HTML the hub renders. Its design is code, the same on every
instance: a stylesheet, a script of at most 10 KiB loaded with `defer`,
self-hosted fonts and inline SVG, all served from `/assets/landing/`
with a digest in the URL. The script adds motion, the demo's typing and
a theme switch, reads only the page itself and makes no request; under
reduced motion everything shows its end state. The policy allows
script, style, fonts and images from the hub only, and no connection.
The hub's own entry on the landing documents (7b1e4c52 in
`hub/context/landing.md`, a page with no script) has its `Revisit
when` met by this decision and is updated with the build (card
tsk-m6ew67r1w3hc). The first stage adds the `demo` and `opensource`
sections and shows the FAQ as `<details>`; a public activity feed and agents among the
profiles come later with their own contract change.

**Reason:** the designed page lives from motion (the rings, the typed
demo) that plain HTML and CSS cannot carry everywhere, and the
maintainer wants that look; keeping every word in the HTML keeps the
page readable without script and by crawlers, which was the reason for
the static page in the first place. First-party files only keep the
policy closed to anything the operator or a visitor could inject.

**Rejected alternatives:**
- No script at all, CSS animation only: the demo's typing and the
  theme switch need state, and CSS-only typing breaks with real text.
- Fonts and scripts from a CDN: a request to a third party on every
  visit, and a policy that has to allow it.
- Design values (colours, fonts) as settings of the instance: the look
  is one product's, and every setting is one more thing an operator can
  break; content stays the operator's, design stays code.
- Rendering the page in the browser from `GET /landing`: crawlers and
  visitors without script would see nothing.

## The landing header links only the sections that carry a short `nav_label`, at most four

**Id:** 7817872f-1876-40b2-8ec8-7ee4e2802991
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the designer's review of the live landing page against the board, 2026-10-31 (header wrapping to two lines with five long section titles as links, the mobile header stacking them); contract `docs/api.md` §16.7
**See:** scope.md#the-landing-and-legal-pages-are-instance-content-in-sections-rendered-by-the-hub-as-static-html — cd44707b-7b79-47ae-a78d-586195d465dc — as of 2026-10-31

A section may carry `nav_label` (1–24 characters); the header links
exactly the enabled sections that have one, in their order, at most four
per page. A section title is never a link text by itself.

**Reason:** with every section title as a header link, the header wrapped
to two lines on a desktop and stacked on a phone, pushing sign-in and the
call to action out of the first line. Short labels written for the header
keep it on one line in every language, and the operator decides which
sections are worth a link.

**Rejected alternatives:**
- Section titles as links (the state before): too long, and the number of
  links grew with the page.
- A fixed list of links in the template: the template has no words of its
  own for an instance's page in every language, and the operator could
  not choose.

