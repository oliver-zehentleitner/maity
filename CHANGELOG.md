# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/).

Keep a Changelog records what changed. Why it changed is in [`context/`](context/index.md).

## [Unreleased]

### Added

- `docs/architecture.md` and `docs/api.md`: the architecture and the REST contract v1 the hub, the CLI and the dashboard build against.
- Repository scaffold: README, licence, contributing guide, agent entry point,
  task board, Keep the Why configuration with linter and dashboard workflows.
- hub: server skeleton — `maity_hub` package with `maity-hub serve` and
  `maity-hub migrate`, settings from the environment, Alembic baseline
  portable across PostgreSQL, SQLite and MySQL/MariaDB, `GET /api/v1/health`,
  `GET /api/v1/help` (Markdown), the dashboard served from `web/` at `/`
  without dotfiles; `make check` and `make revision`; CI on SQLite,
  PostgreSQL, MariaDB, the built wheel and the image; Dockerfile and Docker
  Compose with PostgreSQL in `deploy/`.
- hub: the V1 data model — tables for humans, agent profiles, dashboard
  sessions, projects with their policy, memberships, join links,
  credentials, agent sessions, idempotency keys, cards and their edges,
  requests, events, chat delivery and read state, forge observations —
  and migration `0002`, tested on SQLite, PostgreSQL and MariaDB.
- cli: `maity` — `join`, `resume`, `wait`, `report`, `ask`, `api`, `help` against
  the v1 contract, every request HMAC-signed with an idempotency key; the
  credential stored per clone under the Git common directory (mode 0600, never
  printed), credential-shaped payloads refused before sending; `report` refuses
  on any mismatch between git, the remote and the pull request; the pointer
  block in `AGENTS.md`; redirects refused, git and gh run without prompts and
  with a timeout; `wait` never runs past its `--timeout`, even when the hub stops
  answering; the agent skill in `cli/skill/maity/SKILL.md`.
- cli: `claim`, `unclaim`, `checkpoint` (branch and head from git), `say` (typed
  messages, and `say human` for the chat with the agent's human), `answer`, and
  `release list|show|tick`; `--json` on these and on `ask` and `report` prints
  the hub's answer; an `invalid` answer lists each field with its reason code.
- ci: a `cli` job runs `make check` in `cli/` on Python 3.10 and 3.13.
- ci: the `audit` workflow runs pip-audit (pinned with hashes in `hub/requirements/tools.txt`)
  against all four hub locks on every push to main, every pull request and daily.
- docs: `docs/join-page.md`, the join page template the hub serves.
- docs: `docs/install/`, the entry page for self-hosters: which of the three paths
  when, TLS and `MAITY_TRUSTED_PROXIES` per path (the same-host proxy trap), the
  first account, project and agent, backups per engine, upgrades without downgrade.
- docs: `docs/agents.md` gains "Staying on duty, per harness": foreground limits,
  background wake-ups and a `maity wait` recipe for Claude Code, Codex, opencode, pi,
  Hermes, Kimi Code, Cline CLI and oh-my-pi, read from each one's source and docs.
- docs: `docs/agents.md`, the handbook for an agent that joined and its human: the
  daily loop, exit codes, the rules, waiting on a harness, the path without the CLI,
  troubleshooting; the join page, the skill and the README point to it.
- web: dashboard skeleton against fixtures — a project switcher with open
  counts on every screen and an inbox across all projects; per project the
  inbox, board, agents and presence, organisation tree, chat with owned
  agents, sign-in and sign-out, project state and absence, pausing agents,
  and the join line for a new agent, in the shapes of `docs/api.md`; a
  fetch layer that reads fixtures on `file://` only and `/api/v1`
  otherwise; `make check` on the Python standard library and `make smoke`
  on a bare node binary, both in a `web` CI job; Keep the Why for `web/`
  as a child of the root.
- web: create a project (`#/new`, `POST /projects`) with field errors from the hub,
  reachable from the switcher and from the empty state of an account without projects
- web: refresh from the project's events (`after=latest`, then `wait=0` every 5 s):
  reload offers on the board, agents and organisation, chat replies from the feed,
  presence re-read in place; the "what waits for you changed" notice now appears
  (the count re-read had marked itself as seen)
- web: fixtures label the consent replies `go` and `no`, as the hub sends them
- web: a browser end-to-end test (`web/tools/e2e.py`, CI job `web-e2e`): headless
  Chromium against a real hub on SQLite, the agent through the `maity` CLI, from
  sign-in to the answer that wakes `maity wait`, with a screenshot of every step
- web: first-time hints: the empty inbox and board say where their content comes from,
  the join line says where to paste it, the board's subtitle says that open cards are
  all shown, a tab row wider than the screen fades where more tabs are, and an inbox
  with nothing open on screen reloads on its own when a request arrives
- web: release cards against the hub's §6.7: a typed or reported PR state is shown as an
  unverified claim, a PR the forge does not have as such (`found`, `pr_not_found`), the
  `ships_with` groups, every readiness reason in words, an honest note when the project
  has no forge probe, a closed release as its frozen record; contract cards show their
  watchers
- hub: the API conventions and authentication of `docs/api.md` §1–§2 —
  error envelope with `Maity-Error`, `Maity-Server-Time`, no-store and
  nosniff on every response, the 64 KiB body cap, refusal of credential-
  shaped strings with revocation of a verified leak; human login with
  scrypt, session cookies and `X-CSRF-Token`; agent bearer credentials over
  TLS and HMAC-signed requests with a nonce window; `Idempotency-Key`;
  `MAITY_TRUSTED_PROXIES` and `MAITY_ALLOW_PLAIN_HTTP`; `GET /me` with open
  requests per project; `maity-hub owner create`; `/health` errors as the
  envelope (`database_unavailable`, `schema_outdated`); `500 internal` in the
  envelope; the hub's own request log without query strings or join tokens.
- hub: projects with state, policy presets, absence and generated rules
  (`rules_changed`), members with presence, pause and removal, agent
  profiles, join links with the join page (Markdown, or HTML for a browser)
  and the single-use exchange, the resume packet, `PATCH /me`, credentials
  list and revoke (`docs/api.md` §3, §5.2, §5.3, §6.1–§6.3, §6.9, §10); a
  join smoke script and CI job for the curl and the CLI path.
- hub: cards on the board (`docs/api.md` §6.4–§6.6) — create with area
  routing, edit, the transition table, `depends_on` without cycles and
  mirrored `ships_with`, `done` refused with open dependencies, the paged
  board; the atomic claim with leases, release, assign, the freeze and
  fixes-only reason; checkpoints and completion reports with
  `verification: signed|bearer`.
- hub: requests to humans (`docs/api.md` §7) — the four classes with
  options and computed replies, addressing by member, role or owner with
  the defaults, consent only to and from answering roles, `on_behalf_of`,
  `needs_in_session`; the inbox with its defaults, filters, three sorts and
  paging, and `GET /requests` across projects; answers by `reply_id`, text
  or `talk` with the answer rights, `self_answer`, `on_behalf_of`;
  withdrawal; cards blocked while a request waits and restored after; the
  resume packet's requests; the smoke script asks and answers on both
  join paths.
- hub: events (`docs/api.md` §8, §9) — reading with the cursor and its
  acknowledgement, `after=latest`, the long-poll that waits in-process and
  wakes on the readable events addressed to the reader, one long-poll per
  credential with `superseded`, `listening` in presence; messages to
  members, roles or all; redaction with its own event; the human's
  conversations with its agents, with delivery and unread counts; the
  smoke script waits and wakes on both join paths.
- hub: the tested dependency set pinned with hashes in `hub/requirements/`
  (runtime, dev, build backend, uv), generated by `make lock` /
  `make lock-upgrade` with `uv pip compile --universal`; the image and every
  hub CI job install from it, `make lock-check` in CI keeps it in step with
  `pyproject.toml`.
- deploy: a Helm chart for the hub (`deploy/helm/maity-hub`) — one pod
  replaced with `Recreate`, `maity-hub migrate` as a pre-install/pre-upgrade
  hook Job, the database URL and the forge token from existing Secrets, an
  optional Ingress with TLS and long-poll timeouts, a NetworkPolicy that
  admits only the ingress controller's namespace, readiness on
  `/api/v1/health` and liveness on `/api/v1/help`, a values schema that
  refuses unknown keys, refusals for an Ingress without trusted proxies and
  for plain HTTP outside the cluster, `helm test`; `deploy/helm/check.sh`
  and `deploy/helm/kind-smoke.sh` in CI.
- hub: release and contract cards (`docs/api.md` §6.7, §6.8) — SemVer
  versions unique per project with one release in flight; the release
  object with reported and typed pull requests, `ships_with` groups
  followed over all edges (a partner outside the release blocks), the
  checklist seeded from the project settings, edited by `PATCH` and ticked
  through its own endpoint; readiness computed from observed forge state
  only and on the data as it will be stored, `false` with
  `probe_not_configured` without a forge token, `done` refused with
  `release_not_ready`, `release_ready` announced once per turn to ready,
  also by the write that closes it; a closed release is a record, not
  edited and with its pull requests, groups and readiness frozen at the
  close; `ships_with` never names a release card; contract cards with arbiter and
  watchers, another arbiter than the policy's named only by an admin,
  `final` only by the arbiter or an admin.
- hub: the resume packet shows the agent's own pause as `membership.paused`
  (`docs/api.md` §5.2).

### Fixed

- hub: `hints.wait_timeout` per harness below its command kill, with the names agents write (Cline 25, opencode 110, Hermes 170, Kimi 280, oh-my-pi 290, Claude Code 540, others 600); Cline's 240 outlived its 30 s kill.
- hub: the lock tooling pins uv 0.13.5, past GHSA-hq85-5cpj-mr62 (a compromised root in the bundled CA store, fixed in 0.13.4).
- hub: an agent credential is scoped to its own project (`docs/api.md` §2.2); any other project answers `not_found`.
- hub: the join smoke script reads a token that starts with `-` as text, and its check that the join page never shows the code can fail at all.
- web: the handle and slug fields validate in the browser again: their `pattern` had an
  unescaped `-` in a class, which browsers compile with the `v` flag and drop as invalid
- web: a join for a new agent profile names that profile in the list of joins and
  offers it in the agent select, instead of showing its id until the view is reloaded
- web: at phone width a credential's or join's Revoke button keeps its label on one line,
  and a credential's id, client and dates wrap as one text beside it
- web: a request id on a blocked card no longer breaks at its hyphen
- web: at phone width a form's select no longer widens the page past the screen when an
  option is long (the join view's agent list, the create view's presets)
- web: a join whose list cannot be re-read afterwards says it was created, not "No join created"
- web: the project switcher's state dot shows the state's colour; a later `.dot` rule
  had made every dot grey
- web: an open chat updates "not picked up yet" to "reached a session" on the agent's
  next event or when the window gets the focus back, instead of only after a reload
- web: on a narrow screen the current tab and project are scrolled into their rows;
  the 15-second count re-read redraws only the switcher, so it no longer closes an
  open State & absence panel with what was typed in it, nor resets a scrolled tab row
