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
instance adds limits per account, and no ordinary member can list other
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
they are switched on by configuration. Still open: whether limits count
per person or per project.
