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

## Pillow is held below 13 for now

**Id:** df3c7ee6-6fd3-4350-8d03-aad7d3011a66
**Type:** decision
**Status:** superseded
**Superseded by:** 5e7e2eb3-d38f-4810-b43b-4ae477d62798
**Evidence:** inferred
**Source:** adding the avatar decoder (contract #136), 2026-10-22
**Revisit when:** Pillow 13 has been out for some weeks, or a security release reaches only 13

`pillow>=12.3,<13`: the avatar decoder reads bytes from any agent
credential, so the first release taken is one that has been out for
months (12.3.0, July 2026) rather than the major release of the week
(13.0.0, 2026-10-16).

**Reason:** a new major version of the hub's most exposed parser
deserves its own change, tested on its own, not one folded into the
feature that introduced the dependency.

**Alternatives:** the newest release, 13.0.0. It brings whatever it
fixes, but it is six days old and a major version.

## Pillow 13 for the avatar decoder, and the size read before Pillow

**Id:** 5e7e2eb3-d38f-4810-b43b-4ae477d62798
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the review of PR #218 and the contract owner's ruling, 2026-10-23

`pillow>=13.0,<14`. The `Revisit when` of the 12.x pin fired within a
week: advisories published 2026-10-20 to 22 are fixed only in 13.0.0, and
12.3.0 got no patch release. One of them, GHSA-5xm2-6676-qcp9, is
reachable from the decoder. An APNG claiming a huge canvas makes 12.x
allocate it inside `Image.open`, before any size check. Others need code
the decoder does not run:
- `draft()`/`thumbnail()` for the JPEG heap overflow GHSA-8g5g-8vmr-9782;
- `seek()` past the first frame for GHSA-v9pv-5gc8-w2m6;
- `getexif()` on a PNG for GHSA-g4qv. The EXIF orientation is applied to
  JPEGs only.

Independently of the version, the decoder now reads width and height from
the file's header itself and refuses past 4096 before Pillow opens the
bytes.

**Reason:** the most exposed parser of the hub does not stay on a version
with a known, reachable flaw because the fix came in a new major. The
header check is the control that does not depend on the library's own
order of checks, now or in a later version.

**Rejected alternative:** staying on 12.3 with the header check as the
only control for GHSA-5xm2. It closes the reachable flaw, but leaves the
others one code change away.


## cryptography for the secrets the hub stores, held to one major release

**Id:** 2ea5c41e-7128-4205-91dc-04ff6110b338
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.2 and §17.4 (AES-256-GCM with `MAITY_SECRET_KEY`); the coordinator's go for adding it with the webhook (tsk-0wtpcjkdhgq8), 2026-10-23
**Revisit when:** cryptography 51 has been out for some weeks, or a security release reaches only a newer major release

`cryptography>=50.0.2,<51`, with `cffi` and `pycparser` that it pulls in,
in the runtime and dev locks. `maity_hub.secretbox` is the only module that uses it:
`AESGCM` with a random 96-bit nonce per value and the field name as
associated data. The forge webhook's secret uses it first; the mail
settings' SMTP password reuses it. 50.0.2 is the newest release; the 50
line has been out since July.

**Reason:** the contract prescribes AES-256-GCM, which the standard
library does not have; `cryptography` is the maintained, audited binding
the Python world uses for it, with wheels for every platform the image
builds. One major release at a time, as with Pillow, so an upgrade is a
decision with its own review.

**Rejected alternative:** PyNaCl (libsodium): a different cipher than the
contract names. A pure-Python AES: slower and not audited. Deriving a key
stream from HMAC in the standard library: a home-made cipher.

## The wheel carries the dashboard

**Id:** df58484e-1f02-4949-bd3c-3d32456fb57a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on the local quickstart card, 2026-10-25; docs/install/quickstart.md
**Revisit when:** the dashboard gets a build step, its own release cadence, or a second server that serves it

The `maity-hub` wheel carries `web/index.html`, `css/`, `js/`
and `brand/` as `maity_hub/web`, the same way it already carries
`docs/join-page.md` (since 2026-11-05 through `hub/hatch_build.py`,
which also puts them into the sdist; see c36f4a54). web/'s `fixtures/`, `tools/` and `context/`
stay in the checkout. `checkout_web_dir()` still prefers `web/` beside
`hub/` in a checkout, and otherwise falls back to the packaged
directory. The image keeps `MAITY_WEB_DIR=/app/web`. `serve` prints
the dashboard's address, or that it serves the API alone.

**Reason:** the quickstart installs the hub with pipx and ends with the
dashboard open. Without the dashboard in the wheel, an installed hub
served the API alone. The dashboard is static files with no build step,
the API serves it, and both change together, so one distribution keeps
them at one version.

**Rejected alternatives:**
- A separate dashboard package: a second install line, and versions
  that can drift apart from the API they call.
- Pointing `MAITY_WEB_DIR` at a checkout: an extra clone and an
  environment variable in a path meant to take five minutes.

## The image sets MALLOC_ARENA_MAX=2, because the process grew with every request through fragmented arenas

**Id:** a20c28f6-6b1d-48c1-b60e-7fc9191e90df
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** measurements on 2026-10-28 for the card on the hub's growing memory (258 to 419 MiB in five hours on 2 vCPU), with and without the setting, on a real hub process
**Revisit when:** the hub's memory still grows after a deploy with it, or the image gets another allocator
**Reason:** a small drift and a lower baseline, at no cost that shows. Against a real hub process (`hub/scripts/measure_arenas.py`, SQLite, 8 CPUs, Python 3.12.3, glibc 2.39, 8 concurrent clients, environment cleaned of `GLIBC_TUNABLES`, `LD_PRELOAD` and `MALLOC_*`, every request answered: 0 failed in all four runs) the process size after the burst of 2,400 requests and then 6,000 more went from 118.0 to 119.7 and from 118.8 to 119.7 MiB with glibc's default, and from 114.8 to 114.9 and from 114.8 to 115.1 MiB with `MALLOC_ARENA_MAX=2`, which also starts 3 to 4 MiB lower; throughput (136 and 138 against 140 and 135 requests a second) and latency (p50 9 to 11 ms; p95 and p99 the same within the noise of two runs each) did not change. That is a drift of about 0.1 to 0.3 KiB a request without the setting and next to none with it. A first probe through the test client had shown about 1 KiB a request; the real hub shows less, so that number was too high and is not used. The measurement is limited: eight clients on eight CPUs against SQLite say nothing certain about a pod with 40 request threads on 2 vCPU and a server database. With 16 clients, 1 to 2 of 2,400 requests were answered `503` in several runs (SQLite makes every transaction wait for the write lock, `BEGIN IMMEDIATE`, and a request can wait past its 5-second limit), with either setting; those runs are marked invalid by the script and not used.

This is not the explanation of the 32 MiB an hour seen in production: that is about 12 KiB a request, a hundred times the drift measured here. The Python heap did not grow either (189 KiB over about 400 requests under `tracemalloc`, nothing standing out), and every in-process structure that grows with input is bounded (the long-poll registry holds one waiter a credential, the rate limiters forget keys past their window, the nonce window holds at most 10,000 entries). What the probes do not exercise is the real network and long-polls, the background workers (forge probe, images, mail, Keep the Why reads) and a server-database driver; the pod's own memory curve and a heap profile from the running hub are what is left.

**Rejected alternatives:**
- Bounding more caches (LRU or TTL): none of the structures the card names grew in the probe.
- `jemalloc` in the image: another package in a pinned image for what a setting does.
- Fewer worker threads: it would cut concurrency for a cost the allocator setting avoids (and the measured throughput did not change).

## The image is published only from main and v* tags, through an environment, and signed keyless

**Id:** dd54e1f8-29a5-434e-abbe-f08d61d293fe
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** hardening card tsk-ngx42j6r0jke (the maintainer, 2026-11-04; plan approved by the team lead); `.github/workflows/publish-image.yml`, `deploy/helm/maity-hub/README.md`
**Revisit when:** the image is pushed with a token that only the `ghcr` environment holds, or the chart starts checking signatures itself

`publish-image.yml` runs on a `v*` tag and by hand. Its build job stops
unless the ref is a `v*` tag or `main`; the signing job runs only after
it. Both run in the environment `ghcr`, which the repository's
settings open to `main` and `v*` tags only; who may create or move those tags is a repository rule. Both
the `if` and the environment are in the workflow file, so they keep
this file from running elsewhere, not a changed copy of it on a branch:
the push uses the run's `GITHUB_TOKEN`, whose `packages: write` the file
itself asks for. After the push a second job, the only one with
`id-token: write`, signs the pushed digest with cosign, keyless: the
certificate names `publish-image.yml` and the ref the run was on.
The chart README tells operators to check that identity with
`cosign verify` before they pin a digest.

**Reason:** the image is what every installation runs, so only
reviewed code, on `main` or a release tag, should become one. What
holds that is the signature with the tag rule: a run from a branch,
even with an edited file, gets `refs/heads/<branch>` in its
certificate, which the README's `cosign verify` refuses, and only
those the rule allows create `v*` tags. The `if` and the environment
keep the unchanged file from pushing from elsewhere. The signature
lets an operator check where a digest came from without trusting the
registry alone.

**Rejected alternatives:**
- The `if` alone, without the environment: the environment adds the
  repository's own list of refs, which a later approval rule can
  extend. Neither stops an edited copy of the file on a branch (above).
- Pushing with a token that only the `ghcr` environment holds, which
  would stop an edited file on a branch from pushing at all: needs a
  stored long-lived token; kept as a further step if needed.
- A signing key stored as a secret: a long-lived key that can leak.
  Keyless needs none, and the identity is the workflow and ref.

## The hub is published to PyPI as `maity-hub` from the same `v*` tag as the image, built from a hashed lock

**Id:** 843b8d35-45c7-4b91-827f-7109f470ca54
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-yb8ceadp1gpw (the maintainer, 2026-11-05: versioned PyPI installs instead of the Git URL; plan and the `v*` tag approved by the team lead); `.github/workflows/release-hub.yml`, `hub/requirements/release.in`, `hub/Makefile`, `hub/scripts/check_dist.py`
**Revisit when:** the hub and the CLI start sharing one version, the image and the package stop releasing together, or PyPI's trusted publishing starts attesting how the files were built
**See:** https://github.com/oliver-zehentleitner/maity — 227cd75c-bfc7-4cd8-9ba8-cf877cd3bf21 — as of 2026-11-05
**See:** https://github.com/oliver-zehentleitner/maity — a8dd1473-5aff-4f32-a3fe-89c0498a208d — as of 2026-11-05
**See:** packaging.md#the-sdist-carries-the-dashboard-and-the-join-page-under-bundled — c36f4a54-432f-4fe2-82ab-377690759268 — as of 2026-11-05
**See:** https://github.com/oliver-zehentleitner/maity — ea58fdd2-6e3f-45df-ae48-4ce6825cafde — as of 2026-11-09

A tag `v<version>` runs `release-hub.yml` beside `publish-image.yml`, so
one tag gives the package and the image the same version. The workflow
stops unless the tag names the version in `hub/pyproject.toml`, which
is the only place it is written (`__version__` reads the package
metadata). Versions are pre-releases (`0.1.0a1`, …) before the beta, as
the CLI's are. As in the CLI's release, a `check` job (which ran the
hub's checks with the hashed dev lock until 2026-11-09 and now holds the
tag to ci's result on its commit and to a green hub-mariadb run on a
commit of main with the same hub files, the entry
ea58fdd2-6e3f-45df-ae48-4ce6825cafde in the root context), a `build` job installs only
`hub/requirements/release.txt` (build, twine and hatchling, compiled
with the `build.txt` pins as constraints) into a fresh environment and
builds without isolation (`make release-build`), and `publish` uploads
that job's artifact with trusted publishing from the `pypi`
environment. Before the upload, `make release-check` proves the files:
the wheel carries the dashboard and the join page byte for byte, a
wheel rebuilt from the sdist is the same, and the wheel installed
outside the checkout from the hashed runtime lock migrates SQLite,
serves its page and every file the page names. The `hub-dist` job of
ci.yml runs the same two targets on every pull request that touches
`hub/`, `web/` or the join page, so a tag never finds them broken.

**Reason:** the quickstart installs the hub from the Git URL, so the
version a person runs is whatever main holds that day and cannot be
named or pinned. The image already releases on `v*`, and its check
holds the tag to the version the hub reports; a second tag prefix for
the package would give one hub version two tags that can point at
different commits. The release lock follows the CLI's: what PyPI gets
is built only with reviewed, hashed tools. The proof runs before the
upload because a file on PyPI cannot be replaced under the same
version.

The name was taken on PyPI with a final `0.0.0` placeholder. pip
prefers any final release to pre-releases, so while `0.0.0` stands,
`pipx install maity-hub` installs the placeholder, not `0.1.0a1`
(checked with pip against a local index holding both); a yanked
release is skipped unless pinned exactly, so the placeholder is yanked
before the first tag. For the same reason the quickstart keeps the Git
URL until `0.1.0a1` is on PyPI: merging the workflow publishes nothing,
and `pipx install maity-hub` before the first release installs the
placeholder, which has no `maity-hub` command (the review of this change).
The quickstart switches to `pipx install maity-hub` in a pull request of
its own once the release is verified.

**Since 2026-11-09:** `0.1.0a1` is on PyPI, the maintainer removed the
`0.0.0` placeholder the same day (deleted rather than yanked, so the
simple index lists only `0.1.0a1`), and the quickstart installs with the
plain `pipx install maity-hub`, as `pipx install maity` for the CLI.
(Source: card tsk-g5me3qzet9dp. Before the removal, the index listed
`0.0.0` with `yanked: false`, and in a throwaway pipx home the plain line
failed building the placeholder's sdist, while `--pip-args=--pre` and
`==0.1.0a1` installed `0.1.0a1`. After it, the plain line installed
`0.1.0a1` without pip's cache.) Rejected: `--pip-args=--pre` as the
documented line (it worked with the placeholder, but it is a flag every
reader has to carry, and pip would then also prefer later pre-releases
to finals); a pinned `==0.1.0a1` as the main line (stale with the next
release, and kept only as the way to pin); and keeping the Git URL (no
version to name, and the package path stays untested).

**Rejected alternatives:**
- A tag prefix of its own, `hub-v*`, as the CLI has `cli-v*`: two tags
  for one hub version, and the image and the package could name the
  same version for different code.
- Installing from the Git URL for good: no version to name or pin, and
  nobody tests the path most users take.
- Uploading the wheel alone: the sdist is what a source build or a
  platform without the wheel uses; it is kept and proven instead.
- An API token stored as a repository secret: a long-lived credential;
  trusted publishing needs none.

## The sdist carries the dashboard and the join page under `bundled/`

**Id:** c36f4a54-432f-4fe2-82ab-377690759268
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-yb8ceadp1gpw (2026-11-05): on main, a wheel built from the hub's sdist failed with `Forced include not found: …/docs/join-page.md`; `hub/hatch_build.py`
**Revisit when:** the dashboard gets a build step or a package of its own, or hatch can name files outside the project root in an sdist
**See:** packaging.md#the-wheel-carries-the-dashboard — df58484e-1f02-4949-bd3c-3d32456fb57a — as of 2026-11-05

The wheel's extra files (`docs/join-page.md`, and `web/index.html`,
`css/`, `js/`, `brand/`, `vendor/`) live outside `hub/`. A build hook,
`hub/hatch_build.py`, names them in one table: building from the
checkout it takes them from the repository root; building the sdist it
puts them under `bundled/`; building from an unpacked sdist, where
`bundled/` exists, it takes them from there. The wheel from either path
has the same files with the same bytes (`make release-check`), and the
editable install keeps the copies it had before.

**Reason:** the wheel's `force-include` in `pyproject.toml` pointed at
`../docs` and `../web`, which an sdist built in `hub/` does not hold, so
pip could not install the hub from its sdist. The image and CI build
the wheel from the checkout and never noticed. One table in the hook
keeps the list in one place for both targets.

**Rejected alternatives:**
- Uploading only the wheel: leaves a broken sdist or none.
- Copying `web/` into `hub/` in the repository: a second copy that
  drifts from the one the dashboard's checks test.
- A second, sdist-only `force-include` table in `pyproject.toml`: the
  wheel's table would still name `../` paths, which the unpacked sdist
  does not have.
