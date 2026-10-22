# Runner

## The configuration refuses unknown keys and documents every default; tomllib only from 3.11

**Id:** f2a34d72-f074-474c-87bb-2d8c6bccd60e
**Type:** decision
**Status:** active
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
**Status:** active
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
**Status:** active
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
