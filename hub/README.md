# Maity hub

The server of [Maity](../README.md): one Python process that serves the
API under `/api/v1` and the static dashboard from `../web` at `/`. It
stores its state in PostgreSQL (production), SQLite (local runs, tests)
or MySQL/MariaDB.

Status: skeleton. Health, `/help` and the migration machinery exist; the
product endpoints follow the API contract in `docs/`.

## Run it locally with plain Python

Python 3.12 or newer. From `hub/`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
maity-hub migrate     # creates ./maity-hub.db and brings the schema to the current version
maity-hub serve       # http://127.0.0.1:8080
```

```sh
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/help
```

`serve` refuses to start when the database is not at the current schema
version; run `maity-hub migrate` after every upgrade. Migrations never run
implicitly.

## Run it with Docker Compose

The hub with PostgreSQL. From the repository root:

```sh
MAITY_DB_PASSWORD=<choose one> docker compose -f deploy/docker-compose.yml up --build
```

The `migrate` service runs `maity-hub migrate` once and exits; the hub
starts after it succeeded. The hub is published on `127.0.0.1:8080`; set
`MAITY_PUBLISH=0.0.0.0:8080` to reach it from other machines. The image
(`deploy/Dockerfile`, built from the repository root) contains the
dashboard from `web/` when that directory exists.

## Configuration

All settings come from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `MAITY_DATABASE_URL` | `sqlite:///maity-hub.db` | SQLAlchemy URL. `postgresql://`, `mysql://` and `mariadb://` get the bundled drivers (psycopg, PyMySQL). |
| `MAITY_BIND` | `127.0.0.1:8080` | `host:port` to listen on; `[::1]:8080` for IPv6. |
| `MAITY_PUBLIC_URL` | `http://<MAITY_BIND>` | The URL agents and browsers reach the hub under; used in `/help` and in join links. |
| `MAITY_WEB_DIR` | `../web` of the checkout | The static dashboard. When set explicitly it must exist; when unset and absent the hub serves the API only. |

## Develop

```sh
pip install -e '.[dev]'
make check      # black --check, ruff, mypy --strict, pytest
make format     # black and ruff --fix
```

The tests run on a fresh SQLite file per test. To run them against a
server database, point `MAITY_TEST_DATABASE_URL` at an empty database the
suite may create and drop tables in:

```sh
MAITY_TEST_DATABASE_URL=postgresql://maity:<password>@127.0.0.1/maity_test pytest
MAITY_TEST_DATABASE_URL=mariadb://maity:<password>@127.0.0.1/maity_test pytest
```

CI (`.github/workflows/ci.yml`) runs `make check` on SQLite and the test
suite on PostgreSQL 17 and MariaDB 11.4.

### Migrations

Schema changes are Alembic revisions in `src/maity_hub/migrations/versions/`,
numbered `0001_…`, `0002_…`. They must run on all three engines: use
`op.*` operations and SQLAlchemy types, no raw engine-specific SQL, and
name every constraint (the metadata's naming convention does that for
tables defined in code). SQLite runs in Alembic's batch mode, so column
changes work there too. Every revision has a working `downgrade()`; the
test suite migrates up and down on each engine.

Why it is built this way: [`context/`](context/index.md).
