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

## Lint and types before a push

A red CI from formatting, types or the context costs a round of about an
hour. An opt-in pre-push hook runs CI's own `make lint typecheck`
(`black --check`, `ruff`, `mypy`, no tests) for each of `hub/` and `cli/`
that the push touches, and `ktw-lint` for each Keep the Why project it
touches (the root, `hub/`, `cli/`, `web/`, as CI's ktw-lint job has them;
a change to a project's `context/` or `.keep-the-why` also lints its
family). Turn it on once per clone:

```sh
git config core.hooksPath tools/hooks
python3 -m venv hub/.venv && make -C hub install PYTHON=.venv/bin/python
pipx install --force "keep-the-why-lint==$(sed -n 's/.* # lint-v//p' .github/workflows/ktw-lint.yml)"
```

The second line is the hub's environment from the hashed lock, the same
one CI installs; the hook uses it for both packages (or the Python that
`MAITY_HOOK_PYTHON` names). It stops before checking when black, ruff or
mypy there differ from the pins in `hub/requirements/dev.txt`: after a
lock change, run `make -C hub install PYTHON=.venv/bin/python` again.
Likewise it stops when the `ktw-lint` on PATH (or the one
`MAITY_HOOK_KTW_LINT` names) is not the version CI pins (`# lint-vX` in
`.github/workflows/ktw-lint.yml`), naming both versions and the install
command; it installs nothing and needs no network. It checks the working
tree, so it also stops when HEAD is not the pushed commit or what it
checks (a touched package, a linted project's `context/` and
`.keep-the-why`) has uncommitted changes. `git push
--no-verify` skips it; `git config --unset core.hooksPath` turns it off.
`tools/pre_push.py` has the details.
Not in a clone a maity runner manages: the runner's clone check refuses
a clone whose `.git/config` sets `core.hooksPath`.

## The overlap check before a push

Before you push a branch, check it against the open pull requests that
change the same files:

```sh
tools/overlap.sh            # the checked-out branch; or tools/overlap.sh <branch>
```

It prints one line per such pull request: the shared files, and `clean` or
the files that conflict. It decides by `git merge-tree`'s exit code, never
by git's message, so the locale doesn't matter. A file that already
conflicts with `main` alone is named but not counted, so exit 0 means your
branch adds no conflict, not that it merges cleanly with everything: read
the lines. Exit 1 means your branch adds a conflict: settle the order with
the other author or the lead before you push. Exit 2 means the check could
not run; it never ends in 0 then. It needs bash 4 or newer and `gh`, and it fetches
`origin main` and the head of every pull request open in origin's repository. It lists
them over GitHub's REST API (`gh api`), so it also runs where the GraphQL API is
blocked, as in Claude Code's cloud sessions.

## The coverage check before a MERGE-READY

Before you report a pull request as ready to merge, check that its green
`ci-ok` run saw every `main` commit on its files:

```sh
tools/coverage.sh <pr>
```

CI tests the pull request merged with `main` as `main` was when the run
started. The check reads that `main` from the run's checkout logs, then lists
the `main` commits that are in neither that `main` nor the pull request's
head and change one of its files (a merge counts too). Exit 0 means there
are none. Exit 1
names them: merge `origin/main` into the branch and push for a new run (a
re-run tests the old merge again). Exit 2 means the check could not run,
including when `ci-ok` is not green yet or the pull request is stacked on
another branch; it never ends in 0 then. It needs bash 4.4 or newer, `gh` and
a full (not shallow) clone, and it only reads: GitHub over REST and a
`git fetch` of `origin main` and the pull request's head into refs of its own.

## Opening and editing a pull request from a cloud session

Where the GitHub tool or GitHub's GraphQL API is refused, as in Claude
Code's cloud sessions, `gh pr create` and `gh pr edit` cannot work. Open
and edit your pull request over the REST API instead:

```sh
tools/pr.sh open --title "…" --body-file body.md     # the checked-out branch against main
tools/pr.sh edit 1234 --body-file body.md            # or --title "…", or both
```

`open` refuses a branch that origin does not have at your local head:
push first. `edit` changes only the pull request whose head is your
checked-out branch (`--branch B` names another of yours): every agent
pushes as the same GitHub account, so the head is what tells the pull
requests apart. The body always comes from a file, sent as it is, and a
body with an attribution line is refused. The list is fixed: a line that
starts with `Generated with`, `Generated by`, `Co-Authored-By:` or
`Claude-Session:`, in any case, after nothing but spaces, emoji, symbols,
`>` and Markdown emphasis or link markup (`_Generated by [Claude Code](…)_`,
`- Co-Authored-By: …`, `> Claude-Session: …`, `[Co-Authored-By](…): …`). The same words mid-line
are text. It prints GitHub's answer (number, URL, head, title). Exit 1
means it refused, with the reason; exit 2 means it could not run (a check,
git, gh or reading GitHub's answer failed), and it never ends in 0 then.
Owner, repository and host are origin's, read only from
`[user@]host:owner/repo`, `ssh://`, `https://` or `http://` with exactly
owner/repo after the host, or the loopback proxy's `/git/owner/repo`;
any other origin URL (a query, a fragment, other path segments, `.` or
`..`) is refused before GitHub is called. Opening a
pull request for a cloud session is no longer the lead's job: open your
own and send the lead its number.

## The guard tests before a review request

Run `tools/guards.sh` before you ask for a review (`HUB_PYTHON=` a Python
with the hub's test requirements). In about half a minute it runs what
otherwise fails in CI one round at a time: the hub's per-human tables test,
`make -C web shapes`, `make -C web fixtures` and `make -C web check`. It
fails while any of them fails or leaves the work tree changed. Commit what
it rewrote. Add a field the check names to the fixture under
`web/fixtures/` by hand; `web/tools/fixture-shapes-baseline.json` is never
extended for it. It needs a clean work tree to start, so after a red run commit
what it rewrote (or `git checkout -- .`) before the next one. Exit 2 means
the guards could not run, and it never ends in 0 then.

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
- A factual sentence in a pull request text or a review request about
  main ("already on main", "main did not touch these files"), about GitHub,
  or that the old head is red names the command, the head it ran on and the
  command's full output.

## Before the first review

- A card for a tool or a security-relevant change carries a `Boundary:`
  paragraph in its body before the first review order: what the change
  guarantees, what it does not, and what counts as P3. The review lead
  quotes it to all three reviewers in round one.
- A web pull request that adds a hub route or a non-admin caller path adds,
  in its first push, the route to the fixtures and one smoke case per
  caller path. Its review request names the caller paths the smoke covers.

## Local test environment

Everything runs on the machine you work on; there is no shared test system.

- **Hub:** in `hub/`, `make install` into a venv of its own, then `make check`, which
  runs the whole suite with one worker per core; on the machine the project's agents
  share, `make lint typecheck` and the affected test files instead (below). The tests
  run on SQLite by default, one file per test (`hub/README.md`, "Develop").
- **Hub on PostgreSQL:** `scripts/with_postgres.sh pytest -n 2 <test files>` from
  `hub/`; it starts a local server and gives the run a database of its own. Without a
  system PostgreSQL, the `pgserver` package brings the server (`hub/README.md`).
- **CLI:** in `cli/`, `make dev`, then `make check`. The tests need neither a
  database nor a running hub: they talk to a hub on loopback in the test itself
  (`cli/tests/fakehub.py`).
- **A shared machine:** at most two workers per run and heavy runs in a slot
  (`tools/run_slot.sh`); on the machine the project's agents share, only the test files
  a change affects, never the full hub suite. The next section has the rules.

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
- **No full hub suite on the agents' machine** (since 2026-10-29, after the
  machine the project's agents share ran out of memory twice and crashed): there,
  run only the test files a change affects, with at most `pytest -n 2`, and leave
  the full suite to the pull request's CI. On a machine of your own the full suite
  may run.

A branch cut before the run slots (#1302) has no `tools/run_slot.sh`, and
there `make smoke` and `with_postgres.sh` take no slot by themselves. Merge
`main` into such a branch only where that is allowed anyway (a conflict, or
the lead asks for it); otherwise run `main`'s copy of the script, which needs
nothing else from the checkout, without changing the branch:

```sh
( slot=$(mktemp) && trap 'rm -f "$slot"' EXIT && git show origin/main:tools/run_slot.sh > "$slot" && bash "$slot" make -C web smoke )
```

The subshell removes the copy on its way out and still ends with the command's
status, so a failed run stays a failure.

## Commits

Imperative, plain English, one concern per commit:
`hub: claim tasks with a lease`. A handful of meaningful commits per
feature; `context/` entries are the exception and get one each.

## During a review and in a stack

- Fixes after a review are pushed as one bundle once every review of the
  round is in, not after the first; an exception only on the lead's word.
- After the lower pull request of a stack is squash-merged, merge
  `origin/main` into the upper one instead of rebasing it.

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
