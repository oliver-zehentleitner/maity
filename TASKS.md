# Tasks

Open work. One block per agent. Done items are deleted, not ticked. Items
that need the maintainer are marked **[maintainer]**.

## Maintainer

- **[maintainer]** Confirm the team for the MVP: Agent A as head (coordination, review, merge, `context/`), coding agents B (`hub/`), C (`cli/` + skill), D (`web/`) and their models; the maintainer starts the local sessions.
- **[maintainer]** Clarify the security requirement "end-to-end encryption": transport security plus signed, replay-proof requests (the agent's reading), or payloads the hub itself cannot read (which the dashboard and the admin roles could not work with).
- **[maintainer]** Pull requests are merged by the maintainer (the agent account's merges are blocked by its harness); or grant the agent a permission rule for `gh pr merge`.

## Agent A (coordination, review, `context/`)

- `docs/security.md` (threat model, credentials, request signing and replay protection, the stored-verifier cost, access-log rule: codes and credentials never in URLs); `docs/install/` for plain Python, Docker Compose and Helm on Kubernetes; `docs/agents.md` as the agent-facing guide the join page and `/help` are built from.
- Review PR #4 (cli) and PR #5 (web) against `docs/api.md`; hand PR #3 to the maintainer after the password-path fixes.
- Add the `children` blocks for `hub/`, `cli/`, `web/` to `.keep-the-why` when the directories exist and have owners.

## Agent B (`hub/`)

- Batching the board's per-card lookups after a measurement.
- Signed requests mandatory per project, later (a project setting; bearer stays for the page-driven join).
- Before the events slice: the long-poll as `async` on an in-process event with database access off the event loop; recorded in `hub/context/` first.
- MySQL 8 in CI if a difference to MariaDB shows up (`hub/context/testing.md`).
- Dependency update automation for `hub/requirements/`: Renovate or Dependabot on the uv-compiled files. Advisories are caught by the `audit` workflow; the bump itself is still manual (`make lock-upgrade PACKAGE=<name>`, hub/README.md "Dependencies").
- **[maintainer]** The first push of the hub image to ghcr.io (`publish-image`: a `v*` tag or a manual run); then the chart can default `image.repository`. Publishing the chart itself is still open.

## Requirements collected so far (not yet designed)

- Join by pasting a short text into any running agent session; pairing with the hub; the agent then knows who it is, what to do and how the system works.
- Every agent can message every other member; a task board per project.
- An admin crew of agents (manager, reviewer, Keep the Why steward) orchestrates the others and is the maintainer's interface; it owns checklists, including release management: which pull requests must be merged before a release fits together.
- One account, many projects: the human switches between projects in the dashboard, and sees from anywhere — a project switcher with counts, and one cross-project view of everything that waits for them — when a project needs them, so they can switch to it. `GET /me` carries the memberships with the number of open requests per project.
- The human can chat with the agents they own, from the dashboard: a direct conversation per agent, delivered to the agent as events it picks up with `wait`/`resume`; the inbox stays the primary surface, the chat is the channel beside it.
- A decision inbox for the human: what each agent wants, sortable by priority, date and agent; answered by yes/no, a prepared reply or free text; delivered to the agent by push, by polling, or both.
- Organisation models (hierarchical, decentral, autonomous pool, hybrid) as switchable profiles, visible in an org chart.
- Other people can be invited; they bring their own agents and get responsibilities and rights.
- The API has a `/help` an agent can query for everything it needs to know about the hub and its operations — the API describes itself to its agent users.
- Keep the Why optional per project, external, never reimplemented in the hub.
- Project state (build / freeze / fixes-only / accepted / archived) as a setting on the project, visible in every agent payload; a freeze is a checkbox, not a sentence.
- Absence mode for the human: away until a time, with a one-line scope of what the admin roles may decide meanwhile.
- Versions follow Semantic Versioning; whether the admin crew tags alone or a human gives the go is a project setting; "may tag" is a capability granted per membership.
- The Keep the Why steward may write `context/` entries itself or open cards for the owners; owner preferred, self when needed, configurable per project.
- Invitations for further humans come after the first dogfooding week (the maintainer starts alone).
- Requests from agents are signed and replay-proof (nonce, timestamp, idempotency key on state-changing calls); credentials hashed at rest, revocable per session.
- Idea to design: the project's Keep the Why dashboard export (`state.json`, the static page) shown inside the Maity dashboard as a read-only panel — counts on the project card, the page embedded, entries waiting for confirmation surfaced in the inbox; the hub reads the published export and never touches `context/`. Generalise to a panel plugin interface only if a second panel appears.
