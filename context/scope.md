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

## One codebase, three ways to run it: alone at home, a team's own instance, and an open hosted instance with paid plans

**Id:** 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's direction in the project chat, 2026-10-23 (earlier brainstorming outside the repository had not reached it)
**Revisit when:** the open hosted instance needs something the self-hosted ones must not carry (then it becomes a module, not a fork)

Maity is to run in three ways — the agreed target; today's code has the
first, and registration, plans and payment are still to be specified
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
  as a multi-tenant service and a trial: anyone registers into a free
  plan to try it, and someone who wants more without hosting buys a
  larger plan. Plans are defined by the operator (limits such as agents
  and projects per account, and a price); payment is an optional module
  (a subscription provider or a payment link), off by default.

Every person sees only the projects they belong to, as before; the open
instance adds plan limits per person, and no ordinary member can list other
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
chooses; an account over its limit after a downgrade keeps what it has
and creates nothing new (the tolerant default), and the operator has an
emergency brake per account or for all — pausing the agents over the
limit or making an account read-only — which is logged and told to the
person affected. Opening an instance and plans are never the default;
they are switched on by configuration. Limits count per person: each
pays for their own agents and projects, with a small free plan (for
example up to 3 agents). A project owner may buy additional quota (plans
and prices are the operator's) and hand parts of it to members of their
project — sponsoring, say, three more agents for someone on the free
plan; whether a project allows this is a per-project setting.

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
**Revisit when:** the per-member cost model of the hosted offering changes, or a customer asks for hub-side execution and is willing to carry its cost as a separate plan
**See:** scope.md#a-runner-the-operator-runs-may-start-agents-the-hub-still-never-does — 6f8d6d1b-31fa-408c-be43-f0da404084bb — as of 2026-10-25
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance-with-paid-plans — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

The hosted offering (maity.team) runs no agent workloads. Runners stay
on the members' own machines, never in hub-side worker pods. The hub is
a switchboard: it stores cards, messages, events and decisions and wakes
whoever has to act; everything heavy — the agent sessions, their
repositories, their inference — stays with the customer. This narrows
the runner decision above for the hosted instance: an operator-run
runner may start agents, but the hosted operator runs none.

**Reason:** the per-member cost of the hosted instance must stay in the
cents, so that a free tier carries itself and the paid plans price
coordination, not compute. A hub that ran agents would have a cost that
scales with agent runtime and model usage, which neither a free tier nor
a per-seat plan can carry.

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

## The beta is free; later plans price humans and organisations, never agents; one hard ceiling of agent profiles per human protects the hosted instance

**Id:** 37803db9-3f8a-4a1a-b42f-20ba9c783e1f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25; the ceiling in `docs/api.md` §16.5
**Revisit when:** plans (§2.7 part two) are specified — then the ceiling becomes a per-plan value and this entry is superseded by the plans entry
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance-with-paid-plans — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

The public beta of the hosted instance has no subscriptions. When
plans come, they price what organisations need — private orgs and
teams, roles and policies, audit and reporting, single sign-on,
support — and never the number of agents or sessions; local and
self-hosted use stays free. Price tiers and conversion figures stay out
of the repository, and so does the configuration of the plans
themselves — what each includes, its limits, its price is instance data
in the hosted instance's database, never shipped to local or
self-hosted installations. Independent of plans, the instance operator
sets one ceiling: agent profiles per human (default 100), against
runaway creation; lowering it deletes nothing.

**Reason:** an agent is the user's tool, and charging per tool would
punish exactly the use Maity exists for — many small agents, freely
created and discarded. The ceiling is not a price: it is the one number
that keeps a script or a mistake from filling the hosted instance, set
high enough that nobody working alone meets it.

**Rejected alternatives:**
- Seats per agent or per session: the hub would tax the thing it wants
  to make cheap.
- No ceiling at all on the hosted instance: one runaway script could
  create profiles without end; self-hosted instances may switch it off.
- A ceiling per project instead of per human: that is the project
  owner's policy (`max_placements`), not the operator's protection.

## Usage is measured by counting what the hub already holds, never by tracking

**Id:** 02f126c2-5d8c-4ea4-89bd-ceb499efd24d
**Type:** constraint
**Status:** active
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

## What one instance says about itself lives in its database, not in the repository

**Id:** eec53587-3465-48d8-9c7e-ae24e05e7172
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's direction in the project chat, 2026-10-25; contract `docs/api.md` §16.7
**Revisit when:** an instance needs more than one page of its own (then a small content store, still in the database), or a theme beyond the uploaded logo and banner
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance-with-paid-plans — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-25

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
