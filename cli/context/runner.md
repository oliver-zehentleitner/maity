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
**Status:** active
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
**Revisit when:** the join from the runner (R4) and the harness adapters (R5) are in; then this case no longer exists

While only the `stub` adapter exists and the runner cannot pick up a
join, a placement that needs either is left as it is. It gets no
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
