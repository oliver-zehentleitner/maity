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
make them supersede each other forever. The agents run in a tmux server
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
