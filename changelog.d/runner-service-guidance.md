### Changed

- cli: `maity runner install` ends with the next steps in order (complete the configuration, restart, the tools' and the forge's login as `maity-runner`, then `check` as that user, each command from a directory that user can enter), and a started service with the login and check steps (tsk-2k0jcaxfd0ja).
- cli: a `maity runner` command without `--config` whose default file is missing names `/etc/maity-runner/runner.toml` and how to pass it when the service's file exists; it never reads that file in the default's place (tsk-2k0jcaxfd0ja).
- cli: `maity gh` looks gh up at each call on the `PATH` the runner recorded at the session's start, so a gh installed after the session started is found without a restart; a gh inside the clone or the placement's scratch is refused, and a session started without gh still gets the grant (tsk-2k0jcaxfd0ja).
- hub: `scripts/with_postgres.sh` takes Debian's and Ubuntu's newest `/usr/lib/postgresql/<version>/bin` that has `pg_ctl` when `pg_ctl` is not on the `PATH` and `MAITY_PG_BIN` is unset (tsk-2k0jcaxfd0ja).

### Added

- cli: `maity runner check` warns about an `agent_path` entry that does not exist, naming the agents' real home when the entry lies under a home that is not there (tsk-2k0jcaxfd0ja).
- cli: `maity runner check` warns when a repository's `allow` rule names a program that is not on `agent_path`, when a grant with `pull_requests = true` finds no gh on the runner's `PATH`, and when gh has no login stored for the agents' user (tsk-2k0jcaxfd0ja).
- cli: the runner logs at a placement's start when the hub names no Keep the Why skill at all (a hub of 0.1.0a10 or older), so the skill's absence is said instead of silent (tsk-2k0jcaxfd0ja).
