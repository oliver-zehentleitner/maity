# Contributing

Maity is one repository. `AGENTS.md` has the working conventions for
agents; this file is the short form for a human contributor.

## A change

1. Branch from `main`: `<who>/<topic>`.
2. Keep the change to one concern. A change to an interface other parts
   depend on is documented in `docs/` in the same change.
3. Lint, types and tests must be green before the pull request.
4. Documentation is part of the change: README, a changelog entry as one
   new file in `changelog.d/` (never an edit to `CHANGELOG.md`; see
   `changelog.d/README.md`), `docs/`, and `context/` for every decision,
   rejected alternative or workaround. A `context/` entry is committed
   right after it is written, in its own commit, so its Git timestamp is
   the moment the reasoning was recorded.
5. Open a pull request against `main` with what is in, how it was
   verified, and what was not.

## Before merging a change to the web catalogs

A pull request that changes `web/i18n/en.json` or a language file in
`web/i18n/` is checked against the main it merges into, right before the
merge: whoever merges runs `python3 web/tools/check.py` on the pull
request's merge with the current main (or on the pull request rebased onto
it) and merges only on 0 findings. Its green CI ran against an older main
and does not count for this. Why: `web/context/rendering.md`, "A missing
translation is a note until the release; a wrong one fails at once".

## Evidence for tests and reports

These checks come from errors encountered during development: a green test
or a repeated status alone is not evidence that the intended behavior was
verified.

- Every new test case gets a counter-check without the change under test.
  Run the same case with that change absent and confirm that it fails for
  the intended reason, then restore the change and confirm that it passes.
  Record both outcomes; a setup failure is not a counter-check of the behavior.
- Report a command's resulting state only after the command has returned
  and you have checked its result. Until then, report it as running or pending.
- Before passing on a state reported in a message, verify it against the
  current source of truth. If you cannot verify it, say that it is unverified
  and attribute it to the message.
- A finding that sends someone investigating includes its counting rule:
  what was counted, over which scope, with which filters or exclusions.
  Include enough evidence to reproduce the count.

## PostgreSQL runs and a shared machine

A hub change that adds or changes an Alembic migration or raw SQL runs the
tests it affects on PostgreSQL before it asks for review; SQLite does not
show PostgreSQL's errors, and CI is not the first PostgreSQL run. From
`hub/`:

```sh
scripts/with_postgres.sh pytest -n 2 tests/test_board.py
```

The run gets a database of its own (`maity_test_<name>_<pid>`, `<name>` from
`MAITY_RUN_NAME`, else the user name), dropped when it ends. `hub/README.md`
says where `pg_ctl` comes from without a system PostgreSQL.

On a machine several contributors share under one Unix account (the server's data
directory and the slot files are that account's own; another account gets its own):

- **One server for every run:** `scripts/with_postgres.sh --start` starts it
  when it is not running and leaves it up; every run then uses it. Set
  `MAITY_RUN_NAME` to who you are (for an agent, `handle#instance`), so that
  a database left behind says whose it was. `--stop` stops the server, and
  refuses while a run still uses it, also a run whose wrapper was killed and
  whose command still runs, or a process a run left running. Other runs
  still get the server, but such a process keeps its run slot until it ends;
  the slot files' `.who` names the run it came from.
- **Two heavy runs at a time:** `make smoke` in `web/` and
  `with_postgres.sh` each hold one of the account's run slots while they run;
  there are two (`MAITY_RUN_SLOTS`). A third run waits, says who holds the
  slots, and starts once one is free. Anything else heavy runs in a slot as
  `tools/run_slot.sh <command>`.
- **Two workers per run:** `pytest -n 2` at most; in a slot, `-n auto`
  starts two.

## Commits

Imperative, plain English, one concern per commit:
`hub: claim tasks with a lease`. A handful of meaningful commits per
feature; `context/` entries are the exception and get one each.

## Issues

A bug is a GitHub issue; the form asks for the component, the version and
the steps. Feature requests and the work on Maity itself are discussed in
the project on Maity (`https://maity.team/oliver-zehentleitner/maity`),
not in issues; the issue chooser links there.

## Reasoning

Before changing something that looks odd, read `context/`. If the reason
is there, it was argued once already. If it is not, add it when you find
out.

## Security

Secrets never enter the repository. Report security problems privately as
`SECURITY.md` describes, never in a public issue.
