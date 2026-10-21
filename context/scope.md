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
