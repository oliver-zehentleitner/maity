# Tasks

Open work. One block per agent. Done items are deleted, not ticked. Items
that need the maintainer are marked **[maintainer]**.

## Maintainer

- **[maintainer]** Decide the team: how many coding agents, which models, which directories they own (proposal from Agent A pending the design synthesis).

## Agent A (coordination, review, `context/`)

- Finish the design synthesis from the lasteverLM experiment and discuss it with the maintainer: join protocol, wake-up per harness, token handling, inbox request model, organisation-model policies, release gate, claims and leases, event log, stack.
- Turn the agreed design into `docs/architecture.md` and the first API contract.

## Requirements collected so far (not yet designed)

- Join by pasting a short text into any running agent session; pairing with the hub; the agent then knows who it is, what to do and how the system works.
- Every agent can message every other member; a task board per project.
- An admin crew of agents (manager, reviewer, Keep the Why steward) orchestrates the others and is the maintainer's interface; it owns checklists, including release management: which pull requests must be merged before a release fits together.
- A decision inbox for the human: what each agent wants, sortable by priority, date and agent; answered by yes/no, a prepared reply or free text; delivered to the agent by push, by polling, or both.
- Organisation models (hierarchical, decentral, autonomous pool, hybrid) as switchable profiles, visible in an org chart.
- Other people can be invited; they bring their own agents and get responsibilities and rights.
- The API has a `/help` an agent can query for everything it needs to know about the hub and its operations — the API describes itself to its agent users.
- Keep the Why optional per project, external, never reimplemented in the hub.
