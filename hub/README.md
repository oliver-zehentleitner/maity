# Maity hub

The server of [Maity](../README.md): one Python process that serves the
API under `/api/v1` and the static dashboard from `../web` at `/`. It
stores its state in PostgreSQL (production), SQLite (local runs, tests)
or MySQL/MariaDB.

Status: skeleton. Health, `/help` and the migration machinery exist; the
product endpoints follow once the API contract (`docs/api.md`) exists.

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
echo 'MAITY_DB_PASSWORD=<choose one>' > deploy/.env
docker compose -f deploy/docker-compose.yml up --build
```

`deploy/.env` is ignored by Git and keeps the password out of the shell
history. Use only letters, digits and `-_.~` in the password, nothing
else: Compose hands the same value to PostgreSQL as it is and to the hub
inside a URL, so a character that needs percent-encoding cannot be right
for both. Compose also interpolates `$` in `.env` values.

The `migrate` service runs `maity-hub migrate` once and exits; the hub
starts after it succeeded and reports healthy once `/api/v1/health`
answers. The hub is published on `127.0.0.1:8080`. To reach it from other
machines, set both in `deploy/.env`: `MAITY_PUBLISH=0.0.0.0:8080` and
`MAITY_PUBLIC_URL` to the address the others use (`http://<host>:8080`),
since the public URL ends up in `/help` and in join links.

## Run the image on its own

```sh
docker build -f deploy/Dockerfile -t maity-hub .
docker run --rm -v maity-data:/app/data maity-hub migrate
docker run -d -v maity-data:/app/data -p 127.0.0.1:8080:8080 maity-hub
```

Without `MAITY_DATABASE_URL` the image uses SQLite in `/app/data`, a
volume owned by the hub's user (uid 10001). The image contains the
dashboard from `web/` when that directory exists at build time; dotfiles
and `node_modules` are never copied.

## Configuration

All settings come from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `MAITY_DATABASE_URL` | `sqlite:///maity-hub.db` (image: `sqlite:////app/data/maity-hub.db`) | SQLAlchemy URL. `postgresql://`, `mysql://` and `mariadb://` get the bundled drivers (psycopg, PyMySQL). Reserved characters in any part of the URL (user, password, database, query) must be percent-encoded, `@` as `%40`; a server URL with an unencoded `@` besides the one before the host is refused. |
| `MAITY_BIND` | `127.0.0.1:8080` | `host:port` to listen on; `[::1]:8080` for IPv6. |
| `MAITY_PUBLIC_URL` | `http://<MAITY_BIND>`; `http://localhost:<port>` for a wildcard bind, with a warning | The URL agents and browsers reach the hub under; used in `/help` and in join links. Set it whenever the hub is reached from elsewhere. |
| `MAITY_WEB_DIR` | `web/` beside `hub/` in a checkout; none for an installed package | The static dashboard. When set explicitly it must exist; otherwise a missing directory means the API is served alone. Dotfiles and paths under `/api` are never served from it. |

The machine-readable API description is at `/api/v1/openapi.json`;
`/api/v1/help` is the one written for agents.

## Develop

```sh
pip install -e '.[dev]'
make check      # black --check, ruff, mypy --strict (src, tests, scripts), pytest
make format     # black and ruff --fix
```

The tests run on a fresh SQLite file per test. To run them against a
server database, point `MAITY_TEST_DATABASE_URL` at an empty database the
suite may create and drop tables in:

```sh
MAITY_TEST_DATABASE_URL=postgresql://maity:<password>@127.0.0.1/maity_test pytest
MAITY_TEST_DATABASE_URL=mariadb://maity:<password>@127.0.0.1/maity_test pytest
```

CI (`.github/workflows/ci.yml`) runs `make check` on SQLite, the test
suite on PostgreSQL 17 and MariaDB 11.4 and against the built wheel on
Python 3.13, and builds the image and migrates with it.

### Migrations

Schema changes are Alembic revisions in `src/maity_hub/migrations/versions/`,
numbered `0001_…`, `0002_…`. To create the next one after changing the
table definitions:

```sh
make revision m="add the task table"
```

It migrates a scratch SQLite file to the current head, compares it with the
tables defined in `maity_hub` and writes `000N_add_the_task_table.py`.
Run `make format` on it before `make check` (the template imports `op` and
`sa` whether the revision uses them or not), and review the result:
autogenerate does not detect renames and writes nothing for data changes. Revisions must run on all three engines: use
`op.*` operations and SQLAlchemy types, no raw engine-specific SQL, and
name every constraint (the metadata's naming convention does that for
tables defined in code). SQLite runs in Alembic's batch mode, so column
changes work there too. Every revision has a working `downgrade()`; the
test suite migrates up and down on each engine. A revision spells out its
column types instead of importing them from `maity_hub` (autogenerate
writes `maity_hub.types.UtcDateTime()`; replace it as `0002` does), so
that a later change to the application cannot change what an old
revision creates.

### Data model

The tables are SQLAlchemy Core definitions in `src/maity_hub/tables.py`,
one per entity of `docs/architecture.md` §3.6, with field names from
`docs/api.md`; migration `0002` creates them. Ids come from
`maity_hub.ids` (prefix and random part, never parsed), timestamps are
`maity_hub.types.UtcDateTime` (aware UTC in Python), Markdown bodies use
`MARKDOWN_TEXT` (`MEDIUMTEXT` on MySQL/MariaDB), JSON values `JSON_VALUE`
(JSONB on PostgreSQL; an absent value is SQL NULL). On MySQL/MariaDB every
table is `utf8mb4` with the binary collation, so comparisons and unique
constraints are exact as on the other engines. The test suite checks on
each engine that the migrations create exactly the tables, indexes,
foreign keys and unique constraints in code; the CHECK constraints, which
that comparison does not see, have tests of their own.

Why it is built this way: [`context/`](context/index.md).
