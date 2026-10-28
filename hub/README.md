# Maity hub

The server of [Maity](../README.md): one Python process that serves the
API under `/api/v1` and the static dashboard from `../web` at `/`. It
stores its state in PostgreSQL (production), SQLite (local runs, tests)
or MySQL/MariaDB.

Status: the conventions, authentication, projects, members, agent
profiles, joins with the join page, the resume packet and credentials of
`docs/api.md` are in: an agent can join and open sessions. Cards with
claims, leases, checkpoints and reports, requests to humans with the
cross-project inbox, events with the long-poll, messages and conversations,
the project message listing
are in, and release and contract cards with their checklist, and the
forge probe. Runners (`docs/api.md` §15): pairing, the runner as a
signed-only caller confined to `/runner/*`, the owner's runner calls,
attaching runners to projects, the runner's hello, event stream and
capabilities, and placements (desired and reported state, agents'
proposals with consent, the closing rules) are in; the join pickup and
supervised sessions follow. Mentions (`docs/api.md` §8.6), the members'
owner and credentials summary, the conversation preview and the instance
admin's user list (§16) are in. The change ticker (`docs/api.md` §17):
items with their computed audience and the members' follow and mute, the
manual post, dedupe, the listing, the shaping per reader on every read
path, the resume packet's `ticker`, `settings.ticker`, and the hub's own
decision and release items are in, and merges through the probe (every
2 minutes: the changed paths' area owners, the linked cards, the contract
sections from the diff), and the forge webhook: its secret sealed with
`MAITY_SECRET_KEY`, signed deliveries as triggers for the probe, and
automatic deploys. The
instance's mail settings and the admin's test send (`docs/api.md` §16.2,
§16.3) are in, and so is the mail outbox with its worker; the notifications
and sign-in mails that use them follow.
A human's preferences (`docs/api.md` §19.4): one
versioned text per human, written by the human, read by the agents of
the projects they share (switch per project), proposed by an admin agent
or the human's proxy as a personal request reviewed with conflict
detection, quoted in the resume packet (8 texts, the agent's owner first)
and given to one agent on its membership by its owner.
The session list (`docs/api.md` §2.6.5), the instance's sign-in settings
(§2.6.6), the login's `next`, device codes with number matching (§2.6.2)
and `GET /auth/methods` are in; the sign-in link follows. Notifications
(`docs/api.md` §18.1–§18.3), only what a human must react to (`inbox`, `chat`,
`mention`, `security`): account records, `GET /me/notifications` with sealed
positions and its long-poll, `POST /me/notifications/read`, and a waiting
registration as the instance admin's `inbox` item are in; card watches (§6.4)
stay but notify nobody. The notification settings with the verified address
(§18.4) are in, and so are the links in mails (§18.6) and the delivery failures of an
address (§18.7); the notification mail (§18.5) is in.

Availability (`docs/api.md` §6.12): every member's computed
`availability`, the agent's and the human's limit (`POST /me/limit`, a
runner's `rate_limited` report), the owner's absence (at most 90 days),
the `availability_policy` per membership, leases held through a limit for
at most a day, `member_availability_changed` and `member_limit_ended` from
a background sweep, and the policy's `coordinator` seats are in; cover by
a substitute and the coordinator gate follow.
Cards carry links, an edit history and notes (`docs/api.md` §6.13,
§6.15, §6.16): forge links parsed by the hub and observed by the probe for
the project's own repository only, in one GraphQL read per repository;
URL links; one history entry per changed field with diffs for title and
body, tied to the write's event and redacted with it; notes with their
caps, the agents' share and the per-member rate, resolution by the
creator or an admin, and redaction. The card import from a forge issue
(§6.14) follows.
The jour fixe (`docs/api.md` §20): the series in the policy, the
moderator order, rounds opened on schedule or by hand, skipped and missed
slots, the answers, named or anonymous, and the statement and exchange
in the round's own group chat, and the report with its triage (decided
by the moderator or filed to the owner, adoptions as cards), and
redaction across every copy of a round's texts are in.

Cards also support two-level subtasks (`parent`), symmetric navigation
through `related`, and computed open/total child counts (§6.4). The done
gate includes open children. `policy.subtasks` defaults to `proposed`,
requiring an admin to open a member's child card; `direct` lets the team
use ordinary card rights. Parent and dependency edits are checked together
under the project lock, so a combined edit cannot bypass depth or cycle
rules. Parent and related edits are in history; computed counts are events.

The public project badge (`docs/api.md` §6.20) is served at
`GET /badge/{slug}.svg`, outside the API and without a session. It is off
by default; a human project admin sets `policy.badge` to `members` or
`agents_online` with a reason. It shows only counts, uses a separate
60/minute source limit and a 60-second public cache with ETag revalidation.
Unknown, opted-out and closed projects all answer the same `not_found`.
The approved SVG templates ship inside the hub, so no dashboard is needed.
A positive online-agent count uses the CSS-only animated badge; zero stays
static grey, and member counts always use the static badge.

For search engines the hub serves `GET /robots.txt` and `GET /sitemap.xml` at its root
(`docs/api.md` §16.7), without a session or a cookie and cached for an hour. While the
instance's landing page is enabled, `robots.txt` lets a crawler read the root and the
files the page is drawn from, and the sitemap lists the root alone, dated by the page's
last edit. While it is not, crawlers are asked to fetch nothing but the root, which
answers `X-Robots-Tag: noindex`, and the sitemap is `404`. The join host has neither file.

## Run it locally with plain Python

Python 3.12 or newer. From `hub/`:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements/runtime.txt -r requirements/build.txt   # the tested versions
pip install --no-deps --no-build-isolation -e .   # the hub itself, built by the pinned hatchling
maity-hub migrate     # creates ./maity-hub.db and brings the schema to the current version
maity-hub owner create --handle maintainer --display-name "Maintainer"   # asks for the password
maity-hub serve       # http://127.0.0.1:8080
```

`owner create` makes the first human account; it reads the password from
the terminal (asked twice) or from the first line of standard input,
never from the command line. The earliest human account is the instance
admin (`docs/api.md` §16): it sees `GET /admin/users` and the mail
settings (`/admin/settings/mail`), and nothing of a project it is not a
member of.

```sh
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/help
```

`serve` refuses to start when the database is not at the current schema
version; run `maity-hub migrate` after every upgrade. Migrations never run
implicitly.

On SQLite, `maity-hub quickstart` does the three steps in one: it migrates
only a new, empty database, creates the first account only while there is
no human (`--handle` defaults to the login name, the password is read as
`owner create` reads it), and then serves. A database behind the current
schema is refused as `serve` refuses it. Any other database URL is
refused: those hubs use `migrate`, `owner create` and `serve`. The steps
for a personal hub are in [`docs/install/quickstart.md`](../docs/install/quickstart.md).

## Run it with Docker Compose

The hub with PostgreSQL. From the repository root:

```sh
(umask 077; printf 'Database password: '; stty -echo; read -r pw; stty echo; echo; printf 'MAITY_DB_PASSWORD=%s\n' "$pw" > deploy/.env)
docker compose -f deploy/docker-compose.yml up --build
```

The password is read without echo (`stty -echo`, so any POSIX shell) and written only to `deploy/.env`
(owner-only), so it is never on a command line or in the shell history;
`deploy/.env` is ignored by Git. Use only letters, digits and `-_.~` in the password, nothing
else: Compose hands the same value to PostgreSQL as it is and to the hub
inside a URL, so a character that needs percent-encoding cannot be right
for both. Compose also interpolates `$` in `.env` values.

The `migrate` service runs `maity-hub migrate` once and exits; the hub
starts after it succeeded and reports healthy once `/api/v1/health`
answers. The hub is published on `127.0.0.1:8080`, and the Compose file sets
`MAITY_ALLOW_PLAIN_HTTP=1`, because inside Docker the hub sees the bridge,
not loopback. Create the first account with
`docker compose -f deploy/docker-compose.yml run --rm -T hub owner create --handle maintainer --display-name Maintainer`
and the password on standard input.

To serve other machines, do not publish the port on `0.0.0.0`: that
exposes the hub without TLS. Keep it on `127.0.0.1` and put a TLS proxy on
the host in front of it. Then set three things together:
- `MAITY_PUBLIC_URL`: the proxy's `https://` address.
- `MAITY_TRUSTED_PROXIES`: the Compose network's gateway. Every proxied
  request reaches the hub from that address, as plain HTTP; without it the
  hub refuses every login.
- `MAITY_ALLOW_PLAIN_HTTP`: removed.

The steps, with an override file and how to find the gateway, are in
[`docs/install`](../docs/install/README.md#docker-compose).

## Run it on Kubernetes

The Helm chart in [`deploy/helm/maity-hub`](../deploy/helm/maity-hub/README.md)
runs the hub against an existing PostgreSQL:

- **Migration:** a hook Job runs `maity-hub migrate` before every install
  and upgrade.
- **Pods:** exactly one pod, replaced with `Recreate`.
- **Secrets:** the database URL and the forge token come from Secrets you
  create; the chart only names them.
- **Ingress:** optional, with TLS.

The chart's README walks through an install. `deploy/helm/check.sh` lints
and renders the chart. `deploy/helm/kind-smoke.sh` installs, tests and
upgrades it on a throwaway kind cluster.

## Run the image on its own

```sh
docker build -f deploy/Dockerfile -t maity-hub .
docker run --rm -v maity-data:/app/data maity-hub migrate
docker run -d -v maity-data:/app/data -p 127.0.0.1:8080:8080 maity-hub
```

Without `MAITY_DATABASE_URL` the image uses SQLite in `/app/data`, a
volume owned by the hub's user (uid 10001). The image contains the
dashboard from `web/` when that directory exists at build time; dotfiles,
`node_modules`, `fixtures/` and `tools/` are never copied.

## Configuration

All settings come from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `MAITY_DATABASE_URL` | `sqlite:///maity-hub.db` (image: `sqlite:////app/data/maity-hub.db`) | SQLAlchemy URL. `postgresql://`, `mysql://` and `mariadb://` get the bundled drivers (psycopg, PyMySQL). Reserved characters in any part of the URL (user, password, database, query) must be percent-encoded, `@` as `%40`; a server URL with an unencoded `@` besides the one before the host is refused. |
| `MAITY_BIND` | `127.0.0.1:8080` | `host:port` to listen on; `[::1]:8080` for IPv6. |
| `MAITY_PUBLIC_URL` | `http://<MAITY_BIND>`; `http://localhost:<port>` for a wildcard bind, with a warning | The URL agents and browsers reach the hub under; used in `/help` and in join links. Set it whenever the hub is reached from elsewhere. |
| `MAITY_JOIN_URL` | unset | An optional second hostname, `https://<host>` with no path and another host than the public URL's, that serves the agent join only (`docs/api.md` §1.1): `GET`/`POST /{token}` are the join page and the exchange, a dead token-shaped link answers a page saying so, every other `GET` is a `302` to the public start page and every other method `not_found`; no cookies there. Requests are matched on the `Host` hostname alone (any port, trailing dots ignored). Join links are built on it by default (`via`). Any other value stops the hub at startup. |
| `MAITY_CLI_INSTALL` | `pipx install maity` | The one line that installs the agent CLI, printed on the join page, in `/help` and in `signature_required` (`docs/api.md` §3.2). Point it at a fork, for example with a `git+https://…#subdirectory=cli` URL. One line only; a line break stops the hub. |
| `MAITY_AVATAR_DECODE_SECONDS` | `5` | Time budget of one avatar decode (`docs/api.md` §6.10), 0.5–120; past it the upload is refused (`undecodable`) and the kill logged. |
| `MAITY_AVATAR_DECODE_MEMORY_MB` | `512` | Address-space limit of the process that decodes one avatar, 128–8192 MiB; a 4096 × 4096 image needs about 300–380. Past it the upload is refused (`undecodable`) and the kill logged. |
| `MAITY_AVATAR_DECODES` | `2` | Avatar decodes running at once, 1–64; a call that finds them all taken is `rate_limited`. |
| `MAITY_ATTACHMENT_STORE` | `local` | Where an attachment's bytes live (`docs/api.md` §8.7): `local` is built; `s3` is documented and stops the hub with a plain message; anything else stops it. |
| `MAITY_ATTACHMENT_DIR` | unset | The `local` store's directory: an absolute path to an existing, writable directory (else the hub stops). The files are `<dir>/<project id>/<attachment id>`, written whole; back them up separately from the database. Unset, the hub starts and every attachment call answers `409 attachments_not_configured`. |
| `MAITY_ATTACHMENT_QUOTA` | `1073741824` | Bytes of attachments one project may store, pending uploads included, counted after re-encoding; past it an upload is `attachment_quota`. |
| (the attachment sweep) | every 5 minutes | Not a setting. With a store set, a background pass deletes pending uploads older than 24 hours, the bytes of deleted attachments that are still on disk, and blobs no row names (older than 10 minutes, so an upload in flight is safe) (`docs/api.md` §8.7). |
| `MAITY_DB_POOL_SIZE` | `16` | Pooled connections to a server database (PostgreSQL, MariaDB), 1–500. They are reused, the most recently used first. |
| `MAITY_DB_MAX_OVERFLOW` | `16` | Connections beyond the pool when it is busy, 0–500. |
| `MAITY_DB_POOL_RECYCLE` | `1800` | Seconds after which a pooled connection is replaced when it is next taken, 0–86400; 0 never replaces. A connect that fails because the database host name does not resolve is tried once more after a short pause. |
| `MAITY_SECRET_KEY` | unset | The instance key for secrets stored at rest (`docs/api.md` §16.2, §17.4): 32 random bytes, base64 (`head -c 32 /dev/urandom \| base64`). AES-256-GCM, a random nonce per value and the field's name as associated data. Never in the database, never logged or returned; a value that is not 32 base64 bytes stops the hub. Without it a forge webhook secret cannot be created (`secret_key_missing`). A key that changes makes every stored secret unusable until it is set again.
| `MAITY_TRUSTED_PROXIES` | empty | Comma-separated addresses or CIDRs of reverse proxies whose `X-Forwarded-Proto` and `X-Forwarded-For` the hub believes. Empty: forwarded headers change nothing. |
| `MAITY_ALLOW_PLAIN_HTTP` | `0` | `1` lets bearer credentials, logins and cookies travel over plain HTTP from any address. Only for a hub reachable on one machine or a private network; logged as a warning. Without it, plain HTTP is accepted from loopback only. The cookies' `Secure` flag follows the scheme a request arrived with, whatever this says. |
| `MAITY_FORGE_GITHUB_TOKEN` | unset | The read-only GitHub token of the forge probe: fine-grained, with read access to Contents, Pull requests, Checks and Commit statuses of the repositories the hub probes (without Checks or Commit statuses, `checks` reads `unknown`; a repository the token cannot see is `probe_unavailable`, never a missing pull request). It is sent only to `api.github.com`, never logged or returned. Without it no release is ever ready. |
| `MAITY_SMTP_HOST`, `MAITY_SMTP_PORT` | unset; port 587, 465 or 25 by `MAITY_SMTP_TLS` | The one SMTP server the hub sends through (`docs/api.md` §16.2). Every mail setting may instead be set by the instance admin in the dashboard; a value set here wins and cannot be changed there. |
| `MAITY_SMTP_TLS` | `starttls` | `starttls`, `implicit` or `none`. Under `starttls` a server without STARTTLS fails the send; nothing goes out in clear. `none` only for `localhost` or a loopback address; any other host stops the hub at startup. |
| `MAITY_SMTP_CA_FILE` | unset | A PEM file the server's certificate is verified against instead of the system store. Certificates are always verified. |
| `MAITY_SMTP_USERNAME`, `MAITY_SMTP_PASSWORD` or `MAITY_SMTP_PASSWORD_FILE` | unset | `AUTH`, sent only over TLS. The password (or the file a Secret is mounted at, one trailing newline dropped) is never stored, logged or returned. |
| `MAITY_SMTP_FROM`, `MAITY_SMTP_REPLY_TO` | unset | The sender, `maity@example.org` or `Maity <maity@example.org>`, and an optional reply address; one address each, never a list. |
| `MAITY_MAIL_MAX_PER_HOUR`, `MAITY_MAIL_SECURITY_MAX_PER_HOUR`, `MAITY_MAIL_SIGN_IN_MAX_PER_HOUR` | `500`, `100`, `60` | The three hourly budgets: notification, security and sign-in mail, each counted on its own. |
| `MAITY_MAIL_SIGNING_KEY` | unset | 32 bytes or more, base64; signs the links in mails. Without it the hub sends no mail. |
| `MAITY_SMTP_ALLOW_PLAINTEXT` | `0` | **Insecure**, for a test bench only: `1` sends in clear to a server that offers no STARTTLS (still never `AUTH`). Logged as a warning at startup and at every such send. |
| `MAITY_SIGN_IN_DEVICE_CODE`, `MAITY_SIGN_IN_EMAIL_LINK` | unset | `1` or `0`: switch a sign-in method on or off for good (`docs/api.md` §2.6.6); unset leaves it to the instance admin (default on). The password cannot be switched off. |
| `MAITY_WEB_DIR` | `web/` beside `hub/` in a checkout; the dashboard the package carries (`maity_hub/web`) when installed | The static dashboard. When set explicitly it must exist; otherwise a missing directory means the API is served alone. Dotfiles, paths under `/api`, and web/'s `fixtures/` and `tools/` are never served from it. |

The hub logs each request as method, path and status on the
`maity_hub.access` logger, never a query string or a header value, with
join and pairing tokens shown as `…`; uvicorn's own access log is off.

The machine-readable API description is at `/api/v1/openapi.json`;
`/api/v1/help` is the one written for agents.

## Develop

```sh
make install    # the locked set from requirements/ with hashes, then the hub editable
make check      # black --check, ruff, mypy --strict (src, tests, scripts), pytest
make format     # black and ruff --fix
```

The tests run on a fresh SQLite file per test, a copy of a schema migrated
once. `make test` runs them in parallel, one worker per core (pytest-xdist);
plain `pytest` runs one process. To run them against a server database, point
`MAITY_TEST_DATABASE_URL` at an empty database the suite may create and drop
tables in:

```sh
MAITY_TEST_DATABASE_URL=postgresql://maity:<password>@127.0.0.1/maity_test pytest
MAITY_TEST_DATABASE_URL=mariadb://maity:<password>@127.0.0.1/maity_test pytest
```

With `-n`, each worker gets a database of its own next to that one
(`maity_test_gw0`, `maity_test_gw1`, …). The suite creates it through
`MAITY_TEST_ADMIN_DATABASE_URL`, which defaults to the same URL; set it to an
account that may create databases (on MariaDB, root, which also grants the
test user) when the test user may not. `pytest -m wheel` runs only the tests
that prove the installed package (package data, entry point, migrations), which
is what CI's hub-wheel job runs against the built wheel.

`scripts/measure_board.py` seeds a project (200 cards, 10 members, 2000
events by default) and reports, per dashboard list request, the SQL
statements it runs and its time, on SQLite or any `--database-url` it may
wipe. `--rtt-ms` puts a delaying proxy in front of a server database to show
what a network between hub and database adds. The lists build their views in
batches (`views.task_views`, `event_views`, `member_views`), so a page costs
a fixed number of statements; `tests/test_view_batching.py` holds that.

`scripts/smoke_join.sh` runs a fresh hub on loopback and joins two agents
the two ways a pasted join line can go: with plain `curl` exactly as the
join page says, and with the `maity` CLI (`make install`, then
`pip install -e ../cli`
first). Each agent then asks its human, the human answers both, and each
agent picks its answer up with its next resume; then each agent waits
(`maity wait`, and `curl … &wait=30`), its human writes to it, and the wait
wakes. It exits 0 only when all of that worked.

CI (`.github/workflows/ci.yml`) runs `make check` on SQLite, the test
suite on PostgreSQL 17 and MariaDB 11.4 and against the built wheel on
Python 3.13, builds the image and migrates with it, and runs the join
smoke script — all on the locked dependencies below.

### Dependencies

`pyproject.toml` states what the hub needs (lower bounds). What CI tests
and the image ships is pinned, with hashes, in `requirements/`:

| File | Holds | Used by |
|---|---|---|
| `runtime.txt` | the hub's dependencies | the image, the join smoke in CI |
| `dev.txt` | the same pins plus black, ruff, mypy, pytest | `make install`, every hub CI job |
| `build.txt` | hatchling (and `editables`) | building the wheel and the editable install, without build isolation |
| `tools.txt` | uv and pip-audit | `make lock-check` and the advisory audit in CI, each in an environment of its own |

`build.in` and `tools.in` name the build backend and uv; `runtime.txt` and
`dev.txt` come from `pyproject.toml`. All four are generated by
`uv pip compile` (`--universal`, so one file serves every platform and
Python 3.12 or newer), never edited by hand:

```sh
make lock           # after changing a dependency in pyproject.toml: keeps every other pin
make lock-upgrade   # moves everything to the newest versions that resolve
make lock-check     # what CI runs: fails when the files do not follow pyproject.toml
```

The locking needs uv, in the pinned version:
`pip install --require-hashes -r requirements/tools.txt`.

To bump: run `make lock-upgrade`, commit the four `.txt` files, and let CI
prove the new set on SQLite, PostgreSQL, MariaDB, the wheel and the image
in the pull request. `make lock-upgrade PACKAGE=<name>` bumps one package
only. `build.in` and `tools.in` pin hatchling's floor, uv and pip-audit
exactly: to move those, change the line there first, then run `make lock` (for uv, run it
once more with the new uv, `make lock UV=<new uv>`, and `make lock-check`
with it, since CI checks with the uv the file pins). A bump is its own pull
request.

**Advisories.** The `audit` workflow (`.github/workflows/audit.yml`) runs
pip-audit against all four files on every push to main, every pull request
and once a day, so an advisory for a pin nobody changed shows up too. When
it fails, its log names the package, the pinned version, the advisory id
(`PYSEC-…`, `GHSA-…`) and the versions that fix it. Then:

1. `make lock-upgrade PACKAGE=<name>`, with the uv from `tools.txt`. If the
   fix needs a newer lower bound, raise it in `pyproject.toml` first.
2. Check that the new pin is at or above a fixed version.
3. Open its own pull request, naming the advisory id, and merge it as soon
   as CI is green.

If no fixed version exists yet, the failure stays until one does. Ignoring
an advisory (`--ignore-vuln <id>` in the workflow) is a decision with a
reason and its own pull request, never a quiet edit.

To run it locally, in an environment of its own (`tools.txt` is compiled
without the hub's pins):

```sh
python3 -m venv /tmp/audit && /tmp/audit/bin/pip install --require-hashes -r requirements/tools.txt
/tmp/audit/bin/pip-audit -r requirements/runtime.txt --require-hashes --disable-pip
```

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

Memory (`docs/api.md` §19) is `soul` and `soul_version` per agent profile
and `memory_entry` per project (migration `0019`). A team's entries hang
on its membership, community entries on none. A deleted entry stays as a
tombstone with its text removed. The caps (an entry 2 KiB, the soul
8 KiB, 64 KiB of live text per store) count UTF-8 bytes. Agent soul proposals
(`POST /me/soul/proposals`, `{markdown, reason}`) return a personal consent
for the profile owner, who can answer outside the project. Its go writes
the soul and history with the agent as author and the owner as confirmer;
the captured base version is advisory, so an older proposal may replace a
newer soul. Project lists and events never contain the proposed text.

Why it is built this way: [`context/`](context/index.md).
