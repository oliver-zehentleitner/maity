# Runner

## The configuration refuses unknown keys and documents every default; tomllib only from 3.11

**Id:** f2a34d72-f074-474c-87bb-2d8c6bccd60e
**Type:** decision
**Status:** superseded
**Superseded by:** 4bc67bf6-75e1-4fbf-b665-4f9bd04cf908
**Evidence:** confirmed
**Source:** runner design v2 §5.1 and §12 question 7; the coordinator's binding answers on the runner configuration, 2026-10-22
**Revisit when:** the CLI's floor moves to Python 3.11, or the dashboard's pairing panel generates keys `check` does not know

`maity runner` reads a TOML file (`~/.config/maity-runner/runner.toml`,
`--config` or `MAITY_RUNNER_CONFIG`). Only `hub.url`, `limits.projects`,
`limits.repositories` and one `[harness.<id>]` are required; every other
key has a default, and `maity runner check --explain` prints them all.
Unknown keys are refused with their full dotted name. `tomllib` is
imported only on 3.11 or newer; on 3.10 every `maity runner` command
refuses, and the rest of the CLI keeps its 3.10 floor.

**Reason:** the dashboard writes a starter file trimmed to the required
keys, so the defaults have to be the documented ones and nothing else; a
typo that silently fell back to a default would widen or narrow what a
runner may do without anyone noticing, which is the same reason the API
refuses unknown fields. Gating `tomllib` keeps agent hosts on 3.10 working,
since agents need `maity join` but not the runner.

**Rejected alternatives:**
- Moving the whole CLI to 3.11 (the design's draft assumption): every agent
  host would need 3.11 for a feature only runner hosts use.
- A vendored TOML parser or JSON configuration on 3.10: a third-party
  parser breaks the stdlib-only rule, and JSON gives operators no comments
  in a file they edit by hand.
- Ignoring unknown keys with a warning: a warning on a service's start is
  easily missed, and the key decides what agents may touch.

## Repository entries and project URLs go through one normalisation

**Id:** b1571548-5a54-476c-bb1c-b32a669cf7e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's binding answers on the runner configuration, 2026-10-22
**Revisit when:** a forge is supported whose repository paths are not `owner/name`, or owners ask for a narrower glob

`limits.repositories` accepts `host/owner/name` and one wildcard form,
`host/owner/*`. Config entries and the project's `repository.url` are
both reduced by `normalise_repository`: scheme and user dropped, trailing
`/` and `.git` stripped, host lowercased; owner and name keep their case.

**Reason:** the dashboard writes `github.com/owner/name` while the hub
stores URLs like `https://GitHub.com/owner/name.git`. Normalising only one
side would make a runner refuse its own project. One owner-wide form
covers the real case (all of an organisation's repositories) without a
glob language whose matches an operator has to reason about.

**Rejected alternatives:**
- General globs in owner and name (an early draft of this module): `*`
  and `?` anywhere make it hard to see what an entry admits, and nothing
  needed them.
- Lowercasing owner and name too: forges differ on case sensitivity of
  paths, so only the host, which is case-insensitive everywhere, is folded.

## `pair` reads only `[hub]` of an existing file and refuses before sending

**Id:** 50e407f3-e2ef-4ee2-a574-932b09e67669
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's binding answers on the runner configuration, 2026-10-22 (starter file, refusal for another hub); `docs/api.md` §13 (`--code`); implementation of runner slice R1, 2026-10-22 (reading only `[hub]`); the coordinator's review of R1, 2026-10-22 (checks before the exchange, credential first)
**Revisit when:** pairing needs anything from the configuration beyond the hub and the state directory

`maity runner pair` reads only `hub.url` and `hub.state_dir` of an
existing configuration, not the whole file. Without one, it writes a
starter file with those two keys (0600, directory 0700) after a
successful exchange. A configuration for another hub, or a state
directory that already holds a credential, others can reach or this
user cannot create, is refused with exit 2 before the code is sent.
After the exchange the credential is written first, then the
configuration; an existing configuration directory is taken as it is,
since the file holds no secret. The code comes from `--code`, as in the contract, or
`--code-file` (`-` for stdin).

**Reason:** the starter file `pair` writes is incomplete until the
operator adds limits and harnesses; validating the whole file would make
re-pairing after a revocation fail on a file `pair` itself wrote. The
exchange spends the enrollment and the credential exists nowhere else, so
everything that could stop it being stored is checked before the code is
sent, and the credential is the first thing written: a configuration that
cannot be written can be typed by hand, a lost credential means a new
enrollment and a live runner credential nobody holds. `--code-file` keeps the code out of the shell
history and the process list.

**Rejected alternatives:**
- Full validation in `pair`: see the reason; `check` is where the whole
  file is validated.
- Writing the configuration first and requiring 0700 of its directory
  (the first version): a `~/.config/maity-runner` made 0775 by the
  operator failed the pair after the exchange and lost the credential.
- Overwriting the configuration of another hub: it would orphan that
  runner's credential and state without a word.

## `serve` ends with 78 on anything retrying cannot fix, and never takes the agents with it

**Id:** e210a162-44c7-4efd-9176-c3c3f66b3e63
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.2, §8 and §10.1; implementation of runner slice R2, 2026-10-22 (which answers count as fatal, the superseded stream, `KillMode`)
**Revisit when:** the hub gains a reason to answer a runner 4xx that a later retry could clear, or the runner runs more than one service per credential by design

`maity runner serve` backs off and says `hello` again only on no answer,
a 5xx, 408, 429 or a clock skew. A revoked credential, any other 4xx and
`superseded: true` on the event stream end it with exit 78, which the
systemd unit does not restart (`RestartPreventExitStatus=78`). SIGTERM
ends it with 0. The unit sets `KillMode=process`.

**Reason:** a service manager restarting a runner whose credential is
revoked, or whose hub refuses its capabilities, only produces a log loop.
Failing loudly once tells the operator what to fix. A superseded stream
means a second `serve` holds the same credential; restarting both would
make them supersede each other forever. On one host a lock on the state
directory refuses the second service at its start, so the running one
keeps the stream. A state directory the service cannot write ends it with
78 too, so a unit pointed at the wrong path does not restart every ten
seconds. The agents run in a tmux server
the runner started, inside the unit's cgroup, so systemd's default
`KillMode=control-group` would end every agent on a service restart. The
design keeps agents running across runner restarts and hub outages, so
only the runner's own process may be signalled.

**Rejected alternatives:**
- Retrying every error with backoff: hides a revoked credential or a
  wrong configuration behind an endless reconnect.
- Backing off on `superseded` and reconnecting: two services would take
  the stream from each other in turn.
- Leaving `KillMode` at its default: a `systemctl restart` for an
  upgrade would end every agent mid-work.
- `PrivateTmp` in the unit: with the agents outliving the service, the
  next start would replace their `/tmp` under them.

## Capabilities say `sandbox: off` until an adapter switches a sandbox on

**Id:** 0e700858-b898-4d5d-b230-b5d9ce3e0941
**Type:** decision
**Status:** superseded
**Superseded by:** 3c074f5a-6245-4fd9-82a2-09b543738394
**Evidence:** confirmed
**Source:** `docs/api.md` §15.3 (`sandbox`: the harness's own OS sandbox); implementation of runner slice R2, 2026-10-22
**Revisit when:** the harness adapters (R5) enable a harness's own sandbox when it starts

Every real harness is advertised with `sandbox: "off"` and `stub` with
`"n/a"`, whatever `check` finds about the prerequisites. The version is
the first dotted number in the `--version` output, cut to printable ASCII.

**Reason:** the field tells a human choosing a runner how far the
harness is confined. Bubblewrap being installed does not mean the
runner starts the harness with its sandbox on; until an adapter does
that, `on` would overstate the confinement.

**Rejected alternative:** derive `on` from the prerequisites, as `check`
reports them; that describes the machine, not how the agent runs.

## A placement the runner cannot act on yet is logged, not reported as a failure

**Id:** 5ed066bf-d571-489f-902c-1097d3a6b6e8
**Type:** decision
**Status:** superseded
**Superseded by:** 5d71ccda-d931-460f-aa82-1438221cf2c9
**Evidence:** confirmed
**Source:** `docs/api.md` §15.7 (closed reason list); implementation of runner slice R3, 2026-10-22
**Revisit when:** the harness adapters (R5) are in; then this case no longer exists

While only the `stub` adapter exists, a placement for another harness is
left as it is (until R4, a placement that needed a join was too). It gets no
report, and the runner logs one line naming the missing slice. A start
that fails in tmux itself is reported as `failed`/`harness_missing`, and
the log line carries tmux's message.

**Reason:** §15.7's reason list is closed, and none of its codes means
"this runner version cannot do that yet". Reporting `failed` with a
code that names something else (`join_failed`, `harness_refused`) would
tell the human a wrong cause and make them act on it. With no report the
dashboard shows the placement as pending (`reported_current: false`),
which is what it is. A tmux failure is the closest the list has to "the
process cannot be started here", and the log keeps the real cause.

**Rejected alternatives:**
- Adding a reason code for it: a contract change for a state that lasts
  only until the next two slices merge.
- Starting a placement without its credential: the agent would run
  without an identity, against §15.5's rule that a missing expected
  credential is `join_failed`.

## The supervisor's deadlines are wall-clock times

**Id:** 8d3c5f39-21b9-4892-8a05-4816078637f4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's review of runner slice R3, 2026-10-22 (proposed `time.monotonic()`); kept in the review round
**Revisit when:** a runner host is seen whose clock jumps (no NTP), or the records stop being kept across runner restarts

`retry_at`, `deadline_at`, crash times and `since` are `time.time()`
values. They are persisted in `actual.json` and reported as RFC 3339
timestamps.

**Reason:** these times outlive the process. After a runner restart,
the record still has to say when a backoff ends and which crashes fall
inside the crash window, and the hub shows `retry_at` and `deadline_at`
as times of day. A monotonic clock restarts with every boot and means
nothing in another process. A clock step on the host moves a backoff or
grace deadline by that step, which NTP-synced hosts keep small.

**Rejected alternative:** `time.monotonic()` for the deadlines, as the
review proposed. Every persisted value would need converting at save
and load, and that conversion breaks at a reboot, which is exactly when
the records matter.

## Agents' tmux runs on a socket in the state directory, sessions named with underscores

**Id:** b4254a67-3690-4365-9e8a-e0daaa3a2425
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.4 (first `-L maity`, `maity-<project>-<clone>`); the coordinator's review of runner slice R3, 2026-10-22 (the name collision); `docs/api.md` §15.5 as amended to `-S`
**Revisit when:** agents run as their own OS user (the `agent_user` layout), where the server belongs to that user and its socket must lie where both can reach it

The runner's tmux server listens on `tmux -S <state_dir>/tmux.sock`, by
default (an absolute `tmux_socket` overrides it), not `tmux -L maity`.
Sessions are named `maity_<project>_<clone>` and matched by their
`@maity_placement` label, not by name.

**Reason:** `-L` puts the socket in `/tmp/tmux-<uid>/`, which the
operator's own tmux shares and which a service's private `/tmp` would
hide after a restart. In the runner's 0700 state directory the socket is
the runner's alone and survives a service restart along with the agents.
Project slugs and clone names may both contain `-`, so `maity-ab-cd-ef`
could be `ab` + `cd-ef` or `ab-cd` + `ef`. One project's live agent would
then be read as the other's orphan and killed. Both tokens are
`[a-z0-9-]`, so `_` cannot occur in either, and the label settles any
doubt.

**Rejected alternatives:**
- `-L maity`, as first designed: shared directory, and lost under
  `PrivateTmp`.
- Keeping `-` and parsing names more cleverly: the split is ambiguous
  by construction.

## The runner's `maity join` finds the clone's state without git

**Id:** 6f21f308-885a-4882-b043-162c3d582ed2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.3 (no git in agent clones) and §15.9; implementation of runner slice R4, 2026-10-22
**Revisit when:** the agent-side CLI keeps its state anywhere but `<clone>/.git/maity`, or the runner runs the join as a different user (the `agent_user` layout)

The runner runs `maity join --join-file - --no-resume --no-pointer` in
the clone with `MAITY_STATE_DIR` set to `<clone>/.git/maity`. Its
output is mapped to a `join_failed` detail and never logged.

**Reason:** without the variable, the CLI finds its state with `git
rev-parse` in the clone, a clone whose `.git/config` the agent may have
written. That would break the rule that the runner runs no git in an
existing clone. Its error output can name the join URL, so it can name
the token. `--no-pointer` keeps the join from writing into the
repository: the runner starts the session with its own prompt, so the
pointer block has nothing to do here.

**Rejected alternatives:**
- Letting the CLI call `git rev-parse`: a read-only command, but it reads
  the agent-writable config, and the rule is simpler kept whole.
- Logging the CLI's error text for diagnosis: a token in a log file
  outlives the join.

## Claude Code's sandbox runs strict or not at all

**Id:** 3c074f5a-6245-4fd9-82a2-09b543738394
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** Claude Code's sandboxing documentation (code.claude.com/docs/en/sandboxing), read 2026-10-22; the coordinator's review of runner slice R5a
**Revisit when:** Claude Code changes the defaults of `autoAllowBashIfSandboxed` or `failIfUnavailable`, or another harness gets an OS sandbox the runner switches on

Where bubblewrap and socat are on the agents' `PATH`, the runner's
settings for Claude Code turn the sandbox on with `failIfUnavailable`,
`allowUnsandboxedCommands: false`, `autoAllowBashIfSandboxed: false` and a
strict network allowlist (the hub, the forge, the repository's
`network` list). Capabilities then say `sandbox: on`. Without those tools
the session runs unsandboxed, `running` carries `detail:
sandbox_unavailable`, and `require_sandbox` refuses the placement.

**Reason:** the documented defaults would undo the point. If the sandbox
cannot start, Claude Code runs commands unsandboxed. A command that fails
inside the sandbox may be retried outside it. And sandboxed commands run
without the permission rules, so the command allowlist would no longer
apply. Each default has to be set the other way explicitly. Allowed
network domains start empty, so the hub and the forge have to be named, or
`maity` and `git push` fail.

**Rejected alternatives:**
- `sandbox.enabled` alone, as in the first version of R5a: a missing
  bubblewrap and the retry escape hatch would both run commands
  unsandboxed without anyone noticing.
- Leaving `autoAllowBashIfSandboxed` at its default: inside the sandbox
  every command would run, `curl` to any allowed host included.

## The command allowlists are not a boundary until agents run as their own user

**Id:** 2bdc5809-b08b-4fa2-97bc-004d37c4cddb
**Type:** constraint
**Status:** needs-review
**Evidence:** confirmed
**Source:** runner design v2 §6.1 ("`Bash(git *)` is not a boundary"); the coordinator's review of runner slice R5a, 2026-10-22 (`git diff --no-index` printed the clone's credential)
**Revisit when:** the `agent_user` layout (R7) or the Kubernetes backend makes the OS user or the pod the boundary

The runner grants named `git` subcommands, not `git *`. It denies `-c`,
`--config-env`, `--exec-path`, `--no-index`, `--upload-pack`,
`--receive-pack`, `--exec=` and any path under `.git/maity`. The file
tools cannot write anywhere under `.git` (its config and hooks would turn
an allowed `git status` into anything) and cannot read `.git/maity`. With
Claude Code's sandbox on, commands can neither read nor write
`.git/maity`; only `maity` itself runs outside the sandbox. Without the
sandbox, and for Codex and opencode, any repository code an allowed
build or test command runs can read the clone's credential.

**Reason:** git runs programs through its options and configuration, and
`diff --no-index` reads any file. A wildcard grant therefore meant "may
run anything", and in the `single` layout that includes reading the
agent's own credential and the runner's state. Naming subcommands and
denying the known escape routes stops accidents and naive prompt
injection. It does not stop a determined agent: aliases from the
operator's git configuration, test runners in a repository's `allow`
list, and build tools all execute repository code. Until agents run as an
OS user of their own, an agent with a shell is as trusted as the
operator's account. The operator docs say so.

**Rejected alternative:** a longer deny list that tries to close every
route. git's surface keeps growing, and a list that looks complete
would read as a boundary when it is not one.

## Codex reaches the operator's login through a link in its per-placement home

**Id:** 49caa654-c3ad-44c0-bdfd-3274aa2ddfa7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** runner design v2 §6.1 and §6.2 (a `CODEX_HOME` per placement); implementation of runner slice R5b, 2026-10-22; whether Codex rewrites `auth.json` on a token refresh is unverified (the design marks it *verify*)
**Revisit when:** a real Codex run shows the link replaced by a file, or the operator's login going stale while an agent's stays fresh

Each Codex placement gets its own `CODEX_HOME` under the runner's state
directory. A `config.toml` written by the runner sets the sandbox,
approvals and network rules. The operator's `~/.codex/auth.json` is
linked into it, not copied.

**Reason:** a per-placement home keeps `codex exec resume --last` from
picking up another agent's session and keeps the operator's own Codex
configuration out of the agents' runs. The login, though, is one account.
A copy would go stale when Codex refreshes the token in one place and
not the other, and the agents would start failing while the operator's
own Codex still works. A link keeps one file for both.

**Rejected alternatives:**
- Copying `auth.json` at every start: the copy can diverge after a
  refresh, and the next start would overwrite a newer token with an older
  one.
- Running Codex with the operator's own `CODEX_HOME`: every agent would
  see the operator's history and configuration, and `--last` would cross
  placements.

## Codex is confined by its sandbox, so it refuses command allowlists

**Id:** c2acd907-0f26-4850-8272-063390f1d6a7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of runner slice R5b by a member who runs Codex, 2026-10-22, and the coordinator's ruling on it
**Revisit when:** Codex gains a per-command allowlist the runner can write (an exec policy it honours in `exec` and the TUI), or the contract settles another `confinement` value

Codex placements are advertised with `confinement: "sandbox"`, not
`allowlist`. A placement for a repository whose `allow` list is not
empty is refused for Codex (`harness_refused`). The project's own
Codex configuration is kept out by marking the clone untrusted.

**Reason:** the runner's Codex profile limits files and network through
Codex's sandbox, but Codex has no command allowlist the runner can write.
Advertising `allowlist` would tell the human choosing a runner that
commands are filtered when they are not. A repository `allow` list would
look honoured while it is ignored. Refusing makes the gap visible. A
trusted clone would load a committed `.codex/config.toml` over the
runner's profile, and one reviewer saw that switch the sandbox off.

**Rejected alternatives:**
- Keep advertising `allowlist` and ignore the grant: a claim the runner
  cannot keep.
- Build an exec-policy layer for Codex now: unverified against the
  shipped Codex, and the sandbox already sets the boundary that matters.

## The configuration refuses unknown keys and documents every default; the CLI needs Python 3.11

**Id:** 4bc67bf6-75e1-4fbf-b665-4f9bd04cf908
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 7, relayed 2026-10-22; runner design v2 §5.1; the coordinator's binding answers on the runner configuration, 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — 22a7d470-4458-493b-8df6-08176d4abb13 — as of 2026-10-22
**Revisit when:** the dashboard's pairing panel generates keys `check` does not know

`maity runner` reads a TOML file (`~/.config/maity-runner/runner.toml`,
`--config` or `MAITY_RUNNER_CONFIG`) with the standard library's
`tomllib`. Only `hub.url`, `limits.projects`, `limits.repositories` and
one `[harness.<id>]` are required. Every other key has a default, and
`maity runner check --explain` prints them all. Unknown keys are refused
with their full dotted name. The whole CLI, agent commands included,
needs Python 3.11 or newer.

**Reason:** the dashboard writes a starter file trimmed to the required
keys, so the defaults have to be the documented ones and nothing else. A
typo that silently fell back to a default would widen or narrow what a
runner may do without anyone noticing, which is the same reason the API
refuses unknown fields. The maintainer chose one floor for the whole CLI
over a gate for the runner alone. One version line for agents and
operators to read, and no code path that exists only to refuse, outweigh
supporting hosts that only have 3.10.

**Rejected alternatives:**
- Gating `tomllib` to the runner while agent commands kept 3.10 (the
  first version): two floors in one package, and a refusal path to test.
- A vendored TOML parser or JSON configuration: a third-party parser
  breaks the stdlib-only rule, and JSON gives operators no comments in a
  file they edit by hand.
- Ignoring unknown keys with a warning: a warning on a service's start is
  easily missed, and the key decides what agents may touch.

## The agents' OS user is the operator's choice

**Id:** c666ae71-f252-4973-aa28-f13222254713
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 1, relayed 2026-10-22
**Revisit when:** a deployment needs agents isolated from each other by default, or the `agent_user` layout proves too hard to set up for most operators

Both layouts stay supported. With `single`, agents run as the runner's
user, which may be the operator's own account in a terminal. With
`agent_user`, agents run as a separate OS user through sudo. Neither is
required, and the runner advertises which one it uses
(`targets[].isolation`).

**Reason:** running agents as one's own user in a terminal is a
legitimate way to work: it is how a single developer starts, and the
harness's own sandbox and allowlists still apply. A separate user is the
stronger boundary (see the constraint on allowlists in this file) for
operators who want it, at the cost of sudo rules and a second account.
Making it mandatory would block the simple case without making the
shared case safer than an operator would choose anyway.

**Rejected alternative:** `agent_user` as the only layout. It is the
safer default on paper, but it puts sudo configuration in front of a
first run.

## For now the runner offers Claude Code and Codex

**Id:** 62bcf506-caed-470c-a094-9bea4217b440
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 4, relayed 2026-10-22
**Revisit when:** the maintainer decides on opencode and the harnesses without a command allowlist when the runner goes into use

A configuration may name `claude-code`, `codex` and `stub`. `opencode`
is refused as "not offered yet" even though its adapter is built. `pi`,
`hermes`, `kimi`, `cline` and `omp` stay refused because they have no
command allowlist (design §6.3).

**Reason:** the maintainer wants to discuss the rest once the runner is
in use, with real runs behind the discussion. The opencode adapter stays
in the code so that the decision costs a line, not a slice.

**Rejected alternative:** offering every built adapter: opencode's
project-configuration switch and `instructions` path are still
unverified (design §6.1).

## Model access is the operator's to arrange

**Id:** 889e6702-afb6-429c-8e89-b5d7a1561992
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 2, relayed 2026-10-22
**Revisit when:** the hub is asked to hand out or meter model access, or operators want per-agent spend visible in the dashboard

How agents pay for their model is up to the operator: a subscription
login or API keys, one shared by all agents or one per agent. Maity
prescribes nothing. The runner passes on what the operator configured
(the agents' user's own harness login, a harness `env_file`, Codex's
linked `auth.json`), and nothing about it reaches the hub.

**Reason:** the operator already holds the accounts and knows their
terms. A hub-side model credential would make the hub a store of the most
valuable secret in the setup, and it would add a billing concept the
project does not need.

**Rejected alternative:** model keys managed by the hub and handed to
runners per placement: a secret store in the hub, and a second place for
a key to leak from.

## Default session modes: Claude Code attachable, Codex woken by events

**Id:** 46741392-ca22-48e6-9417-d509c67d31a8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 5, relayed 2026-10-22; runner design v2 §6.2
**Revisit when:** a harness's interactive mode stops waking on a background `maity wait`, or a supervised run costs model calls while idle

A placement that names no mode gets the harness's advertised
`default_mode`. In the shipped configuration examples that is
`interactive` for Claude Code locally and over ssh (a tmux session a
human can attach to) and `supervised` for Codex (headless runs woken by
events). The mode can be chosen per start.

**Reason:** Claude Code wakes on a background `maity wait`, so an
attachable session costs nothing while idle and lets a human answer in
the session. Codex has no such wake-up in its interactive UI, and
`codex exec` ends and closes its terminals when its turn ends. The
supervised loop starts it again on the next event.

**Rejected alternative:** one default mode for every harness: it fits
only one of them.

## `stop-all` refuses while the service runs; `gc` never holds an agent's credential

**Id:** ad84669c-8da9-4e2a-8598-342d797d6454
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §7.5 and §10.1; implementation of runner slice R6b, 2026-10-22
**Revisit when:** the runner gains a local control channel the service listens on, or the hub reports revocation to runners directly

`maity runner stop-all` takes the service's lock first and refuses
while `serve` holds it. `maity runner gc --revoked` asks whether a
workspace's credential is revoked by running that clone's own `maity`
(`python -I -m maity api GET /me` with the clone's state directory). It
asks the hub which placements are active and keeps every clone one of
them names. git runs in a clone only when `.git` holds nothing but a
plain clone's top-level entries, each a file or a directory as git
makes it (so no `commondir`, `config.worktree`, submodules or object
alternates, nothing in `info/` but `exclude`, and no symlink anywhere,
since git follows them past every check) and `.git/config`, at most
64 KiB, holds nothing but a plain clone's keys (core basics, origin, branch tracking,
user name and email). git runs with `GIT_DIR` and `GIT_WORK_TREE` pinned
to the clone, without the operator's `GIT_*` environment or git
configuration. Otherwise, and whenever git
fails, the clone is listed as not inspected and is never removed.

**Reason:** a running service compares sessions with the hub's desired
state every five seconds. It would start every agent `stop-all` just
ended, and the operator would see the emergency stop fail. Refusing with
the reason is clearer than racing the service. The runner never holds an
agent's credential (§15.9). Letting the agent-side CLI make the call keeps
that true, and `-I` with a cwd outside the clone keeps the clone's code
out of the process. `gc` is the one place the runner reads an agent's
git state, so it does so with everything git could run switched off.

A first version ran git with `-c` overrides for hooks, fsmonitor and
pagers and called that defused. A review showed filter drivers (through
`.git/info/attributes`) and `gpg.program` (through `log.showSignature`)
still ran the agent's code as the operator. Overrides can only switch off
what they name, and git keeps adding ways to run programs, so the rule
now reads only configuration it knows to be inert. A second review found
the same gap one level up: `.git/commondir` sends git to another
directory's configuration and attributes. Checking `.git/config` alone
was again an enumeration, of the files git reads, so `.git` itself is
now held to a plain clone's entries as well.

**Rejected alternatives:**
- `stop-all` telling the service to stop its agents: there is no control
  channel, and an emergency path should not depend on the process it
  works around.
- Overriding every dangerous git setting with `-c`: an enumeration of
  what git can run, which is how the first version missed two.
- Pinning `GIT_COMMON_DIR` alone instead of checking `.git`'s entries:
  it closes `commondir` but not the next file git learns to read; it is
  kept as a second line, not as the rule.
- Reading the credential in the runner to ask the hub: a second holder
  of every agent's credential.

## A placement for a harness this runner does not run is refused with a reason

**Id:** 5d71ccda-d931-460f-aa82-1438221cf2c9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner code on `main` after the R5 adapters (#123, #125) and the offered-harness decision 62bcf506, read 2026-10-22; the coordinator's re-check of 5ed066bf, 2026-10-22
**See:** runner.md — 62bcf506-caed-470c-a094-9bea4217b440 — as of 2026-10-22
**Revisit when:** the configuration accepts a harness without an adapter in this version, or a contract code for "not in this version" is added to §15.7

A placement whose harness is not in this runner's configuration, opencode
included (the configuration refuses it), is reported as
`failed`/`harness_refused`; a mode or model the configuration does not
list is `harness_refused` with `mode_unsupported` or `model_unsupported`.
Every harness the configuration accepts has an adapter, so the earlier
"logged, not reported" case for a harness without one cannot arise; the
supervisor keeps that check only as a guard. A start that fails in tmux
counts as a quick exit and ends in `exited`, and in `crash_loop` after
the cap, with the cause in the log.

**Reason:** `harness_refused` means "not allowed by the runner's
configuration" (§15.7), and that is now exactly the case. The human sees
the real cause and can pick another runner or tool, instead of a
placement that waits for something this runner will never do.

**Rejected alternative:** keeping such a placement pending without a
report, as while the adapters were missing: it would wait forever on a
runner that refuses the harness by configuration.

## Sandboxed agents: git redirects are pinned, other clones and secrets unreadable

**Id:** ea36c196-f8e6-43ae-bc47-49c8d5379a65
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's post-merge re-verification of #125 and #147 (both holes reproduced) and approval of the plan, 2026-10-22; the independent review of #184 (the submodule route, opencode's pattern-keyed search permissions), 2026-10-22; verified on the runner VM with codex-cli 0.156.1 and git 2.47.3 (`codex sandbox`, no model run); Claude Code 2.1.308's settings strings for `allowRead`
**See:** runner.md — c2acd907-0f26-4850-8272-063390f1d6a7 — as of 2026-10-22
**Revisit when:** Claude Code's `allowRead` precedence over a more specific `denyRead` is verified, a harness runs git in the clone with an environment the runner does not set, or git learns another file in `.git` that redirects where it reads configuration

Every agent session gets `GIT_COMMON_DIR=<clone>/.git` in the
environment the runner gives the harness, and through `GIT_CONFIG_COUNT`
`core.fsmonitor=false` and `diff.ignoreSubmodules=all`. Git then ignores
a `.git/commondir` the agent wrote from inside its sandbox, and does not
run a program from a nested repository the agent registered as a
submodule (whose configuration the pin does not reach). That covers the
harness's own git calls, which run outside the sandbox, and any other git
started from the session. `maity`'s own git carries the same settings on
its command line whatever its environment, because for Claude Code
`maity` runs outside the sandbox. Codex's profile reads nothing under
the workspaces root but its own clone, nothing in the runner's state and
configuration, and none of a list of logins and keys in the agents'
home. Claude Code's sandbox gets the same read denies except the
workspaces root, plus the credential of every other clone that exists
when the agent starts. A clone made later stays readable to it until its
next start. Both keep the clone's own credential readable, because the
agent's `maity` needs it. The forge login stays readable, because pushing
needs it. opencode's `grep` and `glob` are off: opencode checks them
against the pattern typed, not the path searched. maity and the runner
run git only through `proc.GIT`, a clone into a missing directory, and
`gc`'s pinned read; a test pins that.

**Reason:** git creates lock files, `ORIG_HEAD` and `COMMIT_EDITMSG` in
`.git`, so the directory has to stay writable, and an agent that can
write there can write `commondir`. Read-only `config` and `hooks` meant
nothing once git read them from elsewhere. The variable is part of the
harness process's environment, which a sandboxed command cannot change.
An agent that unsets it for its own git runs the planted program as
itself, inside its own sandbox, which it could do anyway. Without read
denies, one agent read another's credential (another identity on the
hub), the operator's ssh keys and the model login, and could send them
to an allowed host. For Claude Code the workspaces root is left
readable: re-opening the clone inside it with `allowRead` may re-open
the clone's credential as well, and that order could not be checked
without a model run. Denying each other clone's credential by name at
the start avoids the question, at the cost of clones made later. The
home list is a list: the README says that any other secret in the
agents' home stays readable.

**Rejected alternatives:**
- A read-only `.git` with write access to `objects`, `refs` and the
  index only: git creates its lock files and `ORIG_HEAD` in `.git`
  itself, so commits fail.
- Denying writes to each redirecting file (`commondir`,
  `config.worktree`, `info/attributes`): files that do not exist yet
  cannot be bound read-only reliably, and it is the enumeration the gc
  fix already moved away from.
- Hiding the whole home from Codex: the agent's `maity`, `git` and
  toolchains are often installed there.
- `--ignore-submodules=all` on `maity`'s own `git status`: it also hides
  a newly staged submodule, so `report` would miss a change. The
  configuration setting keeps git out of the submodule and still shows
  the staged gitlink.

## In the `agent_user` layout everything on the agents' side belongs to the agents' user

**Id:** 3edc329a-6a10-427d-a0a3-733127f14b20
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §7.6; the coordinator's choice to do the `agent_user` layout before ssh, 2026-10-22; implementation of runner slice R7a, 2026-10-22; not yet run with a real second user
**See:** runner.md — 2bdc5809-b08b-4fa2-97bc-004d37c4cddb — as of 2026-10-22
**Revisit when:** agents need separation from each other, not only from the runner (one OS user per agent), or a live run shows a harness writing where the agents' user cannot

With `layout = "agent_user"`, every command for the agents runs as
`sudo -n -u <agent_user> --`, with only the environment it needs passed
explicitly. That covers the tmux server and its sessions, the clone, the
join, the supervised loop, `gc`'s git and its revocation check, and stopping
a process group. Everything the agents' side needs (tmux socket and
configuration, logs, the harness settings and Codex's home) lives under
`~<agent_user>/.maity-runner/` and is written as that user. The runner's
state directory, its credential and its records stay the runner user's
alone. Commands for the agents never get the runner's terminal (stdin is
`/dev/null`), and the clone runs without any login prompt. Harness
probes and `check` run as the agents' user, who is the one that must be
able to start them. Nothing secret may travel as an argument in this
layout: sudo logs every command line, and `/proc` shows it, so a
harness `env_file` (R5) has to reach the session another way than
`env K=V` or `tmux -e`. The sandbox read denies are worked out from this
side too: the agents' user's home secrets, its `~/.maity-runner` (every
agent's socket, log and settings, which the single layout keeps in the
hidden state directory) and the other clones' credentials, listed as
that user because the runner cannot list a 0700 directory it does not
own; a listing that is not complete refuses the start
(`harness_refused`) rather than leave a credential readable. Binaries and
sandbox tools are looked up, and Codex's sandbox tried, as that user on
the agents' PATH as well.

**Reason:** the layout exists so that agents, and any repository code
they run, cannot read the runner's credential or state. That only holds
if nothing the agents need has to be inside the runner's 0700 state
directory. Harness settings written as the agents' user can be changed
by that user, but under this layout the OS user is the boundary. A
setting an agent widens only reaches what that same user could already
do with a shell. Agents under one `agent_user` still see each other's
files and credentials; separating them needs one user per agent (ssh
`own_user`, or pods).

**Rejected alternatives:**
- Harness settings owned by the runner and readable by the agents: they
  would need a runner-owned directory the agents can traverse, and
  Claude Code still loads the agents' user's own settings, which that
  user can write.
- Running tmux as the runner with `server-access` for the agents' user:
  tmux 3.3 and later only, and the sessions' processes would still be
  the runner's.

## On the ssh backend each host is a target that runs its own `maity`

**Id:** 256e800f-3ddc-482e-b4ac-e6b09d69fe72
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.4; implementation of runner slice R7b, 2026-10-22; tested against a fake `ssh`, not yet against a real host
**Revisit when:** a live run on a real host shows a step that does not work over ssh, or `gc` and `workspace claim` are extended to ssh hosts

The supervisor works on targets: `local`, or one per configured ssh host.
Each target has its own command runner, workspaces root, tmux server,
agent limit and harness probes. Every command for a host is a fixed
template sent as one command line with every word quoted, over a shared
connection with strict host keys and no forwarding. The agents' files
(tmux socket, logs, harness settings) live in the remote user's
`~/.maity-runner/`. That home is learned on the first connection. What the
agents run, the supervised loop and the `stub` included, starts through
the host's own `maity`, on internal subcommands (`maity runner loop`,
`maity runner stub`). The join runs the host's `maity` too, so the
agent's credential is written on the host and never passes through the
runner. Workspace records are keyed `<host>:<path>`. `gc` and
`workspace claim` stay local-only in this slice.

**Reason:** the runner's interpreter path means nothing on another
machine, and the operator's install there (pipx, a virtual environment)
is reached reliably only through its `maity` on the configured
`agent_path`. Keying records by host keeps the same path on two hosts
from being one workspace. `gc` reads an agent's git state with a layout
check written against local files; doing that over ssh needs the same
care again, so it waits rather than being half done.

**Rejected alternatives:**
- `python3 -I -m maity.runner.loop` on the host: the system `python3`
  usually does not have the operator's `maity` installed.
- Copying the runner's interpreter path to the host: different machines
  rarely share it.
