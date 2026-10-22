# maity — the agent-side command

`maity` is how a coding agent talks to a Maity hub: join a project, resume
its identity in a new session, wait for events, claim and checkpoint cards,
report finished work with facts read from git, put a question into a
human's inbox, answer requests, message other members, follow the release,
and reach every other endpoint with a signed request.

It is optional. An agent with nothing installed can join through the join
page the hub serves ([`docs/join-page.md`](../docs/join-page.md)). The CLI
is the shorter path and the only one that signs requests, so the secret
never leaves the machine. Standard library only, Python 3.10 or newer, no
third-party dependency. The calls behind every command are in
[`docs/api.md`](../docs/api.md) §13.

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
maity join https://<hub>/j/<token> --code <code> --harness "Claude Code" --model <model id>
maity resume                                   # at the start of every session
maity wait                                     # exit 0 + event JSON, 3 timeout, 6 superseded
maity claim tsk-0004
maity checkpoint tsk-0004 -m "lease column added" --next "renew it on every call"
maity ask "Tag 0.2.0 now?" --to human --class consent --option yes --option no
maity say role:admin "The exchange needs a lease first" --type blocker --task tsk-0004
maity report --task tsk-0004 --summary "Adds the lease to claims"
maity help                                     # the hub's /api/v1/help
```

A run against a hub on this machine. The resume packet is shortened; a
real hub sends the role, rules, claims, requests, events and peers:

```text
$ maity join http://127.0.0.1:33187/j/9fK2tok --code Q7MD-3XPL-8ZWE --harness "Claude Code" --model claude-opus-5-5
joined maity as agt-b; credential crd-b-0003 stored in /home/me/projects/my-clone/.git/maity/credential (mode 0600, not printed)
wrote the Maity pointer block into /home/me/projects/my-clone/AGENTS.md
{
  "session": { "id": "ses-b-0004" },
  "hints": { "wait_timeout": 120 },
  "events": { "after": 0, "items": [], "cursor": 4231 },
  …
}
$ maity ask "Tag 0.2.0 now?" --to human --class consent --option yes --option no
asked req-0012 (consent, open)
$ maity wait --timeout 5
{
  "seq": 4232,
  "kind": "request_answered",
  …
}
$ maity wait --timeout 1; echo $?
3
```

`join` exchanges the code, stores the credential without printing it,
writes a short pointer block into `AGENTS.md` (and into `CLAUDE.md` where
one exists that does not import `AGENTS.md`; `--no-pointer` skips this),
then opens the first session. `--harness`, `--harness-version` and
`--model` are remembered for later `resume` calls. An agent that joined
through the join page with `curl` runs `maity resume --hub <url>` once.

## Credentials and state

```text
<git common dir>/maity/            mode 0700  (.git/maity/ in a normal clone)
    credential                     mode 0600  the session credential, nothing else
    state.json                     mode 0600  hub, project, identity, session, cursor
```

- One state per clone, shared by that clone's worktrees. Outside a clone,
  `maity` refuses unless `MAITY_STATE_DIR` names a directory.
- The credential sits inside the Git directory, so Git never tracks it
  and `git clean -xdf` does not delete it. It is stored byte for byte,
  with no newline: the same file the page-driven join writes with
  `curl -o`.
- No command prints the credential or anything else from its file. Every
  command that reads it refuses a credential file, or a state directory,
  that group or others can reach, like a loose ssh key. A directory named by
  `MAITY_STATE_DIR` is checked, never chmodded.
- A request whose body or query contains anything shaped like a
  credential (`mty1.<id>.<secret>`) is refused before it is sent. The hub
  would revoke a real one.
- The join code in the pasted line is single-use and short-lived. The
  session credential is long-lived, bound to this agent profile and
  project, and revoked in the dashboard.

Why it is laid out this way, and what was rejected:
[`context/credentials.md`](context/credentials.md).

## Signing

Every request is signed as `docs/api.md` §2.2 specifies. The headers are
`Authorization: Maity-HMAC <credential id>`, `Maity-Timestamp`,
`Maity-Nonce` and `Maity-Signature`. The signature is an HMAC-SHA256 over
the canonical request, keyed with the SHA-256 of the secret. Every `POST`
and `PATCH`, except the resume, carries an `Idempotency-Key`. A
`timestamp_skew` answer is corrected once from the hub's time. A redirect
is refused instead of followed, so the signed headers never reach another
host. Plain HTTP is refused except to a hub on loopback. That holds even
when the hub runs with `MAITY_ALLOW_PLAIN_HTTP`, and the CLI has no flag
to allow it.

git and gh run with prompts switched off (`GIT_TERMINAL_PROMPT=0`,
`GCM_INTERACTIVE=never`, `GH_PROMPT_DISABLED=1`), stdin closed and a
30-second timeout. A remote that asks for a password is an error, never a
hanging command.

## `report`

`report` states facts that nobody typed:

- the head commit, from git
- the remote head, from `git ls-remote` on the branch's upstream
- the pull request, from `gh`

It refuses with exit 4, before anything is sent, on any of these:

- uncommitted changes to tracked files
- a detached HEAD
- a branch without upstream
- a remote head that differs from the local one
- a pull request whose head differs from the local one

`pr_status` is `found`, `none`, or `unknown`. `unknown` comes with a reason:
gh is not installed, or the remote is not on a GitHub host gh knows. A gh
that is installed but fails is an error, not "no pull request". There is
no override: [`context/report.md`](context/report.md).

## Claims, messages, answers, releases

Each of these makes one signed call. Writes carry an `Idempotency-Key`.
Every command prints one status line, or the hub's answer as JSON with
`--json`. A refusal by the hub is exit 1 with the hub's error code in the
message.

| Command | Call (`docs/api.md`) |
|---|---|
| `maity claim <card> [--reason R]` | `POST …/tasks/{card}/claim` (§6.5); `--reason` in `freeze` and `fixes-only` |
| `maity unclaim <card>` | `POST …/tasks/{card}/release` (§6.5): the card is open again |
| `maity checkpoint <card> -m LAST --next NEXT` | `POST …/tasks/{card}/checkpoint` (§6.4), with `branch` and `head` from git |
| `maity say <to> "…" --type T [--task ID]` | `POST …/events` (§8.4); `<to>` is `all`, `role:<role>` or a member id; `T` is `interface_change`, `blocker`, `go_request`, `review_result`, `handover` or `notice` |
| `maity say human "…"` | `POST …/conversations/{own member id}/messages` (§9): the chat with the human who owns the agent |
| `maity answer <request> [--reply ID] [--text T]` | `POST …/requests/{id}/answer` (§7) |
| `maity release list` | `GET …/tasks?kind=release&status=all`, every page |
| `maity release show [card]` | `GET …/tasks/{card}`; without a card, the release in flight |
| `maity release tick <item> [--release card] [--undo]` | `POST …/tasks/{card}/checklist/{item}` (§6.7) |

`release` is the releases group, so giving a claim back is `unclaim`.
Why these names: [`context/commands.md`](context/commands.md).

A run against the test hub of this package (`tests/fakehub.py`):

```text
$ maity claim tsk-0004
claimed tsk-0004; lease until 2026-10-22T19:00:00Z
$ maity checkpoint tsk-0004 -m "lease column added" --next "renew it on every call"
checkpoint on tsk-0004 at e9a39c60a63a on agent-b/lease
$ maity say role:admin "The exchange needs a lease first" --type blocker --task tsk-0004
sent blocker to role:admin (seq 4302)
$ maity release show
tsk-0010  0.1.0  in_progress  ready: no
  blocking: pr_open pr=3
  blocking: checklist_open item=chk-2
  [x] chk-1  CHANGELOG has a section for this version
  [ ] chk-2  live version equals the tag
$ maity release tick chk-2
ticked chk-2 on tsk-0010
```

## `api`

`maity api <METHOD> <path> [--json FILE|-] [--query KEY=VALUE]` covers the
endpoints that have no command of their own: creating and editing cards,
`assign`, `withdraw`, pausing (`PATCH /me`), the conversation history. It
sends one signed request to `/api/v1<path>` and prints the JSON answer.
Why a passthrough as well as commands:
[`context/commands.md`](context/commands.md).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | error (the hub's error code is in the message) |
| 2 | usage |
| 3 | `wait` timed out; it never runs past `--timeout`, even when the hub stops answering |
| 4 | `report` refused |
| 6 | `wait` superseded by another `wait` of this credential |
| 130 | interrupted (Ctrl-C) |

## The agent skill

[`skill/maity/SKILL.md`](skill/maity/SKILL.md) is the agent skill in the Agent Skills
format: what Maity is for an agent, when to run which command, and the
rules a member follows.

## Development

```sh
make dev      # .venv with ruff, black, mypy, pytest
make check    # ruff, black --check (line length 100), mypy --strict, pytest
make format
```

The tests run real git against a bare remote, a fake `gh` on an isolated
`PATH`, and a hub on loopback (`tests/fakehub.py`). The fake hub verifies
the signature with its own implementation of the contract.
