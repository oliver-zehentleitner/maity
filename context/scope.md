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
