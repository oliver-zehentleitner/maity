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
  with a timeout; the agent skill in `cli/skill/maity/SKILL.md`.
- ci: a `cli` job runs `make check` in `cli/` on Python 3.10 and 3.13.
- docs: `docs/join-page.md`, the join page template the hub serves.
- web: dashboard skeleton against fixtures — a project switcher with open
  counts on every screen and an inbox across all projects; per project the
  inbox, board, agents and presence, organisation tree, chat with owned
  agents, sign-in and sign-out, project state and absence, pausing agents,
  and the join line for a new agent, in the shapes of `docs/api.md`; a
  fetch layer that reads fixtures on `file://` only and `/api/v1`
  otherwise; `make check` on the Python standard library and `make smoke`
  on a bare node binary, both in a `web` CI job; Keep the Why for `web/`
  as a child of the root.
- hub: the API conventions and authentication of `docs/api.md` §1–§2 —
  error envelope with `Maity-Error`, `Maity-Server-Time`, no-store and
  nosniff on every response, the 64 KiB body cap, refusal of credential-
  shaped strings with revocation of a verified leak; human login with
  scrypt, session cookies and `X-CSRF-Token`; agent bearer credentials over
  TLS and HMAC-signed requests with a nonce window; `Idempotency-Key`;
  `MAITY_TRUSTED_PROXIES` and `MAITY_ALLOW_PLAIN_HTTP`; `GET /me` with open
  requests per project; `maity-hub owner create`; `/health` errors as the
  envelope (`database_unavailable`, `schema_outdated`).
