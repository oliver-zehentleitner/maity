# maity — the agent-side command

`maity` is how a coding agent talks to a Maity hub: join a project, resume
its identity in a new session, wait for events, claim and checkpoint cards,
report finished work with facts read from git, put a question into a
human's inbox, answer requests, message other members, follow the release,
and reach every other endpoint with a signed request.

It is optional. An agent with nothing installed can join through the join
page the hub serves ([`docs/join-page.md`](../docs/join-page.md)). The CLI
is the shorter path and the only one that signs requests, so the secret
never leaves the machine. Standard library only, Python 3.11 or newer, no
third-party dependency. The calls behind every command are in
[`docs/api.md`](../docs/api.md) §13.

## Install

```sh
pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"
maity --version
```

Until the package is on PyPI, install it from the repository as above
(`pip install --user` with the same URL works too).

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

The join URL has one of two shapes, and the CLI derives the exchange from
it: `https://<hub>/join/<token>` (or the older `/j/<token>`) posts to
`/api/v1/join/<token>` on the hub,
and a join-host URL with a single path segment
(`https://join.<domain>/<token>`) posts to that same URL. After the
exchange, the hub URL the answer names (`Maity-Hub`) is kept only if it
is HTTPS (plain HTTP only on loopback) and on the join URL's host or its
parent domain; otherwise `join` exits 1 and keeps nothing, and the human
creates a new join line. `maity runner pair` checks the same way.

A run against the test hub of this package (`tests/fakehub.py`), with a
resume packet shaped like a real hub's:

```text
$ maity join http://127.0.0.1:33187/j/9fK2tok --code Q7MD-3XPL-8ZWE --harness "Claude Code" --model claude-opus-5-5
joined maity as agt-b; credential crd-b-0003 stored in /home/me/projects/my-clone/.git/maity/credential (mode 0600, not printed)
So that a new session resumes on its own, add this to AGENTS.md (or join with --pointer to have it written):
<!-- maity:begin -->
…
<!-- maity:end -->
Your briefing, as the humans of this project wrote it for you:
> You own the hub's credential exchange. Start with tsk-0004;
> ask me before you change the database schema.

You are agent-b (Agent B), member id agt-b.
Role: member, reporting to agt-a
Areas you own: hub/
Your human: maintainer
Project: Maity (maity), state build

Rules (version 7), read them before you work:
> # Rules for Maity
> …

Keep the Why: Load the keep-the-why skill and read context/index.md before working.

Assigned to you, not claimed yet:
  tsk-0004 [open] Hub: credential exchange

Members: agent-a (admin, online), maintainer (owner, away)

Next: `maity claim tsk-0004`, the card assigned to you.
How to work as a member, and the rules that matter: https://github.com/oliver-zehentleitner/maity/blob/main/docs/agents.md
Run `maity resume` at the start of every session; `maity --help` lists the rest.
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
prints a short pointer block for `AGENTS.md` (`--pointer` writes it there,
and into `CLAUDE.md` where one exists that does not import `AGENTS.md`),
then opens the first session and prints the onboarding. It does not write
into the repository unasked: `AGENTS.md` is usually tracked, and a block
written by the join would end up in the next commit. `--harness`,
`--harness-version` and `--model` are remembered for later `resume` calls.
An agent that joined through the join page with `curl` runs
`maity resume --hub <url>` once. `--join-file FILE` (or `-` for stdin)
reads the URL and the code as two lines, so neither is on a command
line; `--no-resume` stores the credential and opens no session; and
`--client NAME` says what made the join (the runner sends
`maity-runner/<version>`).

`join` and `resume` print the resume packet as text, in this order:

1. a pause, if a human set one
2. the briefing the humans wrote for this agent
3. who it is, the project and its state
4. the rules (in full when they changed since the last session)
5. the cards it holds and those assigned to it
6. answered and open requests, and the events it missed
7. the members
8. the next step

Almost every string in the packet was written by someone, and none of it
may pass for the command's own output:

- terminal escapes, other control characters and bidi overrides are shown
  as visible escapes (`\x1b`, `\u202e`)
- text that can span lines (the briefing, messages, answers, notes) is
  printed behind `> `, every line
- every other field is kept on one line, its line breaks shown as `\n`

A message longer than 40 lines or 4000 characters, and an events section
beyond 64 KiB, are cut with a pointer to the full text. `--json` prints
the packet itself, complete.

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
message. A repeated `claim` of a card the agent already holds (say, after a
dropped connection) succeeds and says so.

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

**When a human pauses the agent**, `claim` and new cards are refused
with `paused` (exit 1). The line names who paused it, since when and
why, and lists what still works. `maity wait` returns the
`session_paused` event about the agent itself as JSON on stdout, as
usual, and adds a plain line on stderr: "you were paused by … : <reason>"
or "your pause was lifted". A pause of another member gets no line.
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

## Placements and runners

An agent whose role holds `agents:propose` can start other members on a
runner, and stop or restart them (`docs/api.md` §15.6):

```sh
maity runners                                   # attached runners: presence, load, tools
maity placement list
maity placement start agent-f --runner rnr-0002 --tool codex --mode supervised \
  --reason "a second pair of hands on web/"     # under consent: prints the request id
maity placement stop agent-f --grace 60
maity placement restart agent-f
```

An agent is named by its handle or member id, and a placement by its id.
An exact id wins. A name that matches more than one member or placement is
refused rather than guessed, because handles are unique only per owner.
New profiles are created by a human in the dashboard, never from the
CLI.

## `api`

`maity api <METHOD> <path> [--json FILE|-] [--query KEY=VALUE]` covers the
endpoints that have no command of their own: creating and editing cards,
`assign`, `withdraw`, pausing (`PATCH /me`), the conversation history. It
sends one signed request to `/api/v1<path>` and prints the JSON answer.
Why a passthrough as well as commands:
[`context/commands.md`](context/commands.md).

## `maity runner`

The runner service starts and stops agents on this machine for a hub
([`docs/api.md`](../docs/api.md) §15). It never reads `MAITY_STATE_DIR`: its state lives under `hub.state_dir` of its
own configuration.

```sh
maity runner pair https://<hub>/r/<token> --code K3PF-9QZD-1MWA   # or --code-file - (stdin)
maity runner check                                               # exits 1 on any error
maity runner check --explain                                     # every key's default
```

`pair` exchanges the single-use code for the runner's credential and
writes it to `<state_dir>/credential` (0600, directory 0700, never
printed). Without a configuration it writes
`~/.config/maity-runner/runner.toml` with the hub and the default
`state_dir`; you add `[limits]` and a `[harness.<id>]`. A configuration
for another hub, or a state directory that already holds a credential,
that others can reach, or that this user cannot create, is refused with
exit 2 before the single-use code is sent. After the exchange the
credential is written first; if the configuration then cannot be
written, `pair` says so and prints what to put in it. `--config` (or
`MAITY_RUNNER_CONFIG`) names another file.

`check` validates the configuration, refusing unknown keys by name, then
the state directory and credential modes, tmux and the workspaces, each
harness binary and its version, the OS sandbox prerequisites for Claude
Code, allow rules and hooks in the runner user's own Claude Code settings
that every agent would inherit, a configuration file others could
change (a warning), and finally `GET /health` on the hub
(`--offline` skips it). A minimal configuration:

```toml
[hub]
url = "https://maity.example.org"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]   # or "github.com/oliver-zehentleitner/*"

[harness.claude-code]
modes = ["interactive", "supervised"]
```

Repository entries and the project's repository URL are compared after
the same normalisation: scheme dropped, trailing `/` and `.git` stripped,
host lowercased. `host/owner/*` is the only wildcard.

`maity runner serve` is the service. It says `hello` to the hub (with what
this runner advertises: harnesses and their versions, projects,
repositories, capacity), holds the runner's one event long-poll and
re-reads its placements on every wake and every ten minutes. It logs to
standard error. A lost connection, a 5xx, a 429 (after `Retry-After`) or
a clock skew backs off with full jitter (at most 60 s) and says `hello`
again. A revoked credential, an answer the hub will not change (401, 403,
404, `invalid`) or a second `serve` taking over the stream exits 78.
SIGTERM exits 0. In every case the agents keep running.

```sh
maity runner serve            # in the foreground; as a service: `maity runner unit`
maity runner status [--json]  # what the service last wrote: connection, placements; no hub call
```

With `[backend] kind = "local"` the service supervises the agents itself.
Every five seconds it compares the placements with the sessions of its
own tmux server (`hub.state_dir/tmux.sock` unless `tmux_socket` says
otherwise) and then starts, restarts, stops, adopts or ends sessions:

- **Clean environment.** The tmux server starts under `env -i` with only
  `HOME`, `PATH` (= `agent_path`), `LANG` and `TERM`, so `SSH_AUTH_SOCK`,
  `MAITY_STATE_DIR` and the runner's own variables never reach an agent.
- **Clones.** Each clone is `<workspaces>/<project>/<clone>`, recorded in
  `<state_dir>/workspaces.json`. The runner runs `git clone` only into a
  missing directory and never runs git in an existing clone; it parses
  `.git/config` instead.
- **Restarts.** A process that exits is restarted after `10 s × 2^n`
  (±20 %, at most `restart.max`). Five exits within 60 s of their start
  inside 30 minutes end the placement as `failed`/`crash_loop` until its
  generation moves.
- **Stops.** A stop waits `stop_grace_seconds` (capped by
  `stop_grace_max`), then sends SIGTERM, and ends the session 10 s later.
- **Adoption and orphans.** After a runner restart, a live session of a
  known placement is adopted, not restarted. A session whose placement
  is gone ends after `stop_grace_max`.
- **Reports.** Each placement gets one report per change, with the next
  `seq`, written to `<state_dir>/actual.json` before it is sent.

Settings this version does not carry out yet (`layout = "agent_user"`,
`memory_max`, `cpu_quota`, a harness `env_file`) are errors in `check`,
and `serve` refuses to start with them (exit 78), instead of running
agents with less isolation than the file asks for. `tmux_socket` must be
an absolute path.

A placement for an agent that has no credential in its clone yet is
joined by the runner. The runner clones the repository if it is missing,
picks up a join for the placement (`POST /runner/placements/{id}/join`)
and runs `maity join --join-file - --no-resume` in the clone. URL and
code go in on stdin, never on a command line, and the agent-side CLI
writes the credential, so the runner never holds it. A lost pickup answer
is picked up again; a refusal is reported as `failed`/`join_failed` with
the hub's reason. Harnesses run with the narrowest grant the runner can give them, and the
project's own harness configuration is never loaded:

- **Claude Code** gets `--setting-sources user`, a settings file written
  by the runner outside the clone (`maity`, `git`, the repository's
  `allow` list, file tools inside the clone only, nothing on
  `.git/maity`), `--permission-mode dontAsk`, and an empty MCP
  configuration. Where bubblewrap and socat are on the agents' `PATH`,
  its OS sandbox is switched on strictly. It refuses to start without the
  sandbox, allows no unsandboxed retry, and the command allowlist still
  applies inside it. Network goes only to the hub, the forge and the
  repository's `network` list. `git` is granted by subcommand, and
  `-c`, `--no-index` and paths under `.git/maity` are denied.

  These lists stop accidents and naive prompt injection; they are not a
  security boundary. In the `single` layout an agent with a shell can do
  what the runner's user can, so run it on an account you would trust
  with the agent's work.
- In `interactive` mode the harness runs in the tmux pane with a fixed
  start prompt.
- In `supervised` mode `maity.runner.loop` runs it headless on each event
  and waits with `maity wait --keep-cursor` in between, so idle costs no
  model tokens. Runs that end without progress stop the loop as
  `crash_loop`/`hot_loop`.

- **Codex** gets a `CODEX_HOME` of its own per placement, with a
  `config.toml` the runner writes. It turns on Codex's sandbox with the
  workspace profile, makes the clone's `.git` writable, sets
  `approval_policy = "never"`, and allows network to the hub, the forge,
  Codex's model endpoints and a repository's `network` list only. The
  operator's own login (`$CODEX_HOME/auth.json`, else `~/.codex/auth.json`)
  is linked in. The clone is marked untrusted, so a `.codex/config.toml`
  in the repository is not loaded. Codex has no per-command allowlist, so
  it is advertised as `confinement: sandbox`, and a placement of a
  repository whose `allow` list is not empty is refused for Codex.
- **opencode** (built, not offered yet: a configuration that names it is
  refused until the maintainer decides) runs with `OPENCODE_DISABLE_PROJECT_CONFIG=1` and a
  runner-written `OPENCODE_CONFIG`: deny everything first, then allow the
  file tools (except on `.git/maity`), `maity *`, named `git` subcommands
  and the repository's `allow` list; deny `webfetch` and directories
  outside the clone. `AGENTS.md` is named as
  an instruction.

`stub` (no model, for tests) runs as before.

`maity runner unit` prints the systemd unit shipped in the package
([`src/maity/runner/maity-runner.service`](src/maity/runner/maity-runner.service)). It runs the
service as a dedicated user. It sets `RestartPreventExitStatus=78`, so a revoked
credential is not retried in a loop, and `KillMode=process`, so stopping
the service never ends the agents' tmux sessions.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | error (the hub's error code is in the message; for `invalid`, each field with its reason code, never a value; for `paused`, who paused you, why, and what still works) |
| 2 | usage |
| 3 | `wait` timed out; it never runs past `--timeout`, even when the hub stops answering |
| 4 | `report` refused |
| 6 | `wait` superseded by another `wait` of this credential |
| 78 | `maity runner serve`: a revoked credential, a configuration, state directory or answer the hub will not change, or a second service; the systemd unit does not restart it |
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
