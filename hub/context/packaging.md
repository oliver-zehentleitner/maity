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
