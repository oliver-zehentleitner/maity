# Packaging

## `src/` layout, one package `maity_hub`, all three database drivers as plain dependencies

**Id:** dc0b5562-83c6-4182-b541-16869cfb7313
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21

The hub is the distribution `maity-hub` with the import package
`maity_hub` under `hub/src/`, built with hatchling. Everything the server
needs at run time is inside the package: the migrations and the `/help`
text as package data. psycopg and PyMySQL are ordinary dependencies, so
`pip install maity-hub` connects to any of the three supported engines,
and `postgresql://`, `mysql://` and `mariadb://` URLs are rewritten to
name those drivers.

**Reason:** with the `src/` layout the tests import the installed
package, not the working directory, so a file missing from the wheel —
a migration, `help.md` — fails in the tests instead of in the image.
Shipping the drivers by default keeps "start it with the database you
already have" a one-command install, which the database-agnostic decision
promises self-hosters; the two wheels are small.

**Rejected alternatives:**
- A flat layout (`hub/maity_hub/`) — simpler paths, but the tests then
  pass against the source tree even when packaging drops a data file.
- Drivers as extras (`maity-hub[postgresql]`, `[mysql]`) — a smaller
  install, but a self-hoster who picks the wrong extra gets a driver
  import error at startup, and SQLAlchemy's default for a bare
  `postgresql://` is psycopg2, which the hub does not use.

## The image runs on SQLite in a data volume when no database is configured

**Id:** a736c1bb-dc19-4a8a-8322-88207f5d53e1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the hub skeleton, 2026-10-21; implementation session, 2026-10-21

The image sets `MAITY_DATABASE_URL=sqlite:////app/data/maity-hub.db` and
declares `/app/data` as a volume owned by the hub's user, so `docker run
<image> migrate` and `serve` work without any configuration. Compose and
Kubernetes override the URL with a server database. The review found the
unwritable default and offered both options below; the choice and its
reason are the implementation session's.

**Reason:** the hub's own default, a relative SQLite file, points into a
directory the unprivileged user cannot write, so the image failed on its
first command. A writable default keeps "try it in minutes" true for the
image too, and the volume keeps the data across container restarts.

**Rejected alternative:** no default in the image — refuse to start and
name `MAITY_DATABASE_URL` in one line. Clear, but the image would then be
the one way to run the hub that cannot start without configuration, and
a quick look would need a server database first.

## The tested set pinned in hashed requirements files from `uv pip compile --universal`

**Id:** c43481ca-facf-4f92-bac4-df5c6468cde8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (the constraints task)
**See:** packaging.md — dc0b5562-83c6-4182-b541-16869cfb7313 — as of 2026-10-22
**Revisit when:** pip installs from a standard lock file (`pylock.toml`) without uv, or the hub needs a dependency without wheels for some platform the image or CI uses

`pyproject.toml` keeps lower bounds. The exact versions CI tests and the
image ships live in `hub/requirements/` as pip requirements files with a
hash for every distribution. There are four: runtime, dev (constrained by
runtime), build (hatchling and `editables`, constrained by dev) and tools
(uv). `uv pip compile --universal` generates them for Python 3.12 or newer
on every platform. They are installed with plain
`pip install --require-hashes`, and the hub itself goes on top with
`--no-deps`, so nothing is resolved twice. The wheel and the editable
install are built without build isolation from the pinned backend.
`make lock-check` recompiles in CI with the pinned uv, from copies whose
hash lines are dropped first so every hash is fetched again, and fails on
any difference.

**Reason:** the image should contain what CI proved, and every download
should be checked against a hash recorded in review. Requirements files
with hashes give both with pip alone, so neither the image nor a
self-hoster needs uv at install time. The universal resolution keeps one
file for Python 3.12 (the image) and 3.13 (the wheel job) instead of one
file per interpreter.

**Rejected alternatives:**
- A constraints file (`pip install -c constraints.txt -e .`): pins the
  same versions, but either way it falls short. With hashes, pip 26
  switches to hash-checking mode, which refuses the editable install of
  the hub (there is no single file to hash). Without hashes, a dependency
  missing from the file is resolved to the newest release without a word.
- `uv lock` with `uv.lock`: a full project lock, but pip cannot read it,
  and the image and CI would depend on uv for installing, not only for
  locking.
- pip-tools' `pip-compile`: produces the same file format, but resolves
  for the running interpreter only, so 3.12 and 3.13 would need separate
  files.
