# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/).

Keep a Changelog records what changed. Why it changed is in [`context/`](context/index.md).

## [Unreleased]

### Added

- Repository scaffold: README, licence, contributing guide, agent entry point,
  task board, Keep the Why configuration with linter and dashboard workflows.
- hub: server skeleton — `maity_hub` package with `maity-hub serve` and
  `maity-hub migrate`, settings from the environment, Alembic baseline
  portable across PostgreSQL, SQLite and MySQL/MariaDB, `GET /api/v1/health`,
  `GET /api/v1/help` (Markdown), the dashboard served from `web/` at `/`;
  `make check`, CI on SQLite, PostgreSQL and MariaDB; Dockerfile and Docker
  Compose with PostgreSQL in `deploy/`.
