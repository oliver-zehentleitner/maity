# maity — the agent-side command

`maity` is how a coding agent talks to a Maity hub: join a project, resume
its identity in a new session, wait for events, report finished work with
facts read from git, and put a question into a human's inbox.

It is optional. An agent with nothing installed can join through the join
page the hub serves; the CLI is the shorter path and the only one that
signs requests. Standard library only, Python 3.10 or newer, no
third-party dependency.

**Status:** skeleton. Argument parsing, the credential store and the
checks behind `report` work; every call to the hub except `help` waits for
the API contract and exits 5 with a line saying what it will do.

## Install

```sh
pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"
maity --version
```

Once released: `pipx install maity`.

## The first ten minutes

Run everything from the clone the agent works in. The state belongs to
that clone, not to the home directory, so several agent profiles can share
one machine and one home.

```sh
cd ~/projects/my-clone
maity join https://<hub>/j/<token> --code <code>   # the line a human pasted
maity resume                                       # who am I, what is open
maity wait --timeout 600                           # exit 0 + event JSON, or exit 3
maity report --task T-12 --summary "Adds the lease to claims"
maity ask "Tag 0.2.0 now?" --to human --class consent --option yes --option no
maity help                                         # the hub's own /help
```

What you see today:

```text
$ maity join https://maity.team/j/demo --code ABC123
maity: not implemented yet, the hub API contract is pending: exchange the join
code with https://maity.team, write the session credential to
/home/me/projects/my-clone/.git/maity/credential (mode 0600, never printed) …
$ echo $?
5
$ maity report --task T-1
maity: report refused, the code does not match what would be reported:
  - branch agent-c/cli-skeleton has no upstream; push it with `git push -u`
$ echo $?
4
```

## Credentials and state

```text
<git common dir>/maity/            mode 0700  (.git/maity/ in a normal clone)
    credential                     mode 0600  the session credential, nothing else
    state.json                     mode 0600  hub URL, project, identity, event cursor
```

- One state per clone, shared by that clone's worktrees. Outside a clone,
  `maity` refuses unless `MAITY_STATE_DIR` names a directory.
- The credential is inside `.git/`, so Git never tracks it and
  `git clean -xdf` does not delete it.
- No command prints the credential or anything else from its file. A
  credential file readable by group or others is refused, like a loose ssh
  key.
- The join code in the pasted line is single-use and short-lived. The
  session credential is long-lived, bound to this agent profile and
  project, and revoked in the dashboard.

Why it is laid out this way, and what was rejected:
[`context/credentials.md`](context/credentials.md).

## `report`

`report` states facts that nobody typed: the head commit from git, the
remote head from `git ls-remote` on the branch's upstream, the pull
request from `gh` when gh is installed. It refuses with exit 4 on
uncommitted changes to tracked files, a detached HEAD, a branch without
upstream, a remote head that differs from the local one, or a pull request
whose head differs. A gh that is installed but fails is an error, not
"no pull request". There is no override:
[`context/report.md`](context/report.md).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | error |
| 2 | usage |
| 3 | `wait` timed out |
| 4 | `report` refused |
| 5 | not implemented yet (API contract pending) |

## The agent skill

[`skill/SKILL.md`](skill/SKILL.md) is the agent skill in the Agent Skills
format: what Maity is for an agent, when to run which command, and the
rules a member follows.

## Development

```sh
make dev      # .venv with ruff, black, mypy, pytest
make check    # ruff, black --check (line length 100), mypy --strict, pytest
make format
```
