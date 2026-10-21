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
