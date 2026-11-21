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
**Source:** runner design v2 §5.2, §8 and §10.1; implementation of runner slice R2, 2026-10-22 (which answers count as fatal, the superseded stream, `KillMode`); card tsk-vyp87d3hnbem (the lead's security review of 2026-11-13: a full disk must not stop the runner service for good), 2026-11-14
**Revisit when:** the hub gains a reason to answer a runner 4xx that a later retry could clear, or the runner runs more than one service per credential by design, or the service gets a way to tell a state directory that is gone from one that is full

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
seconds; that is decided at the start (the lock file in the state
directory). Once serving, a status that cannot be written (a full disk)
backs off and says `hello` again like a hub outage: an exit with 78 there
would leave the agents running unsupervised until someone started the
service by hand, and the disk may have room again a minute later. The agents run in a tmux server
the runner started, inside the unit's cgroup, so systemd's default
`KillMode=control-group` would end every agent on a service restart. The
design keeps agents running across runner restarts and hub outages, so
only the runner's own process may be signalled.

**Rejected alternatives:**
- Retrying every error with backoff: hides a revoked credential or a
  wrong configuration behind an endless reconnect.
- Backing off on `superseded` and reconnecting: two services would take
  the stream from each other in turn.
- Ending with 78 on any local write that fails while serving, as before
  2026-11-14: a full disk then stopped the service for good while its
  agents ran on without stops, kills or status.
- Ending with another exit code there, for systemd to restart: the
  restart lands in the same full disk, and an in-process backoff keeps
  the supervisor and its agents' state in memory.
- Leaving `KillMode` at its default: a `systemctl restart` for an
  upgrade would end every agent mid-work.
- `PrivateTmp` in the unit: with the agents outliving the service, the
  next start would replace their `/tmp` under them.
- A `TMPDIR` under `/var/lib/maity-runner` instead of `/tmp` in
  `ReadWritePaths`: tools that hardcode `/tmp` would fail, and in the
  `agent_user` layout the agents' user cannot write there.

## The runner's advertised `running` count survives a reconnect

**Id:** d0270526-fca9-4a6c-8e5e-50eea8f2feac
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-yfc9n6kmvs52; round-2 review tqgb A1256; the reconnect-count reproduction tests in `cli/tests/test_supervisor.py`
**See:** runner.md#serve-ends-with-78-on-anything-retrying-cannot-fix-and-never-takes-the-agents-with-it — e210a162-44c7-4efd-9176-c3c3f66b3e63 — as of 2026-11-18
**Revisit when:** the capabilities shape, the advertise throttle, or how `serve` and the supervisor share the capabilities dict changes

`maity runners` shows a runner's `running`/`max_agents` straight from the
capabilities the runner advertised; the hub stores and returns that number
unchanged. The count is kept correct across a reconnect, together:

- The supervisor writes each advertised total (and the per-target counts) back
  into the shared capabilities dict, so serve's next `hello` carries the last
  counted total, not the `running: 0` the dict was first built with.
- `serve`'s `hello` reads that dict through the supervisor under the
  supervisor's lock (`advertised_capabilities`), and after each `hello` marks an
  invalidation — it bumps a generation counter — so the next tick re-PATCHes
  whatever the count then is, even 0, an empty counts dict, or a count unchanged
  since the last PATCH.
- What keeps a reconnect pending until a live send answers it is the generation
  a PATCH commits: it records the generation captured at send-start, which for a
  PATCH already in flight when the reconnect arrived is older than the reconnect,
  so `dirty` stays true. A forced *cached* send (`advertise_now`, a reachability
  change: `running is None`) refreshes the throttle but does not advance the
  generation at all, so it cannot consume a pending reconnect either.
- A successful PATCH commits only when no invalidation arrived while it was in
  flight. This guard does not keep the invalidation alive (the captured
  generation does); it keeps a stale, in-flight PATCH's counts out of
  `advertised_counts` / `advertised_running` / the capabilities write-back, so a
  PATCH that started before the reconnect never overwrites the live state.
- `capabilities.build` starts every target's `running` at 0, the honest value
  before anything is counted; the supervisor refreshes them.

Only the `running` fields of the capabilities dict are coordinated by the lock;
the keeper writes the harness/tools parts of the same dict on its own, outside
this lock.

**Reason:** the capabilities dict is shared between serve's connection thread
(`hello`) and the supervisor's tick thread (`_advertise`). Without the
write-back a reconnect re-asserted the build-time `0`, and the advertise
throttle (one `PATCH /runner` per changed count, at most every 60 s) then
suppressed the correction while the count stayed steady — so the hub read `0/N`
while the placements ran on. The invalidation is a generation rather than an
emptied cache, because an empty cache reads as "nothing to send" (a 0 count
never leaves) and an in-flight PATCH would overwrite it. This was a latent gap
the capabilities shape had from the start; reconnects during a routine CLI
upgrade exposed it, so it is a design gap, not a regression a single change
introduced.

**Rejected alternative:** have `hello` read only the scalar `advertised_running`
int (atomic under the GIL) instead of locking the dict. Rejected because
`hello` sends the whole capabilities object — backend, targets, per-target
running, harnesses — so a coherent snapshot of the dict is needed regardless;
one lock over the running fields covers the top-level and per-target counts in
one place.

**Rejected alternative:** represent the invalidation by emptying the advertise
cache (`advertised_counts = {}`). Rejected because `_advertise` drops zero
entries, so an empty cache equals the empty counts of a runner with nothing
running — it reads as "already sent", and a count that fell to 0 never reaches
the hub — and an in-flight PATCH's commit overwrites the empty cache and
swallows the invalidation.

**Rejected alternative:** force an immediate re-advertise (`advertise_now`) from
the reconnect instead of marking it for the next tick. Rejected because the
authoritative count is the next tick's live session snapshot, not the cached
one; marking the generation lets that tick send the true total and avoids
re-asserting a possibly one-tick-stale cached count at the reconnect moment.

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

## On macOS Claude Code's sandbox is Seatbelt; the service stays systemd's

**Id:** 4d122813-2f28-4a7b-807e-44aaaf0c835b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-rrx15szr50c6 (the owner's request of 2026-11-11 for a first runner test on a Mac the next morning; its plan note); Claude Code's sandboxing documentation (code.claude.com/docs/en/sandboxing), read 2026-11-11: macOS uses the built-in Seatbelt, nothing to install, `failIfUnavailable` exits instead of running unsandboxed; `cli/src/maity/runner/capabilities.py`, `commands.py`; the first review of #1679 (the Keychain reachable from the sandbox runtime's Seatbelt profile, read in its source, and the exact-case alternates guard, reproduced on Linux), 2026-11-11. Not run on a Mac when written.
**See:** runner.md — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-11
**See:** runner.md — 84732ea1-d314-465d-939c-fd274b2f8b0d — as of 2026-11-11
**Revisit when:** the first run on a Mac shows git, the forge login or the read denies failing inside Seatbelt, or shows whether a sandboxed command reads a Keychain login or a denied path in another case; Claude Code gets a setting that keeps sandboxed commands from the Keychain; a launchd service is wanted; Codex's sandbox or an ssh host is tried on macOS

On macOS the runner switches Claude Code's sandbox on where
`sandbox-exec` is on the agents' `PATH`, with the settings it gives
bubblewrap on Linux. `maity runner check` names the sandbox's state for
Claude Code on every platform the runner runs on (Linux, macOS and other
POSIX systems; on Windows `maity runner` is refused before any check):
`ok` with the tools it found, otherwise a warning that agents run
unsandboxed, an error with `require_sandbox`. On a platform with no
Claude Code sandbox it says so instead of nothing.
`install`, `uninstall` and `unit` stay systemd's; on macOS the operator
runs `maity runner serve` in a terminal. The ssh backend's probe of a
host still looks for bubblewrap and socat, so a Mac host reads
`sandbox: off`.

Known gap: the Keychain. On Linux the read denies hide Claude Code's
login, a file under `~/.claude`. On macOS Claude Code keeps it in the
Keychain, and `gh` does by default; `HOME_SECRETS` lists files, and the
sandbox runtime's Seatbelt profile allows the Keychain's services
(`com.apple.SecurityServer`, `com.apple.securityd.xpc`). Code an agent
runs may therefore read those logins. No Claude Code setting to close
that was found, so the docs name the gap and what an operator does
about it: a macOS account of its own for the runner, whose login
keychain holds only the logins meant for the agents. Not tried on a Mac.

Case: APFS ignores case by default, so a guard that compares a path by
exact string can be passed with another spelling. maity's clone check
refuses unknown `.git` entries by allowlist, and its one denylist (the
alternates files) now compares in lower case on every platform, since a
real clone never holds two spellings. Claude Code's and Seatbelt's deny
rules are exact-case strings; how they match on APFS is not documented
and not tried.

**Reason:** the sandbox ships with macOS, so its presence is the
analogue of bubblewrap and socat on the `PATH`. `failIfUnavailable`
already turns a Seatbelt that cannot start into a refused start, never a
silent unsandboxed one. Before this, macOS agents ran unsandboxed and
`check` said nothing about it; only the `sandbox_unavailable` detail
showed it. A service needs a launchd agent that nobody could run on a
Mac before the test, and the foreground `serve` is enough for it, since
agents outlive it.

**Rejected alternatives:**
- Keeping macOS unsandboxed until a Mac run: the test would then have
  run agents with the operator's rights and taught nothing about the
  sandbox. Installing from main remains that state, reported.
- Trying Seatbelt once (`sandbox-exec -p … true`) instead of finding the
  binary: Claude Code's own start-up check and `failIfUnavailable` do
  that per start, and the probe could not be tried here without a Mac.
- A launchd agent in the same change: untested by the morning, and a
  service file that does not work reads as support.

## The allowlist harnesses allow one OS UUID v4 source: the kernel's generator

**Id:** 0a639f39-f76c-4a77-ac43-ae8ce1d42434
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-bj6fs628q6pd (a placed runner agent's field report that the sandbox refuses every OS UUID v4 source); the Keep the Why skill 0.20.3 (`SKILL.md`, the `Id` rule) and `AGENTS.md` (every entry's Id is made by an OS command, never from memory)
**Verification:** contradicted — the allowlist mechanism still reads from `adapters.py` and `docs/runners.md` as described, but the inferred live-session efficacy is contradicted: observed in a Claude Code runner placement (CLI 0.1.0a17), 2026-11-20, a plain `cat /proc/sys/kernel/random/uuid` and `uuidgen` were both refused by the harness (denied, "don't ask" mode); card tsk-1rejhywcw3qh reports the `/proc` read refused for three further placed sessions the same day
**See:** runner.md — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-15
**See:** commands.md#maity-uuid-makes-keep-the-why-ids-where-uuidgen-is-refused — 2b2be9a9-25d6-4396-b35d-5a2c242a4997 — as of 2026-11-20
**Revisit when:** `/proc/sys/kernel/random/uuid` stops being a usable OS UUID v4 source, the skill drops the OS-command Id rule, or a harness changes how its command allowlist matches an exact command

The runner allows exactly one command for making a UUID v4,
`cat /proc/sys/kernel/random/uuid`, for the harnesses that gate
commands with a deny-by-default allowlist: Claude Code (a `Bash(...)`
rule in `permissions.allow`, with `defaultMode: dontAsk`) and opencode
(a `bash` rule, the catch-all being `deny`). It is the one source
(`adapters.UUID_COMMAND`); the rule is unconditional, not from a grant.
The allowlist mechanism and that these two harnesses refuse unlisted
commands are **confirmed** from the code and `docs/runners.md`; that a
live Claude Code or opencode session now makes its UUID with the
allowed command, and that Codex and agy run it inside their own
sandbox, is **inferred** and not yet observed in a placed session —
the weaker grade is why this entry's Evidence is `inferred`.

**Reason:** every Keep the Why entry an agent writes needs an `Id` made
by an OS command — never composed from memory — so a session that
cannot run one records no reasoning at all. Under the allowlist the
skill's named sources are all refused: `uuidgen`, `node`, and `od` on
`/dev/urandom` are unlisted commands, denied before they run. The
skill names `uuidgen` first and `cat /proc/sys/kernel/random/uuid`
second; the kernel path was chosen — not because the skill prefers it —
because it needs no package installed (`uuidgen` ships in util-linux,
which a minimal host may lack) and reads a fresh lowercase v4 directly,
so no `tr 'A-F' 'a-f'` step is needed (the skill lowercases macOS's
`uuidgen`). A single exact command is a tighter allow than a program
with free arguments.

**Rejected alternatives:**
- Allowing `uuidgen` instead: an acceptable fallback, but it depends on
  util-linux being installed for the agents' user, which the sandbox
  cannot add (it reaches only the hub, the forge and the grant's
  hosts), and its output needs lowercasing on macOS.
- Allowing the Read tool to read the file (`Read(//proc/...)`) rather
  than a Bash command: the file reports size 0 and yields its bytes
  only on read, which the Read tool is not built to handle; a plain
  command is what the skill tells the agent to run.
- A read-allow in Claude Code's OS `filesystem` sandbox: the block is
  the command allowlist, not the OS sandbox (reads outside the denied
  paths are already allowed), so widening the filesystem would not let
  the command run; the allowlist is where it is gated (see 3c074f5a).
- Codex and agy need no entry: neither has a per-command allowlist, so
  an unlisted `cat /proc/sys/kernel/random/uuid` already runs inside
  their own sandbox (Codex's `:workspace` profile, agy's
  `proceed-in-sandbox`).

## The command allowlists are not a boundary until agents run as their own user

**Id:** 2bdc5809-b08b-4fa2-97bc-004d37c4cddb
**Type:** constraint
**Status:** superseded
**Superseded by:** b2cbf1a7-e25c-4803-8bc4-845c488512fc
**Evidence:** confirmed
**Source:** runner design v2 §6.1 ("`Bash(git *)` is not a boundary"); the coordinator's review of runner slice R5a, 2026-10-22 (a git read printed the clone's credential)
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
git can read any file. A wildcard grant therefore meant "may
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

## Codex's CODEX_HOME lives inside the placement scratch, not the runner's state directory

**Id:** 9084b0ed-985d-41ea-906d-cd9cc6e18879
**Type:** decision
**Status:** active
**Evidence:** inferred
**Verification:** corroborated — the placement, launch-write and sandbox-profile boundaries are read from `adapters.py`, `scratchop.py` and `commands.py` and covered by unit tests (`tests/test_adapters.py`, `tests/test_scratchop.py`, the launch-write op through the `maity runner scratchop` CLI in `tests/test_commands.py`, and the too-old-host refusal in `tests/test_supervisor.py`); a live Codex placement running with the read-only home is not yet observed and is still needed
**Source:** card tsk-hv7jbgy75zjt (a Codex placement's field report that its own sandbox denied the helper it must run, `permission_denied`, so no command ran); the review of the launch-write and sandbox-profile boundaries; the traced cause in `cli/src/maity/runner/adapters.py`; the reporting of the too-old-host refusal settled in the review of PR #1979
**See:** runner.md — 49caa654-c3ad-44c0-bdfd-3274aa2ddfa7 — as of 2026-11-18
**See:** runner.md — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-18
**Revisit when:** a harness other than Codex needs a per-placement home, Codex stops keeping its per-command helper and session state under `CODEX_HOME`, a placement is given a home with no scratch to carry it, or the follow-up card adds a contract detail-code for the too-old-host refusal

Each Codex placement's `CODEX_HOME` lies inside that placement's scratch
(`adapters.codex_home`), under the workspaces root, rather than under the
runner's state directory. The runner still writes `config.toml` there and
links the operator's `~/.codex/auth.json` into it, not copied (carried from
49caa654). The codex sandbox re-opens the placement's scratch, so the home
inside it is reachable; every other placement hides the whole workspaces
root, so this home — its login link and its session state — is hidden from
them, exactly as the scratch is. Where there is no scratch to carry it (no
workspaces root to carve), the home stays in the runner's directory, where
the sandbox hides it. `maity runner check` verifies from the local
configuration the parts it can see before a placement starts — that Codex is
given a scratch and that the workspaces root is not inside the state
directory — but it does not confirm that the scratch is created when a
placement actually runs, nor read an ssh target's own paths, so a runtime
fall-back to no scratch is beyond what it catches.

Because the home sits in the agent-writable scratch, two boundaries are
drawn explicitly. The sandboxed commands may read the home — its control
files and the per-command helper they run — but may write nothing in it
(`read`, not `write`): the runner writes those control files once before the
session starts, and a session cannot rewrite the configuration a later
restart reads. And the runner's own writes of those files go only to a
descriptor opened without following a link from the workspaces root, the
same anchor the scratch's make and removal use, so a `codex-home` swapped
for a link is refused rather than followed out of the scratch.

The runner writes those control files itself, so on an ssh host it runs the
host's own `maity` to do it, the same way it makes and removes the scratch
there — the launch-write op is reached through the `maity runner scratchop`
CLI, not only the runner's internal module path. A host whose `maity`
predates that op cannot anchor the home; the placement is then refused with
a clear reason (the host's `maity` is too old for Codex placements) so the
operator upgrades the host, rather than crash-looping the start or quietly
falling back to the hidden state directory where no command would run.

That refusal is reported as `harness_refused` with no detail, and the
specific reason — the host's `maity` is too old for the codex launch-write
op — goes to the runner's log only. `harness_refused`'s detail is a closed
contract list (docs/api.md §15.7) with no code for this host-too-old case;
an unknown detail makes the hub answer `invalid`, so the runner would
re-send the rejected report every tick and the refusal would never be
recorded. A contract detail-code for it is deferred to a follow-up card.
`retry_at` stays unset, so the start still does not crash-loop and only a
new generation retries.

**Reason:** the codex sandbox hides the runner's state directory, and it
hides a directory by mounting over it, so a path inside it (the old
`CODEX_HOME`) has nowhere to be reached and Codex cannot create or run its
per-command helper (`CODEX_HOME/tmp/arg0-linux`): every command failed and
`maity resume` never started (the incident on this card). The placement's
scratch already solves the same problem for a different directory — it sits
under the hidden workspaces root and is re-opened for this placement while
staying hidden from the others — so the home follows that precedent and
inherits it. Under the workspaces root the home is reachable like the
scratch and holds nothing of the runner's state or another placement's; its
control files are written by the runner and read-only to the session, and
the runner writes them without following a link, so the home adds no
writable surface and no write that leaves the scratch.

**Rejected alternatives:**
- Re-open a home in place under the state directory. A subpath can be
  re-opened under a hidden root — the clone and the scratch are, under the
  workspaces root the profile keeps `none` while it names them back. The
  state directory is different not because the re-open cannot be written but
  because it holds the runner's secrets — the credential, the records, every
  other placement's — and is kept wholly hidden: a readable hole into the
  secret store for one home weighs worse than a home in the agent-facing
  scratch, which holds no secret. So the home goes to the scratch.
- A sibling per-placement directory under the workspaces root beside
  `.scratch` (the card's wording). It would need its own secure
  make-and-remove path run as the agents' user, and its own re-open rule in
  the profile — each a new place the boundary could be gotten wrong — and it
  would be left behind on every closed placement unless a second cleanup
  matched the scratch's. Inside the scratch the home inherits the scratch's
  already-reviewed re-open and its removal; its own launch writes are
  anchored to the scratch root and its control files are read-only to the
  session (above), so the surface it adds is the one named here, not a new
  unreviewed boundary. The cost: a placement without a scratch (a host whose
  `maity` cannot carve
  one) gets no re-opened home and falls back to the runner's directory,
  where the sandbox hides it; `check` verifies the configuration before a
  placement starts (Codex is given a scratch, the workspaces root is outside
  the state directory), but a runtime fall-back to no scratch is beyond it.
- Keep Codex's home in the clone or its `.git`: the work tree is the agent's
  to commit, and `.git/maity` is the denied credential directory; a home in
  either would be committed by accident or refused by the sandbox.
- Fall back to no scratch when the host's `maity` is too old for the
  launch-write op. That would put `CODEX_HOME` back under the hidden state
  directory — the very incident on this card, where no command runs —
  functionally broken while looking like a clean start. A placement that
  cannot be anchored is refused with a reason the operator can act on
  (upgrade the host) instead, so the breakage is named, not hidden.

## agy's scratch lives under the host's shared temp directory, not beside the clone

**Id:** 8ec06e26-42b6-47b7-9f23-2bad37da3dfa
**Type:** decision
**Status:** active
**Evidence:** inferred
**Verification:** corroborated — the make/read/remove discipline, the owner, mode and no-follow checks, the per-user parent owned 0700, the hiding of that parent from the sandboxed Codex and Claude Code placements, the end-to-end `--review-file` read through a production-made scratch, and the clean removal of a scratch holding read-only or unsearchable directories are covered by unit tests (`tests/test_scratchop.py`, the supervisor lifecycle in `tests/test_supervisor.py`, and the review-file read through the recorded scratch in `tests/test_placed_reads.py`); a live agy placement posting a `review_result` with the scratch is not yet observed and is still needed
**Source:** card tsk-bbhcekjk2mgm and the dispatcher's approved design; the finding that agy's sandbox makes the workspace and the beside-clone `.scratch` read-only while the host's shared temp directory is writable from inside the sandbox, confirmed by a reviewer's live probe; the ownership question resolved by the dispatcher
**See:** runner.md — 9084b0ed-985d-41ea-906d-cd9cc6e18879 — as of 2026-11-19
**Revisit when:** agy's sandbox gains a writable beside-clone location, a harness other than agy needs a scratch its sandbox cannot write beside the clone, or the per-user temp parent is given a cleanup for stale placements

An antigravity placement gets a scratch like Claude Code and Codex, so an
agy reviewer can write its `review_result` file, but not beside the clone:
agy's sandbox makes the workspace — and the beside-clone `.scratch` — read
only, so a scratch there could not be written. It goes under the host's
shared temporary directory instead, in a per-user parent
(`maity-scratch-<uid>`) with the per-placement directory inside it. The
runner records that path — the parent is resolved first, so a shared temp
directory that is itself a link does not break the session's own read — and
the session reaches it as `MAITY_SCRATCH`, with `TMPDIR` inside it, exactly as
for the beside-clone scratch; `maity`'s read of `--review-file` finds it
through the recorded-scratch path it already had (an absolute path outside the
clone, no link on the way), so that read needs no change.

The scratch is owned by, and reachable only to, the user agy runs as — the
runner's own user in the `single` layout, the agents' user in `agent_user` —
because a shared temp directory is writable by every user on the host and the
sandbox runs as that user. It is created the same way the scratch and the
Codex launch-writes are, as that user (`AsUser`), so the directory the runner
makes is owned by the user that must write it. The anti-hijack checks verify
ownership against that same user's id: the per-user parent and the
per-placement directory are each opened without following a link and must be
a directory owned by that id; the per-placement directory is private and made
fresh at every start (an earlier one removed first, a new one then created,
refusing one that is already there), so nothing carries across a restart and a
directory planted by anyone else is refused rather than used or written
through. The per-user parent is owned 0700 by that user and the per-placement
directory is given a random name the runner chooses (not the placement id),
recorded with the placement so the session and the runner find the same one
again; the random name keeps a user's own placements from colliding and is not
a secret. The runner creates the per-user parent before a placement whose
sandbox hides it (Claude Code or Codex) starts, so the deny path that
placement's sandbox is given is a real directory rather than a missing path a
placeholder would stand in for; a placement that hides nothing is given no
parent and has none made for it. Removing a scratch restores the owner's access on each directory first,
so one holding a read-only or unsearchable directory a build tool left (a
module cache, say) is still deleted and does not pile up. `repo/` stays
read-only and the plain-call stdin rule for `maity` is unchanged. On an ssh
host, whose remote user's id the runner does not hold, the scratch is not made
and the placement runs without one.

The residual risk is accepted knowingly. The scratch is separated against
other host users — the per-user parent and the leaf are owned 0700 by the user
agy runs as, so another host user cannot enter them — and against the
sandboxed Codex and Claude Code placements of that same user, whose sandbox is
told to hide the per-user parent so they cannot reach a scratch under it. It is
NOT separated against another agy placement, nor against an unsandboxed
placement, of the same host user: a shared temp directory is, by the agy
sandbox's own premise, writable by that user, and nothing here keeps one such
placement out of another's scratch. The 0700 mode gives only ordinary own-user
file permissions and the random leaf name only avoids collisions between a
user's placements; neither is relied on to separate one same-user placement
from another. This same-user exposure is accepted until each placement runs as
its own user (per-placement `agent_user` separation, the owner's pending
`req-ynkndnybr9z3`). The runner's reach into the parent also rests on the
shared temp directory's sticky and setgid bits (the root is opened without a
no-follow guard, as its being outside any per-placement control allows): a
host that does not set those bits on its shared temp directory weakens that
assumption, which is why the location is the conventional sticky shared temp
directory and not an arbitrary one.

**Reason:** the recorded-scratch machinery already draws the boundary this
needs — a placement-owned writable directory the runner records, that
`maity` reads a named file in through descriptors without following a link,
removed when the placement ends — and reusing it means `--review-file` needs
no new code path and the agy scratch inherits the same, already-reviewed
read, lifecycle and `MAITY_SCRATCH`/`TMPDIR` export. The host's shared temp
directory is chosen because it is the one location the runner controls that
is writable from inside agy's sandbox: the sandbox exposes it as writable
while keeping the workspace and the beside-clone scratch read-only, so a
directory the runner creates there is visible and writable to the agy
session. The ownership rule follows from the two layouts both having to hold:
in `single` agy runs as the runner's user, so a 0700 directory owned by that
user is both safe and writable; in `agent_user` agy runs as a separate user,
so the directory must be owned by *that* user to be writable, and the check
must verify ownership against the user the runner created it as, not blindly
the runner's. Creating it through `AsUser` makes the two layouts one code
path, and the owner check reads back the id it was created as.

**Rejected alternatives:**
- Give agy the beside-clone `.scratch` like Claude Code and Codex. Its
  sandbox makes that location read-only, so the session could not write the
  scratch at all — the reason agy had none before.
- Teach `--review-file` a runner-named, placement-owned writable path of its
  own, without the full scratch machinery. It would need its own make,
  record, read-with-no-follow and removal rules — each a new place the
  boundary could be gotten wrong — to end at the same contract the recorded
  scratch already provides, and it would give the session no `MAITY_SCRATCH`
  or `TMPDIR` for a review's other leftovers. Reusing the scratch gives one
  reviewed boundary and one lifecycle instead of a second, narrower one.

## Codex reaches the operator's login through a link in its per-placement home

**Id:** 49caa654-c3ad-44c0-bdfd-3274aa2ddfa7
**Type:** decision
**Status:** superseded
**Superseded by:** 9084b0ed-985d-41ea-906d-cd9cc6e18879
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
**Status:** superseded
**Superseded by:** 79837674-493a-43dd-8670-e8b163309bca
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

## Codex starts without the grant parts it cannot enforce

**Id:** 79837674-493a-43dd-8670-e8b163309bca
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer, 2026-11-17 (req-0t1qj70vh3st): one ChatGPT reviewer on each runner, refused on a runner whose repositories grant commands and pull requests to the Claude Code coders; the lead's approval of the plan on card tsk-fgnag2jvv4fx, 2026-11-17
**Revisit when:** Codex gains a per-command allowlist the runner can write, or a way for one command to leave its sandbox, so that `maity gh` could run outside it

With its sandbox on, a Codex placement starts on a repository whose
grant has an `allow` list or `pull_requests`. It does not get those two
parts (`adapters.codex_left_out`): the `allow` list is not applied, so
every command runs in Codex's sandbox, listed or not, and the runner
writes no pull-request grant for it (an empty record, no word of `maity
gh` in its prompt), as without the grant; it does not enforce that a
Codex agent opens no pull request. With its sandbox off (`require_sandbox` unset, so the start is not
refused for the sandbox alone), such a grant refuses the start
(`harness_refused`), as every such grant did before.
`maity runner check` warns about each part for every such repository
when `[harness.codex]` is configured, and the runner logs them at each
Codex start. Codex is still advertised with `confinement: "sandbox"`,
and its network list (`network`) still applies inside the sandbox.

**Reason:** the grant is per repository, so its Claude Code parts kept
every Codex placement off that repository. Starting it with its sandbox
on widens nothing: with an empty `allow` list Codex already runs every
command in its sandbox. Without the sandbox nothing would take the
list's place, so the refusal stays for that case. What the refusal also
guarded against was a list that looks honoured while it is ignored, and
naming the left-out parts in `check` and in the log keeps that visible.
`maity gh` is built to run outside a harness's sandbox, as every
`maity` call does for Claude Code; Codex's `maity` runs inside it, so
Codex gets no pull-request record.

**Rejected alternatives:**
- Keep refusing (c2acd907): one harness's grant blocked another harness
  on the same repository.
- A grant section per harness (`[repositories."…".harness.codex]`): a
  larger shape than needed once nothing a harness cannot enforce blocks
  its start.
- `maity gh` for Codex inside its sandbox: what `maity gh` reads to
  open a pull request would then be readable by the repository's code.
- Start a Codex without its sandbox and only say so in the log: nothing
  would stand in for the left-out `allow` list.

## An interactive Codex start answers its folder prompt with "Open restricted", and nothing else

**Id:** fea3c3a3-6250-4791-b0ad-396f05507374
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-57nsjjddzk3s (an interactive Codex 0.169 placement stopped on the prompt on an operator's PC, 2026-11-17); Codex 0.169.0's own source (tui/src/onboarding: the prompt, its choices, and its test that a restricted choice saves no trust); the lead's approval of the plan on the card, 2026-11-17
**Revisit when:** Codex gains a setting or flag that skips the folder prompt for an untrusted folder, or changes the prompt's text or what its restricted choice saves

The runner marks the clone untrusted (c2acd907-0f26-4850-8272-063390f1d6a7),
and Codex 0.169 asks about such a folder at every interactive start
("Folder access"), its first choice "Open restricted" highlighted. Nobody
answers in a placed session, so the agent never started while the
placement reported `running`. For an interactive Codex, the runner
looks at the pane for `FOLDER_PROMPT_WITHIN` after the start; when it
shows "Folder access" and "Open restricted", and nobody is attached, it
presses Enter once and logs it. A folder prompt without that choice
(one offering "Trust and continue") is never answered: the log says the
harness waits on a first-run prompt. The pane's text is only matched
(`Tmux.pane_has`), never kept, logged or sent, as in the idle check.
A session adopted after a runner restart is looked at for a prompt to
answer only on the adopting tick, and only within `FOLDER_PROMPT_WITHIN`
of the start the earlier process made. Before every idle check of a
Codex session the runner looks for the folder prompt: while it shows,
or a look cannot tell, no idle line or key is sent, also for a prompt
that shows only later; once it is gone (a person answered it), the idle
check runs as before. One look decides that check only.

**Reason:** "Open restricted" keeps the folder untrusted and saves
nothing, so the clone's own `.codex` configuration stays out exactly as
before; no setting that skips the prompt for an untrusted folder was
found in Codex 0.169's onboarding code. Answering only that
choice means the runner can never be the one that trusts a folder.

**Rejected alternatives:**
- Mark the clone trusted: Codex would load a committed `.codex/config.toml`
  over the runner's profile (c2acd907-0f26-4850-8272-063390f1d6a7).
- Refuse interactive Codex and offer only supervised: not needed while the
  restricted choice exists; it stays the fallback if a version drops it.
- A placement `detail` for a harness waiting on a prompt: a contract change
  for a case the log already names; the lead chose the log line.

## Antigravity starts in a workspace folder that holds only the clone, in a mode the runner sets

**Id:** b0646ec1-c909-456c-842d-28f2d4facd54
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the owner's go for the adapter, relayed 2026-11-12 (req-1vm61j2rm2ye): a workspace folder per placement with the clone inside, agy started in the folder, no home directory per placement for now; test runs of agy 1.5.7 recorded in the notes of card tsk-e062xzrgfxxc (2026-11-12); docs/api.md §15.3 and §15.5
**Revisit when:** agy gains a switch that keeps a directory's own configuration out, or a settings directory per session without a first-run consent; or the owner wants the agents' agy settings apart from those of the user they run as

An `antigravity` placement runs agy in a folder the runner creates per
placement, with the clone as `repo` inside it and nothing else. The
runner refuses to start when the folder holds anything else. Every
session gets settings the runner writes (`--settings`): the default agent
mode, commands in the sandbox without asking, the sandbox on, the folder
trusted, `.git/maity` denied to the file tools, `maity` and the
repository's grants allowed. agy uses the home of the user the agents run
as, so that user's own agy settings apply to every agent.

**Reason:** agy loads the start directory's hooks, MCP servers, plugins,
skills and rules even for a headless run in an untrusted directory, and
the hooks and MCP servers ran outside its sandbox in the test. None of
its settings switches that off; unknown keys are refused. Started one
level above the clone, it loaded none of the clone's configuration, also
after the agent had worked in the clone. The folder is writable for the
agent, so a run could leave configuration there for the next one: hence
the check at every start, and in `supervised` mode before every run of
the loop too, which starts agy again per event and after a failed run
without the supervisor (the loop runs the same check, through the same
listing, as the agents' user; review of PR #1815). The mode is set because agy 1.5.7 made `auto`
the default, also headless, and in the test its reviewer model let a
command leave the sandbox and list `.git/maity`. The settings are merged
with the user's own, not replacing them; the owner accepted that for
now. Resuming with `-c` is enough, because agy scopes it to the working
directory and the folder is per placement (a headless `-c` continued the
folder's conversation in the test).

The folder must not lie inside a git work tree either: agy then loads
the configuration of every directory up to that tree's root. In a test
(2026-11-12), a folder that was no repository, below a repository with
agy rules and an MCP server, loaded those rules and started the server;
with the ancestor's `.git` moved away it loaded nothing from above. With
the session's git variables set (`GIT_COMMON_DIR` naming the clone's
`.git`), a run in the folder still loaded nothing from the clone. So the
runner refuses a start when any directory above the folder has a `.git`
entry. agy takes the work tree from `$PWD`, not the physical directory:
started through a symbolic link inside a repository, at a folder that
physically lay outside, it loaded the repository's rules, skills and MCP
server; the reverse loaded nothing. So the folder's path must be its
real path, and the walk then covers both. An entry beside the clone also counts as unsaved work before a
removal: git in the clone cannot see it, and a retention expiry must not
delete what the agent left there.

**Rejected alternatives:**
- The clone as the working directory, or added with `--add-dir`: the
  repository's agy configuration loads and runs unsandboxed code.
- A home directory per placement (as `CODEX_HOME` for Codex): it would
  keep the operator's agy settings and conversations away from the
  agents, but an interactive start in a fresh home shows agy's first-run
  terms and data-use consent, and a changed `HOME` reaches the agent's
  git, `gh` and `maity` as well. The owner chose the shared settings.
- Checking the folder for agy's known configuration names only
  (`.agents/`, `GEMINI.md`, `AGENTS.md`, …): the set agy reads can grow
  with any release; anything besides the clone is refused instead.
- Cleaning the folder before a start: it could delete the agent's work;
  the runner deletes nothing and names what it found.
- Checking only the folder itself: an ancestor work tree's
  configuration loads all the same (review of the contract, confirmed by
  the test above).
- Resuming with `--conversation <id>` from the previous run's JSON: the
  supervised loop would have to read and keep it, for no gain over `-c`
  in a folder of its own.
- Leaving agy's mode as it comes: `auto` lets a model decide whether a
  command leaves the sandbox.

## agy's sandbox is reported off until the runner sees agy's own sandbox start

**Id:** 7b878d0c-623f-4aa9-97d5-8b3ecc23c2d6
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the antigravity adapter (tsk-ydpnmpdzpc0a, code part), 2026-11-14; agy 1.5.7's `--help`, its changelog and its built-in documentation; docs/api.md §15.3; review of PR #1815 (fix order A449: a namespace probe is a precondition, not agy's sandbox start), 2026-11-14
**See:** runner.md#antigravity-starts-in-a-workspace-folder-that-holds-only-the-clone-in-a-mode-the-runner-sets — b0646ec1-c909-456c-842d-28f2d4facd54 — as of 2026-11-14
**Revisit when:** agy gains a command, flag or dry run that starts its terminal sandbox alone without a model call or the sign-in, or a setting that fails a run when the sandbox is missing: then a bounded check of that start can report `on`

The runner advertises `sandbox: off` for agy on every host, so an agy
placement runs as `sandbox_unavailable` and `require_sandbox = true`
refuses it. The session settings still switch agy's terminal sandbox on
(`enableTerminalSandbox`): what the runner reports does not change what
agy does. `maity runner check` tries, as the agents' user, whether the
namespaces agy's sandbox needs start (`unshare --user --map-root-user
--mount --pid --fork --net true`, on Linux, on an ssh host there) and
prints the result as a diagnostic, "agy's sandbox start not verified";
it never turns the capability on.

**Reason:** §15.3 lets the runner say `on` only where it has seen agy's
sandbox start, because agy runs a command without it, silently, where it
cannot start. agy 1.5.7 has no command that starts only its sandbox, as
`codex sandbox -- true` does for Codex. Namespaces that start are the
precondition named in agy's changelog, not agy's sandbox start, so they
cannot satisfy the contract; until a bounded check of agy's own start
exists, the code follows the contract and reports `off`.

**Rejected alternatives:**
- Reporting `on` where the namespaces start (the first version of this
  PR): a precondition probe, which the contract does not accept as having
  seen the sandbox start.
- A headless `agy -p` run that executes one command: it needs the
  operator's sign-in, costs model quota at every service start, and its
  answer is the model's text, not an exit code.
- Turning agy's sandbox off in the session settings while it is
  reported off: `proceed-in-sandbox` would then fall back to asking,
  which a supervised run refuses, and a host where it does start would
  lose it.

## agy's session settings: grants as command rules, the sign-in denied, hosts allowed

**Id:** af2e96d9-ddfc-4415-9118-48bce30f8bf8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the antigravity adapter (tsk-ydpnmpdzpc0a, code part), 2026-11-14; the test runs of agy 1.5.7 in the notes of card tsk-e062xzrgfxxc; agy's built-in documentation of its rule forms; `agy --settings <file> agents` in a home of its own, which refuses unknown settings and values but not malformed rules
**See:** runner.md#antigravity-starts-in-a-workspace-folder-that-holds-only-the-clone-in-a-mode-the-runner-sets — b0646ec1-c909-456c-842d-28f2d4facd54 — as of 2026-11-14
**Revisit when:** a real session shows a rule form not matching as assumed, or git cannot reach the forge from agy's sandbox

Details of the settings §15.3 describes, chosen in the code:

- A grant's `allow` entry became `command(<prefix>)`: the words before
  a closing ` *`; an entry with another `*` is left out. Only the prefix
  form was seen to work in a run; agy accepts a malformed rule at start
  without a word, so an unverified form (`regex:`) could silently match
  nothing. The cost: an entry without ` *` allowed any arguments.
  Superseded for entries without `*` by the exact grants below
  (f0ef544a-a531-4073-9572-af946f5475b2), 2026-11-15, and for the closing
  ` *` entries too — no command grant is given to agy any more — by
  f8a7b727-8c1f-4df9-98eb-8f9ef8879352; the left-out entry with another
  `*` stays as described here.
- The file tools are denied the private paths every sandbox hides, but
  for `~/.gemini` only agy's sign-in file: agy's sandboxed commands use
  their scratch and artifact directories there. Other harnesses' sandboxes
  hide all of `~/.gemini`.
- Writes to GIT_PROTECTED are denied to the file tools, as Claude Code's
  `Edit` denies are. Whether such a deny also makes the path read-only in
  agy's sandbox, as the `.git/maity` read deny masked that directory in
  the test, is unknown, so each session gets SANDBOX_GIT_CONFIG as well;
  the three settings do no harm where `.git/config` stays writable.
- `read_url(<host>)` for the hub, the forge and the grant's `network`
  hosts, agy's documented rule for a domain, so git and `maity`'s
  traffic may get out of the sandbox's network block. Not seen in a run.
- `command(...)` denies only for prefixes (`git -c`, `git --config-env`,
  `git --exec-path`, `gh`); git is not allowed at all and runs in the
  sandbox, as §15.3 lists only `maity` and the grant.

**Rejected alternatives:**
- Denying all of `~/.gemini` to agy as well: it could break agy's own
  sandboxed scratch, unseen.
- Mapping grants with agy's `regex:` form to keep Claude Code's exact
  match: no run showed how agy anchors it. Taken up later as a deny
  beside the allow, once agy's matching code had been read
  (f0ef544a-a531-4073-9572-af946f5475b2).

## agy grants are exact, as for Claude Code: a deny for each exact entry's longer forms

**Id:** f0ef544a-a531-4073-9572-af946f5475b2
**Type:** decision
**Status:** superseded
**Superseded by:** f8a7b727-8c1f-4df9-98eb-8f9ef8879352
**Evidence:** inferred
**Source:** card tsk-k5z0t8gdr835 and the coordinator's go-ahead for the deny design, 2026-11-15; agy's permissions documentation; agy 1.5.9's command matching read from its binary; `agy --settings <file> agents` in a home of its own; review order A582 on #1828 (the line-feed case), with Go's regexp/syntax source; review order A587 on #1828 (the empty argument), with agy's terminal.RequiresExactMatch, its walker, terminal.wordLiteral and extractSimpleCommands.func1 read from the binary
**See:** runner.md#agys-session-settings-grants-as-command-rules-the-sign-in-denied-hosts-allowed — af2e96d9-ddfc-4415-9118-48bce30f8bf8 — as of 2026-11-15
**Revisit when:** a signed-in agy session shows how an environment assignment (`VAR=x cmd`) or a plain redirect (`cmd > f`) on a granted command is matched, or an agy release changes how `command(...)` rules match, keeps an empty word, or adds an exact form

An exact `allow` entry `a b` (no `*`) becomes the allow rule
`command(a b)` plus the deny rule
`command(regex:a b [[:ascii:][:^ascii:]]*)`; an entry
ending in ` *` stays a plain prefix, and one with another `*` is left
out, both as before. An exact entry is left out for agy, named by
`maity runner check`, and runs in agy's sandbox like an unlisted
command when a word holds a character outside letters, digits and
`_ / = : @ % , -`, or when another entry may allow a longer command
that starts with it. One covered by a ` *` entry gets no rules.

**Reason:** agy matches `command(x)` and `command(regex:x)` both by the
command's first words: a rule with more words than the command never
matches, otherwise each of the rule's words is compared with the
command's word at that place, literally or as `^(?:word)$`, and nothing
anchors the end. An allow alone therefore granted any arguments, a
wider grant than Claude Code's exact `Bash(a b)`. The deny has one word
more, so it never matches the entry itself and matches every longer
form, and deny beats allow; a longer form is then refused, also inside
the sandbox, as an ungranted command is under Claude Code's `dontAsk`.
agy accepts a regex that does not compile without a word and it then
matches nothing, so a deny it could misread would fail open: hence the
character set, which holds no regex or shell metacharacter (`.` and `+`
included, which match more). Without its deny an exact entry would be a
prefix, so such an entry is not allowed at all. The deny's last word
is a bracket class of all ASCII and all non-ASCII characters, not
`.*`: agy compiles each word with Go's `regexp.Compile` (syntax.Perl,
without the `s` flag), where `.` matches every character but a line
feed, so `.*` did not cover a quoted argument holding one. The class
holds no backslash, quote, parenthesis or `|`, which agy's shell split
of the rule would take apart or reject; it reaches the regex compiler
unchanged on every path of that split. Two exact entries that
share a start cannot both stay exact with one deny each: the shorter
one's deny refuses the longer one, so the shorter one is left out.
The env-assignment and redirect cases in **Revisit when** are open: both
need a signed-in agy, which has not been allowed for a test run.

**Limit (superseded):** agy cannot tell an extra empty argument apart; it is allowed.
`a b ''`, `a b ""`, `a b $''`, `a b ' '` and `a '' b` run as `a b`,
outside the sandbox, though the shell passes one argument more. No rule
can catch it (review order A587 on #1828, agy 1.5.9 read from its
binary): such a line does not make agy match the whole line, since
`terminal.RequiresExactMatch` fires only on a NUL, a non-ASCII control,
format or space character, a parse error or a construct its walker
refuses, and the walker accepts `*syntax.SglQuoted` (with or without
`$`) and a `*syntax.DblQuoted` of literals; so agy matches words, and
`terminal.wordLiteral` takes a quoted word's raw text and ends in
`strings.TrimSpace`, and `extractSimpleCommands.func1` skips a word
whose text is then empty, before `shared.coversCommand` hands the words
to `MatchesConfigAny`. `MatchesConfigAnyRaw`, the only matcher that sees
the raw line, runs only on the whole-line path. The same trim makes
`a ' b'` count as `a b`. `maity runner check` names the limit once per
repository with exact entries for agy, and docs/runners.md says it to
the owner.

**Rejected alternatives:**
- Keeping the prefix match as a recorded difference: one harness would
  get a wider grant than another from the same list.
- A PreToolUse hook that forbids leaving the sandbox for a line that is
  not an exact grant: `--settings` refuses `hooks`, so it would live in
  the workspace's `.agents/`, which the agent can write, or in the
  agents' user's shared `~/.gemini`, re-parse the shell itself, and was
  untried.
- A shim for the granted programs on `PATH`: an allowed command leaves
  the sandbox, and agy canonicalises command names, so the shim cannot
  tell a sandboxed call from one that leaves it.
- `ask` rules instead of the deny: a person is asked in an interactive
  run and a headless run refuses, so nothing beyond the deny.
- Escaping `.` or `+` in the deny: agy splits the rule like a shell
  line, which would take the backslash, and no run showed another
  escape working; left out rather than risk a deny that fails open.
- A complement regex per word so that entries sharing a start stay
  exact together: complex, and untried in agy.
- `(?s).*` or `[\s\S]*` as the deny's last word: the shell split takes
  the backslash, and the parentheses are shell syntax, so the word
  would reach the compiler only through agy's fallback for a line that
  does not parse; the bracket class needs no such fallback.
- A deny that catches an empty quoted word after an exact entry (review
  order A587's option (a)): agy drops the word before any rule is
  compared, and `MatchesConfigAnyRaw` sees the raw line only on the
  whole-line path, which such a line never takes; no rule can say it.

## agy command grants are dropped, exact and prefix: agy reads the command past a leading assignment or wrapper

**Id:** f8a7b727-8c1f-4df9-98eb-8f9ef8879352
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-vgce05kdmk2x and the coordinator's go-ahead, 2026-11-15, first for dropping exact grants and then, once the same exposure was confirmed for prefix grants, for dropping those too (two stacked pull requests on the one card); agy 1.5.9's command matching read from its binary (terminal.extractSimpleCommands, terminal.isEnvAssignmentToken, terminal.isCommandWrapper, terminal.canonicalCommandName, shared.coversCommand, commandutils.MatchesConfigAny; the raw-line matcher commandutils.MatchesConfigAnyRaw and terminal.RequiresExactMatch on the whole-line path); agy's permissions documentation
**See:** runner.md#agy-grants-are-exact-as-for-claude-code-a-deny-for-each-exact-entrys-longer-forms — f0ef544a-a531-4073-9572-af946f5475b2 — as of 2026-11-15
**Revisit when:** an agy release changes how it reads the invoked command from a line, gives `command(...)` rules a way to match a whole line or an exact form, or forbids a leading assignment or wrapper on an allowed command; a sound way to keep a prefix grant, or to tighten the `command(maity)` grant, for agy is found; tsk-zjv2xyhyggnm confines `maity` at the OS level; or a signed-in agy session is allowed and shows a granted command matching differently

Neither an exact `allow` entry `a b` (no `*`) nor a ` *` prefix entry `a b *`
is given to agy as a rule: each is left out, named by `maity runner check`,
and runs in agy's sandbox like every unlisted command. An entry with another
`*` (`a *.py`, `npm run test:*`) is left out without a word, as before, since
a rule word is matched on its own. So agy now gets no `command(...)` allow
from a grant's command list at all: only `command(maity)`, the `read_url`
hosts and the file and command denies stand. The same `allow` command list
reaches Claude Code unchanged, OpenCode takes it into its own rules, and
Codex does not get it (79837674-493a-43dd-8670-e8b163309bca).

**Reason:** agy does not match a `command(...)` rule the way Claude Code
matches `Bash(...)`. It reads the invoked command from the line first,
stepping over a leading environment assignment (terminal.isEnvAssignmentToken)
and a command wrapper such as env, nohup, time, nice, sudo, xargs or timeout
(terminal.isCommandWrapper), before any `command(...)` rule is compared; only
the words that remain reach the matcher (shared.coversCommand →
commandutils.MatchesConfigAny; terminal.canonicalCommandName canonicalises the
program name). The one matcher that sees the raw line,
commandutils.MatchesConfigAnyRaw, runs only on agy's whole-line path, and
terminal.RequiresExactMatch takes that path only for a NUL, a non-ASCII
control, format or space character, a parse error or a construct its walker
refuses — not for a plain leading assignment or wrapper. So no `command(...)`
rule can describe a line that carries such a prefix. This defeats both grant
forms the same way: an exact entry's earlier allow+deny pair (f0ef544a) let
the bare command run outside agy's sandbox and relied on the deny to refuse
longer forms, but a line carrying the prefix matched the bare allow with the
prefix already stepped over and no deny could refuse it; and a ` *` prefix
entry, emitted as a bare `command(a b)` allow, matches such a line with the
prefix stepped over just as directly, running the command outside the sandbox.
A `command()`-level hard refusal of every assignment or wrapper line is
therefore not provably complete — the prefix is gone before any rule is
compared, and the raw-line matcher is not on that path — so there is no sound
way at the settings level to keep either an exact or a prefix command grant
for agy. Dropping both is the only sound choice: such a command then runs
inside the sandbox, like an unlisted one. This narrows agy grants (a
command that needs to run outside agy's sandbox through the `allow` list no
longer can — arrange it another way, or run it under Claude Code;
docs/runners.md, CHANGELOG), while the `allow` list stays unchanged for the
other harnesses that apply it.

**Limit:** one command grant remains that agy cannot be given more tightly —
`command(maity)`. The runner must let the session reach the hub, so `maity`
runs outside agy's sandbox (as for every harness), and agy applies
`command(maity)` the same way it applies any command rule, reading the invoked
command past a leading assignment or wrapper; so for agy that grant is not as
tight a boundary as Claude Code's `Bash(maity *)`. No agy setting closes this,
confirmed by reading agy 1.5.9's binary: the stepping in extractSimpleCommands
is unconditional, the whole-line path (commandutils.MatchesConfigAnyRaw, gated
by terminal.RequiresExactMatch) is never taken for a plain leading assignment
or wrapper, and `--settings` has no match-mode key and refuses unknown ones.
There is likewise no sound invocation path for `maity` the runner can arrange
at the settings level (a launcher or absolute path is matched the same way,
and the attacker's environment loads into the launcher process itself before
any re-exec). So the `command(maity)` grant keeps one command reachable
outside agy's sandbox — a residual risk the runner cannot close from its own
settings. The owner has now accepted that residual risk and re-offered
antigravity (req-9spwe33neh1z, 2026-11-16; see "Antigravity is re-offered
with its residual command(maity) risk accepted" below): `antigravity` is no
longer in `config.NOT_OFFERED_YET`, so a configuration naming
`[harness.antigravity]` is accepted by `maity runner check` and `serve`.
OS-level confinement of `maity` (the follow-up card tsk-zjv2xyhyggnm) is being
added incrementally and continues while agy runs. Stated plainly in
docs/runners.md, with no example.

**Rejected alternatives:**
- Keeping the allow+deny pair for exact entries (f0ef544a): a line with a
  leading assignment or wrapper matched the bare allow, which no deny could
  refuse, so the entry did not run exactly as granted; this is what the drop
  first replaced.
- Keeping ` *` prefix grants (as the exact-grant drop first did): a prefix
  entry is emitted as a bare `command(a b)` allow, which the same leading
  assignment or wrapper matches with the prefix stepped over, so a prefix
  grant has the same exposure as an exact one and cannot be kept soundly
  either. agy differs from Claude Code here: Claude Code's `Bash(a b *)`
  prefix-matches the literal command string, so a leading assignment keeps the
  line from matching, but agy strips the prefix first. Confirmed against agy
  1.5.9's binary.
- A `command()`-level refusal of every assignment and wrapper line: agy reads
  the command past such a prefix before any rule is compared, and the raw-line
  matcher is not on that path, so no set of `command()` denies is provably
  complete.
- A PreToolUse-style hook or a PATH shim: already rejected under f0ef544a for
  agy (no `hooks` through `--settings`; agy canonicalises command names), and
  the drop needs neither.

## Antigravity is re-offered with its residual command(maity) risk accepted

**Id:** 28ac82c8-0921-4ffb-9d3e-9ebb2f10b111
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's answer on decision request req-9spwe33neh1z, 2026-11-16; the release decision to re-offer antigravity as "Step 1 (re-offer)" targeting cli 0.1.0a14, with a separate security review
**Revisit when:** tsk-zjv2xyhyggnm lands the OS-level confinement of `maity` (the residual risk can then be re-assessed and the grant possibly tightened), or the owner withdraws the accepted risk
**See:** runner.md#agy-command-grants-are-dropped-exact-and-prefix-agy-reads-the-command-past-a-leading-assignment-or-wrapper — f8a7b727-8c1f-4df9-98eb-8f9ef8879352 — as of 2026-11-16

`antigravity` is dropped from `config.NOT_OFFERED_YET` (empty now, `()`,
after opencode was offered too),
so a `runner.toml` naming `[harness.antigravity]` is accepted by
`maity runner check` and `serve` instead of refused. agy is offered again.

Re-offering does **not** widen agy's grants: agy still gets only
`command(maity)` plus the `read_url` hosts, and the exact and ` *` prefix
command grants dropped in "agy command grants are dropped, exact and prefix"
(f8a7b727) stay dropped. The only grant reaching outside agy's sandbox is the
one `command(maity)` the runner cannot confine from its own settings — the
residual limit that decision recorded.

**Reason:** the owner decided agy should run now carrying that known residual
risk rather than stay held back until it is closed; security for it is built
incrementally. The OS-level confinement of `maity` continues as the follow-up
card tsk-zjv2xyhyggnm; it is no longer a precondition for offering the harness.

**Rejected alternative:** keep antigravity in `NOT_OFFERED_YET` until
tsk-zjv2xyhyggnm confines `maity` at the OS level (the earlier position, in
f8a7b727's limit). Rejected because the owner chose to accept the residual
risk and offer the harness now, building the confinement step by step, rather
than block every antigravity placement until that work lands.

## OpenCode (Grok) is offered; its command rules are not a security boundary

**Id:** a94f2e01-c227-4d4f-baeb-d88c5f0d3c86
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the owner's acceptance on decision request req-kezp8rppfhn5 ("ship now, harden next"), 2026-11-17, after an independent review found opencode's command rules do not bound what an agent can run; the original offer decision req-g4d2cskx6zxv and the 2026-11-15 spike (opencode 5/5 green, the limit run passed, Grok reviews ran); maintainer order tsk-sn90s6wzp9s7; #1963 review round 3 then made `runner check` refuse opencode under `require_sandbox`, like claude-code and antigravity
**Revisit when:** the OS-level sandbox for opencode (tsk-nynpvag9zvhh) lands, so the harness runs confined, or the owner withdraws the accepted risk

`opencode` is dropped from `config.NOT_OFFERED_YET`, which is now empty
(`()`), so a `runner.toml` naming `[harness.opencode]` is accepted by
`maity runner check` and `serve` instead of refused as "not offered yet".
opencode is offered running Grok.

opencode has no OS sandbox the runner switches on (`sandbox: off`), so the
command and permission rules the runner writes for it are model-steering
configuration, **not a security boundary**. An opencode agent must be treated
as able to run any command as the agents' OS user — whatever that user can
read, write or reach. The mitigation is operational, not in the settings: run
opencode's agents as a **separate OS user**, isolated from the runner and from
the other harnesses, so the blast radius is that user's own files. This is
stated plainly in docs/runners.md and the CLI README, without any bypass
detail. `maity runner check` also surfaces the residual risk, on both
backends: the local one through `_check_harness`, each ssh host through
`_check_host`. It keeps the `ok harness opencode` line and adds a
`harness opencode: no OS sandbox` one whenever the opencode check reaches it
— a missing binary or a failed `--version` errors out before it, so it is
not literally unconditional. Because every opencode placement is unsandboxed,
that line is an **error** under `require_sandbox = true` (the start is
refused, the way claude-code and antigravity call
`capabilities.sandbox_refused` when their sandbox is off) and a **warning**
without it. Unlike agy's `sandbox reported off`, this is not a diagnostic the
runner might later clear but a permanent property (opencode never has a
runner-switched OS sandbox to report). Under `layout = "single"`, where the
agents' user is the runner's own, the line spells out the concrete reach —
any command as the runner's own user, including reading the runner's state,
the other clones and logins; an ssh host has no local layout, so it takes the
generic wording (an agent can run any command as the agents' user).

**Reason:** the owner decided (req-kezp8rppfhn5, "ship now, harden next") that
opencode should run now carrying this known residual risk rather than stay
held back. It was first offered under req-g4d2cskx6zxv on a 2026-11-15 spike's
evidence (opencode green 5/5, the limit run passed, Grok reviews ran); an
independent review then showed the command rules do not bound what an agent
can run, and the owner accepted that and re-stated the risk generically. The
planned hardening is an OS-level sandbox for opencode, for example bubblewrap
(tsk-nynpvag9zvhh), which would make the harness runs confined.

**Rejected alternative:** keep opencode in `NOT_OFFERED_YET` until
tsk-nynpvag9zvhh gives it an OS sandbox, so its rules would be backed by a
real boundary. Rejected because the owner chose to accept the residual risk
and offer the harness now, with the separate-OS-user mitigation, rather than
block every opencode placement until that work lands.

## The opencode adapter fails closed on the model

**Id:** 7c23704d-d02f-4cbf-80ca-494119f8fa5c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-kf2kp09d6qew after the first live opencode test found a model-less placement running opencode's own free default (provider `opencode`, `hy4-flash-free`) instead of the configured `xai/grok-4.7`
**See:** runner.md#opencode-grok-is-offered-its-command-rules-are-not-a-security-boundary — a94f2e01-c227-4d4f-baeb-d88c5f0d3c86 — as of 2026-11-18
**Revisit when:** opencode routes a placement's model somewhere other than `--model`, or a provider other than the configured one becomes acceptable

`_opencode` takes the effective model from the placement, or the harness
`default_model` when the placement names none, and passes it as `--model`. A
model that is empty or not among the harness `models` refuses the start
(`NotYet`, surfaced as `harness_refused`) instead of launching.

**Reason:** a provider-`opencode` model is opencode-hosted (the command-rules
constraint above), so running one sends the clone's conversation — the
repository's content — to opencode's servers rather than to the configured
provider (the operator's xAI access). With no `--model`, opencode picks its
own free default, a provider-`opencode` model, so a model-less placement
leaked data silently. The effective model must therefore be one the operator
configured, and `default_model` (validated to be one of `models`) is the
fallback when a placement names none. Fail closed because the leak is silent:
a wrong model still runs and still answers, so a warning-and-continue would
let the data leave before anyone read the warning.

**Rejected alternative:** fall back to `default_model` but let an unknown or
missing model through with a warning (what opencode does on its own, minus the
log). Rejected because the harm — repository content reaching opencode's
servers — happens on the start itself, not later, so only refusing the start
prevents it.

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

## For now the runner offers Claude Code, Codex, Antigravity and OpenCode

**Id:** 62bcf506-caed-470c-a094-9bea4217b440
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision on the runner design's question 4, relayed 2026-10-22; the offer of opencode on req-g4d2cskx6zxv, 2026-11-17
**Revisit when:** the maintainer decides on the harnesses without a command allowlist when the runner goes into use
**See:** runner.md#opencode-grok-is-offered-its-command-rules-are-not-a-security-boundary — a94f2e01-c227-4d4f-baeb-d88c5f0d3c86 — as of 2026-11-17

A configuration may name `claude-code`, `codex`, `antigravity`,
`opencode` and `stub` (`antigravity` was held back here on 2026-10-22 and
re-offered later, req-9spwe33neh1z; `opencode` likewise, offered later,
req-g4d2cskx6zxv). `pi`, `hermes`, `kimi`, `cline` and `omp` stay refused
because they have no command allowlist (design §6.3).

**Reason:** the maintainer wants to discuss the rest once the runner is
in use, with real runs behind the discussion. The opencode adapter stayed
in the code while held back so that offering it cost a line, not a slice;
a 2026-11-15 spike supplied the real runs behind the decision.

**Rejected alternative:** offering every built adapter at once (back when
opencode's project-configuration switch and `instructions` path were still
unverified, design §6.1): each harness is offered on its own evidence
instead, opencode once the spike verified it.

## Model access is the operator's to arrange

**Id:** 889e6702-afb6-429c-8e89-b5d7a1561992
**Type:** decision
**Status:** superseded
**Superseded by:** 5f6c87ce-132d-4f7e-921d-d74741f369fe
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

## Model access stays the operator's; a run's usage counts reach the hub

**Id:** 5f6c87ce-132d-4f7e-921d-d74741f369fe
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's card tsk-m6sq1g0xwwn5 (tokens and cost per card, per instance and per agent) and his answers of 2026-11-11 (req-6f69nz9gdqq8, req-dqe2vaa5wkkg, req-272525w91jvf); contract `docs/api.md` §15.15
**Revisit when:** the hub is asked to price usage, hand out model access or bill; or interactive placements are to report usage
**See:** runner.md#model-access-is-the-operators-to-arrange — 889e6702-afb6-429c-8e89-b5d7a1561992 — as of 2026-11-11

How agents pay for their model is still up to the operator, and nothing
about model **access** reaches the hub: no key, no account, no login
method. What does reach it now is a supervised run's usage **counts**:
input, output and prompt-cache tokens, and the cost figure the harness
computed itself, sent by the runner when a run's work ends and before it
reports the run's end (a later record is lost). The model name, the
prompts, replies, tool calls and the provider's request ids never leave
the runner. Interactive placements report nothing for now: the runner
reads no stream from them, and the harness's session log is a format it
does not promise to keep.

**Reason:** the maintainer wants to see what a card, an instance and an
agent cost. The supervised loop already reads the harness's output for
the watchdog (§15.14), so the counts come almost for free there, and
counts carry none of the secret the earlier decision kept out of the hub.
The maintainer chose not to send the model name, so the usage records
hold no provider's model names. The hub holds model names elsewhere,
and this does not change them: a placement's `model` and the runner's
advertised capabilities (`docs/api.md` §15.5, §15.3) and a session's
`model` (§5).

**Rejected alternatives:**
- Interactive placements from the start, from the harness's session
  log: the format can change with any harness release, and a wrong read
  would show wrong numbers.
- The model name per run: it would help compare costs but puts a
  provider's model names into the hub's data.

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
**Source:** runner code on `main` after the R5 adapters (#123, #125) and the offered-harness decision 62bcf506, read 2026-10-22; the coordinator's re-check of 5ed066bf, 2026-10-22; updated 2026-11-17 when opencode was offered (req-g4d2cskx6zxv), dropping the aside that the configuration refuses it
**See:** runner.md — 62bcf506-caed-470c-a094-9bea4217b440 — as of 2026-10-22
**Revisit when:** the configuration accepts a harness without an adapter in this version, or a contract code for "not in this version" is added to §15.7

A placement whose harness is not in this runner's configuration is
reported as `failed`/`harness_refused`; a mode or model the configuration
does not list is `harness_refused` with `mode_unsupported` or
`model_unsupported`.
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
**Status:** needs-review
**Evidence:** confirmed
**Source:** the coordinator's post-merge re-verification of #125 and #147 (both holes reproduced) and approval of the plan, 2026-10-22; the independent review of #184 (the submodule route, opencode's pattern-keyed search permissions), 2026-10-22; verified on the runner VM with codex-cli 0.156.1 and git 2.47.3 (`codex sandbox`, no model run); Claude Code 2.1.308's settings strings for `allowRead`; Claude Code 2.1.318 with git 2.47.3 on the maintainer's laptop, 2026-11-04 (a call with a command, a variable or a PATH in front of `maity`, no hub; and the harness's own start-up warning that it does not check `Write(…)` deny rules); the coordinator's approval of the adapter hardening plan, refusal of prefixed grant rules included, 2026-11-04; the first sandboxed placements on a runner, whose `git fetch` failed on a read-only `.git/FETCH_HEAD`, and the lead's card for the narrower list, 2026-11-10; Claude Code 2.1.321 with bubblewrap, 2026-11-10 (`claude -p` in a scratch clone of a local bare repository with the runner's settings shape, the model running only `touch`, `git fetch`, `git commit` and `cat` probes, no hub): with the blanket deny, `fetch` and `commit` failed on a read-only `.git`; with the list below both worked, and every listed path and `.git/maity` stayed refused; a reviewer's reproduction of a `commondir` written from inside the sandbox, and the maintainer's choice of option (c), the start check with its detail code, req-2adhtsb3ct75, 2026-11-10; the maintainer's choice of the docs over a start refusal of a rebase or sequencer state, with a section on the runner page, req-ynqaa1dkt1pe, 2026-11-10
**See:** runner.md — c2acd907-0f26-4850-8272-063390f1d6a7 — as of 2026-10-22
**Revisit when:** Claude Code's `allowRead` precedence over a more specific `denyRead` is verified, a harness runs git in the clone with an environment the runner does not set, git learns another file in `.git` that redirects where it reads configuration or runs a program, Claude Code stops turning `Edit(…)` denies into sandbox write denies, or a harness version other than the one in `capabilities.CHECKED` is in use

Every agent session gets `GIT_COMMON_DIR=<clone>/.git` in the
environment the runner gives the harness, and through `GIT_CONFIG_COUNT`
`core.fsmonitor=false` and `diff.ignoreSubmodules=all`. The session's
git then ignores a `.git/commondir` the agent wrote from inside its
sandbox, and does not
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
needs it. opencode's `grep` and `glob` are off, since they cannot be
scoped to a path. maity and the runner
run git only through `proc.GIT`, a clone into a missing directory, and
`gc`'s pinned read; a test pins that.

The pin covers the session's git and maity's own, not a person's plain
`git` in the clone later: that git follows a `commondir` or `worktrees/`
the agent wrote, and neither can be denied (below). So the runner reads
every existing clone at its start the way `gc` does, before the join and
the harness. A clone whose `.git` is not a plain clone's (a `commondir`,
`worktrees/`, a `config.worktree` with content, a configuration key a
plain clone has not) is not started: it is reported `failed`,
`workspace_in_use` with `not_a_plain_clone` (§15.7), the finding goes to
the runner's log, and the runner deletes nothing in it and does not try
again. The sandbox's empty placeholders pass. A person runs git in a
runner's clone only through `maity` or after the clone passed the
runner's check with no session since (the check of a start that then
stopped; `gc --revoked` checks only a clone whose credential is revoked
and that no placement uses), and then only git that reads; in a clone
the check refused, no git at all. Only reading, because the check does
not look inside `rebase-merge/`,
`rebase-apply/` or `sequencer/`, which the agent may write, so a
`rebase --continue` or `--skip` would run an `exec` line planted
there. A session that runs on after the
check can plant again, so the check covers the clone as it was then;
otherwise the work is read from the pushed branch. A person works in a
clone of their own; the runner page (`docs/runners.md`, "Working in an
agent's clone") says so for operators.

A repository's grant may only add plain commands, a grammar rather
than a list of bad spellings: a program name or path, then arguments of
plain characters (the CLI README names them), `*` only in an argument.
The program is never `env` or `maity`, under any path, case or Windows
extension, and no part of an argument (between `/`, `:`, `=` and the
other separators) is `maity`. Assignments, quotes, variables, escapes,
shell operators and a `:` in the program (Claude Code's `prog:*` form)
are refused when the configuration is read, and an adapter skips such a
rule as well.
`maity` stays the runner's own rule. Claude Code's `.git` write denies
are `Edit(…)` rules, which cover its file-editing tools; it does not
check a `Write(…)` deny rule. They name what redirects git's
configuration, hooks and object sources: `config`,
`config.worktree`, `hooks/`, `info/` and `objects/info/alternates`, the
same paths as sandbox write denies, plus `.git/maity`. The rest of `.git`
stays writable, because Claude Code's sandbox turns an `Edit(…)` deny
into a write deny for every command, and commit, fetch and push need
refs, the index, objects, logs and `FETCH_HEAD` between them (a commit
writes the index, a fetch `FETCH_HEAD`, both refs, objects and logs). A call with something in front of
`maity` is held by the runner's hook (63492c65), not by how Claude
Code's sandbox exclusion matches it (corrected in S200, 2fa61a18); the
Claude Code version last checked is `capabilities.CHECKED`, and with
another version the runner still
starts the agent, and `runner check` and the supervisor log say that it
was not checked for it.

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
A grant rule is matched as written, so one with a prefix would be
allowed outside the rules the runner checked; refusing it in the
configuration says so to the operator before an agent starts. The
version check is a warning that does not block the start, as the
hardening task asked: what was checked is the harness's behaviour with
one version, not a contract.

**Rejected alternatives:**
- Denying `Edit(…)` on all of `.git`: the sandbox made the whole
  directory read-only for every command, so no agent could fetch, commit
  or push (the first sandboxed placements, 2026-11-10).
- `commondir` in the list: for a file that does not exist, the sandbox
  leaves something git cannot read, and every git call in the session
  failed on it. `GIT_COMMON_DIR` makes the session's and maity's git
  ignore it, and the start check keeps the runner from starting in a
  clone that has one.
- A read-only `.git` with write access to `objects`, `refs` and the
  index only: git creates its lock files and `ORIG_HEAD` in `.git`
  itself, so commits fail.
- Denying writes to each redirecting file (`commondir`,
  `config.worktree`, `info/attributes`) as the boundary: files that do
  not exist yet cannot be bound read-only reliably, and it is the
  enumeration the gc fix already moved away from. The list above is a
  second layer over the `GIT_COMMON_DIR` pin and clonecheck, not instead
  of them.
- Relying on the pin alone for a clone a session ran in: a person's plain
  `git` there has no pin and would follow the plant. Checking at the
  start costs one read of `.git` per start, the read `gc` already does.
- Refusing a rebase or sequencer state (`rebase-merge/`, `rebase-apply/`,
  `sequencer/`) at the start: an agent's own interrupted rebase would
  then keep its placement from restarting. Only git that continues such
  a state runs what it holds, and the docs tell a person not to. The
  maintainer chose the docs over the refusal (req-ynqaa1dkt1pe).
- Removing a planted `commondir` or `worktrees/` at the start: the runner
  deletes nothing in an agent's clone, so what was planted stays there
  for someone to look at.
- Hiding the whole home from Codex: the agent's `maity`, `git` and
  toolchains are often installed there.
- `--ignore-submodules=all` on `maity`'s own `git status`: it also hides
  a newly staged submodule, so `report` would miss a change. The
  configuration setting keeps git out of the submodule and still shows
  the staged gitlink.
- Refusing a list of bad spellings (`NAME=` and `env` in front, `maity`
  after an operator): `NAME+=`, `/usr/bin/env`, a quoted `maity`,
  `maity:*` and `maity.exe` still passed, found in review. A grammar
  refuses what it does not name.
- Only a warning for a grant rule with something in front or naming
  `maity`, keeping the rule: the harness would still allow it as
  written, and a configuration the runner accepted today then means
  more than the runner checked. Refusing it changes what a valid
  configuration is, and says so by name when `check` or `serve` reads
  it.
- Keeping the `Write(…)` deny next to `Edit(…)`: Claude Code warns at
  start that it ignores it, and a rule that does nothing reads as a
  boundary.

## The sandbox-checked Claude Code version is raised to 2.1.325

**Id:** 2fa61a18-c8c9-4d9c-9c15-b1d5cbf1fcc6
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** card tsk-zjv2xyhyggnm (the owner/lead's approval of the bump); a static read of Claude Code 2.1.325's command matching, with no runtime session with the harness; the security detail of the read held to DM to the lead and the security lead; the runtime re-check on 2.1.325 and 2.1.329 of security round 5, S200, 2026-11-20 (996b6f48), its details with the lead; the order to correct this entry's claim and the README's, relayed by the lead from the author of the security record, 2026-11-20
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-16
**See:** runner.md#a-placed-claude-code-agent-runs-maity-alone — 996b6f48-a8d7-4b81-b977-33cef46bc4cc — as of 2026-11-20
**Verification:** corroborated — the corrected claim below: in the runtime re-check (S200) the runner's hook refused before it ran each tested line with something in front of `maity` but the allowed assignments, and held those to one plain call; the claim it replaces, that the sandbox itself keeps such a call inside, was not confirmed without the hook
**Revisit when:** a later Claude Code version changes how it matches commands for the sandbox, which calls for a re-check before another bump; the runner's hook stops holding a placed session to one plain `maity` call; the re-check of 996b6f48 decides on `capabilities.CHECKED`

`capabilities.CHECKED` for `claude-code` is raised from 2.1.318 to 2.1.325,
so `maity runner check` no longer warns that the installed harness is a
version whose sandbox behaviour was not checked. What holds for a call
with something in front of `maity` is the runner's hook (63492c65): it
refuses such a line before it runs, but for assignments to the allowed
names, after which the line is held to one plain call. The runner does
not rely on Claude Code's sandbox exclusion for such a call.

Corrected in security round 5 (S200): this entry first said that such a
call stays inside the sandbox, as at 2.1.318, confirmed for 2.1.325 by a
static read. The runtime re-check on 2.1.325 and 2.1.329 (996b6f48) did
not confirm that without the hook. The bump itself is not undone; whether
`CHECKED` stays, moves or means something else is left to the re-check
of 996b6f48, which is why this entry stays `needs-review`.

**Reason:** the installed runner moved to Claude Code 2.1.325, and the
version check warned that this version was not checked. The decision to
record the bump was approved by the lead and the security lead on a
static read of how 2.1.325 matches the command for the sandbox; the
particulars of that read are held to DM and kept out of the repository,
so this entry stays general.

**Rejected alternative:** a runtime confirmation with the harness before
bumping. No session able to run the harness was available, and the static
read together with a downstream guard that catches the relevant case was
judged enough to raise the recorded version then. The runtime check came
later (S200) and is why the claim above was corrected.

## In the `agent_user` layout everything on the agents' side belongs to the agents' user

**Id:** 3edc329a-6a10-427d-a0a3-733127f14b20
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §7.6; the coordinator's choice to do the `agent_user` layout before ssh, 2026-10-22; implementation of runner slice R7a, 2026-10-22; not yet run with a real second user; a tester's macOS run, where that host's `install` refused `-D` for every write on the agents' side, its rerun, where `chmod` took a `--` after the mode for a file, and the reviews of #1411, 2026-11-05
**See:** runner.md — 2bdc5809-b08b-4fa2-97bc-004d37c4cddb — as of 2026-10-22
**Revisit when:** agents need separation from each other, not only from the runner (one OS user per agent), a live run shows a harness writing where the agents' user cannot, or a target host lacks one of the tools the agents' side writes with

With `layout = "agent_user"`, every command for the agents runs as
`sudo -n -u <agent_user> --`, with only the environment it needs passed
explicitly. That covers the tmux server and its sessions, the clone, the
join, the supervised loop, `gc`'s git and its revocation check, and stopping
a process group. Everything the agents' side needs (tmux socket and
configuration, logs and the harness settings) lives under
`~<agent_user>/.maity-runner/` and is written as that user; Codex's own
`CODEX_HOME` is the exception — it lives in the placement scratch under the
workspaces root, not here (9084b0ed). The runner's
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

Files for the agents' side (in this layout and on ssh hosts) are written
by one fixed `sh -c` script with tools BSD, macOS and GNU all have. It
makes the file's own directory 0700 if missing, writes the text from
stdin into a `mktemp` file next to the path, sets it 0600 and renames it
over the path. A link at the path, to a file or a directory, is removed
first, and a directory at the path is refused. The text never appears in
an argument, and the path never holds a half-written file. Each `--`
comes before a command's first operand (`chmod -- 600`, not `chmod 600 --`):
BSD tools read no options after the first operand.

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
- `install -D -m 600 /dev/stdin <path>` for the agents' files: GNU's
  meaning of `-D` (make the missing parents) is not the same everywhere.
  Some BSD and macOS versions refuse `-D`, as the tester's macOS host did,
  so no agent could start there in this layout or over ssh; others give
  it another meaning.
- `cat >` straight into the path: it writes through a link planted
  there, and leaves a half-written file when it fails.
- `mv -T` or other GNU-only guards against a directory at the path: the
  same portability problem as `install -D`.

## On the ssh backend each host is a target that runs its own `maity`

**Id:** 256e800f-3ddc-482e-b4ac-e6b09d69fe72
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.4; implementation of runner slice R7b, 2026-10-22; the independent review of #172 (an sshd test found that ssh cannot create its ControlPath directory), 2026-10-22; tested against a fake `ssh` and against a real sshd on localhost, not yet against a remote host
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
`maity runner stub`). `maity runner loop` and `maity runner logcap` take
only the file the runner wrote for them there:
`~/.maity-runner/agents/<placement>/loop.json` and
`~/.maity-runner/logs/<placement>.log` (`commands.runner_own_file`). The
path must be written as exactly that one, with the home from the user
database, not from `HOME`, and no `..` or doubled slash; no step from
`~/.maity-runner` down may be a link, each directory is this user's and
not writable by others, and the file is an existing regular file of this
user with a single link that neither group nor others may write. Under a
placement it must be that placement's own file; a `MAITY_PLACEMENT` that
is set but not a placement id, empty included, owns no file (card
tsk-rasfq0wt751a: an empty one had skipped the check). So on an ssh host the
runner makes the pane's log before pipe-pane starts logcap. It is checked
on every call, not only under `MAITY_PLACEMENT`, which an agent can drop
from its own `maity`'s environment: an agent's `maity` runs outside its
sandbox (security round 5, S201/S202), and `maity --for … runner` is
refused. Claude Code, opencode and agy also deny `maity runner` in their
command rules (`adapters.MAITY_RUNNER_DENIED`, agy's
`AGY_DENIED_COMMANDS`; Codex runs `maity` inside its sandbox): no agent
needs it, the runner and the harness start the in-session commands
themselves. Claude Code's sandbox also denies writes to every private
path, `~/.maity-runner` among them. The checked path is opened again by
`loop` and `logcap`, so this rests on the agent being unable to write
under `~/.maity-runner`; the lasting answer is a runner command an agent
cannot reach at all, with the file checked on the descriptor it uses. The join runs the host's `maity` too, so the
agent's credential is written on the host and never passes through the
runner. Workspace records are keyed `<host>:<path>`. A sandbox's read
denies are the host's: the remote user's home secrets, its
`~/.maity-runner` and the other clones' credentials listed on the host,
never paths of the runner's machine. `gc` and `workspace claim` stay
local-only in this slice.

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

## A placement without a target stays on the host it was first given

**Id:** 0448a690-171f-4f75-8f33-a896dd3f7e0a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.2, §5.4 and §15.7 of the API contract; the contract owner's choice of `target_unknown`, 2026-10-22; implementation of runner slice R7b, 2026-10-22
**Revisit when:** the runner gains a way to move a clone and its credential between hosts, or operators ask for load-based placement

A placement that names a target runs there. One with `target: null`
goes to the first reachable host, in configuration order, with a free
slot. It is recorded there and stays there across ticks and runner
restarts. A target the configuration no longer has is reported as
`failed`/`harness_refused` with the detail `target_unknown`. While a host
does not answer, its placements keep their last reported state, and the
runner advertises the host with `reachable: false` and
`unreachable_since` at once instead of reporting a reason.

**Reason:** a clone and its credential exist on one host. Moving a
placement to another host would start it without its work and its
identity. The first free host in configuration order is predictable for
the operator, who orders the list. Reachability is a property of the
host, not of a placement (§15.7), and an agent on a host that lost its
network is still running.

**Rejected alternatives:**
- Choosing the least loaded host on every start: a restart could land on
  another host and lose the clone.
- Reporting an unreachable host's placements as failed: the agents keep
  running there, and the report would be wrong once the host answers.


## A provider limit reaches the runner as the loop's exit 22, and no harness signals one yet

**Id:** 924bb731-5f0d-4532-b785-e651d0949988
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §15.7 and §6.12 as settled in the contract's review rounds (recognition only by a signal verified on a real run; the reset_unknown backoff); implementation of the CLI side of #158, 2026-10-22
**Revisit when:** a real run of Claude Code or Codex shows the exit code or output that marks its provider limit, or a harness names its reset time in a form the loop can read

The supervised loop learns from the adapter which exit codes are the
harness's provider limit (`limit.exit_codes` in its spec). On such an
exit it writes the harness's own exit code to `limit.json` in the
agent's directory and exits 22. The runner maps 22 to `rate_limited`,
`reason: quota`, `detail: reset_unknown`, with that exit code and
`retry_at` 15 minutes on, doubling with each limit in a row up to 2
hours. When a run of the loop had ended cleanly before the limit, the
loop exits 23 instead of 22, and the runner starts the row over; so does
any other end of a run, and a new generation. The runner deletes
the file before each start and reads it as the agents' user, never
through a link and never blocking on a FIFO, at most 512 bytes, and takes
nothing but a plain exit code from it. No adapter lists an exit code yet, so for
now every limit exits as an ordinary failure, as §15.7 asks until a
signal is verified; a reset time a harness names is not read either.

**Reason:** the loop is the only process that sees the harness exit, and
the runner only sees the loop's exit status; a fixed exit code plus a
file in the agent's directory carries the harness's own code without a
new channel. That directory is the agents' side, so the file is
untrusted input: an agent could plant a link to a device or a deep JSON,
or a reset time that holds its slot for a week. Guessing a harness's limit signal would turn
some real crashes into limits, which hide from the crash cap and set the
member's availability; an empty list keeps the old behaviour until a run
shows the signal. The loop's clean runs between two limits never reach the runner, so the
loop says so in its exit code: the file is the agents' to write, the exit
status is not, and a session's length alone would reset the row for
sessions that simply work a while before each limit.

**Rejected alternatives:**
- Reading the harness's output in the pane for limit messages: the loop
  would have to capture what the agent sees, and the wording changes with
  every harness version.
- A new tmux option to pass the limit to the runner: the runner already
  reads the agent's directory, and an option would outlive the session's
  exit only by accident.

## The limit file is read on the agents' side by the runner's own module, not by `dd`

**Id:** aa29acab-65eb-4f60-a8da-ee284877266f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the macOS verification of #1411 (macOS 27.2: `/bin/dd` reads plainly but answers every `iflag=` with "unknown iflag", exit 1) and the team lead's go on the plan for card tsk-gvh28gtqjrb3, 2026-11-06
**Revisit when:** the runner reads the agents' side through a channel of its own instead of running commands there
**See:** runner.md#a-provider-limit-reaches-the-runner-as-the-loops-exit-22-and-no-harness-signals-one-yet — 924bb731-5f0d-4532-b785-e651d0949988 — as of 2026-11-06

In the `agent_user` and `ssh` layouts the runner reads the loop's
`limit.json` by starting `maity.runner.limitread` on the agents' side:
`python -I -m maity.runner.limitread PATH` through sudo, `maity runner
limitread PATH` on an ssh host, with the agents' PATH. The module opens
the file as the runner does in its own process (no link followed, no
blocking on a FIFO, a regular file only, at most 512 bytes) and prints
it. A host whose `maity` has no `limitread` yet reads nothing, and the
limit is recorded without an exit code.

**Reason:** the read was `dd iflag=nofollow,nonblock`, and the `dd` on
macOS has no `iflag`: there it never read the file, so a limit on a Mac
host always lost its exit code. The runner's own module behaves the same
on every POSIX host and is already how the loop and the stub start on
the agents' side.

**Rejected alternatives:**
- `dd` without `iflag`, or `cat`: they follow a link and wait on a FIFO
  the agents planted, which the read exists to refuse.
- Falling back to `dd` when the host's `maity` lacks `limitread`: on
  macOS that is the read that fails anyway, and elsewhere it would keep
  two ways of reading alive. No exit code is the safe answer.

## The runner records Claude Code's folder trust for the clone before an interactive start

**Id:** 71f94925-ab96-4e3e-81e6-3ea0cbaf9356
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-2ekq5dsy8anz (the first live runner test, 2026-11-09: Claude Code 2.1.319 in a fresh clone waited at "Is this a project you created or one you trust?" and the agent never came online); the team lead's card; the key, file, lock and lookup checked against the installed 2.1.319 and by starting it with and without the entry; the maintainer's decision req-bebf2krde3pp (2026-11-09) to accept the scope as a known limit
**Revisit when:** Claude Code changes where or how it records an accepted trust dialog, gains a flag that trusts a folder for an interactive start, or the runner starts sessions with `CLAUDE_CODE_IGNORE_PERSISTED_TRUST` or `CLAUDE_CONFIG_DIR` set
**See:** runner.md#the-limit-file-is-read-on-the-agents-side-by-the-runners-own-module-not-by-dd — aa29acab-65eb-4f60-a8da-ee284877266f — as of 2026-11-09

Before an `interactive` Claude Code session starts, the runner sets
`projects[<the clone's real path>].hasTrustDialogAccepted: true` in the
agents' Claude Code configuration: `~/.claude/.config.json` when that is
a non-empty file, or an empty one with a write bit while
`~/.claude.json` is missing; otherwise `~/.claude.json`. It writes under
`<file>.lock`, the directory Claude Code's own saves take, the way
proper-lockfile takes it: by `mkdir`, with the lock's mtime renewed
while it is held, and a lock not renewed for 10 s taken as given up and
removed. Right before it replaces the file it checks that the mtime is
still its own; a runner that finds it lost the lock writes nothing and
fails. Nothing is put inside the lock directory, which must stay
removable with `rmdir`. In the `agent_user` and `ssh` layouts the
runner's own module (`maity.runner.trust`) does this on the agents'
side, as for the limit file. When the entry cannot be written (a file
that is not UTF-8 text holding a JSON object or whose text cannot be
written back as UTF-8, a lock held past 15 s, a stale lock that
cannot be removed, a lost lock, a failed read or write, any other
`Exception` on the way), the start fails with the cause in the log. `supervised` sets nothing: headless (`-p`),
Claude Code asks for no trust and records none.

Apart from the clone's entry nothing in the file changes, with one
accepted exception. The lock is advisory, as proper-lockfile's is, and
the check and the replace are two steps. A runner stopped between them
for longer than the stale time (SIGSTOP, a suspended machine) can
replace a write another process made after taking the lock over. That
newer write is then lost. If it was another clone's trust entry, that
agent meets the trust question again on its next start.

The entry is Claude Code's own trust record, so it outlives the
placement and is not limited to the runner's session. The runner never
removes it. The runner's own session loads no project configuration
either way (`--setting-sources user`, an MCP configuration of the
runner's). An unrestricted `claude` that someone starts later in the
same clone asks no question, though, and loads the clone's
`.claude/settings.json` hooks and `.mcp.json`, including ones an agent
wrote into the clone. In the `single` layout the file is the operator's
own Claude Code configuration, chosen by the rule above. A Claude Code
configuration directory per placement would avoid this (the rejected
alternative below). The maintainer accepted the scope as a known limit on
2026-11-09, with one rule: do not start your own `claude` in a runner
workspace.

**Reason:** the placement is the owner's trust decision, made before the
runner starts anything. Without the entry, every placement in a fresh
clone sat at the question while the runner reported `running`. A start
that fails with a cause is better than that.

**Rejected alternatives:**
- Answering the question in the pane with tmux keys: it reads a screen
  whose wording can change, and types into a session the agent then owns.
- A Claude Code configuration directory per placement
  (`CLAUDE_CONFIG_DIR`, as Codex gets its own home): the operator's
  login and the session history live there, so it is a larger change
  than the trust record the card asks for. It is also the alternative
  that would keep the trust inside the placement: an unrestricted
  `claude` in the clone would still ask.
- One entry for the workspaces root: in 2.1.319 the lookup walks up from
  the working directory only as far as the git root, so a parent entry
  is not read for a clone, and it would trust every later clone too.
- Writing the file without the lock: a session saving at the same time
  could drop the entry, or lose its own change.
- A mechanism that also closes the window between the ownership check
  and the replace: the lock has to work with Claude Code's own saves,
  which use proper-lockfile (`mkdir`, mtime, `rmdir`), so a kernel lock
  would not exclude them, and proper-lockfile has the same window. The
  window needs a writer frozen past the stale time, a scheduling fault
  rather than normal operation; the project lead accepted it (#1560 R2).
- A token file inside the lock directory to mark the owner: a runner
  that died while holding it would leave a directory `rmdir` cannot
  remove, and Claude Code's saves would then never get the lock again.
  The renewed mtime is how proper-lockfile itself tells its own lock.
- Starting anyway when the entry cannot be written: the session waits at
  the question and passes for `running`, the failure this fixes.

## The runner tells the agent's resume it is supervised through `MAITY_SUPERVISOR`

**Id:** 2718b0d9-cf5b-4758-9fca-a143fafce1d3
**Type:** decision
**Status:** superseded
**Superseded by:** 8d425d7d-6b2f-4af0-92e1-d1bc9b1a10cd
**Evidence:** confirmed
**Source:** docs/api.md §15.11 (resume accepts `supervisor`); the coordinator's approval of the environment variable, 2026-10-23
**Revisit when:** the runner resumes on the agent's behalf instead of the agent's own `maity resume`, or a harness drops the session environment before the agent's commands run

`adapters.launch` puts `MAITY_SUPERVISOR=maity-runner/<version>` into every
session's environment, beside `MAITY_PLACEMENT` and `GIT_COMMON_DIR`.
`maity resume` sends it as `supervisor` when it is set. A value that is
not a runner's name is a usage error. A hub that refuses the field is
resumed without it, with a warning, as for `environment`.

**Reason:** the agent runs its own `maity resume`, so the runner cannot
put the field into that call itself. The environment reaches every
command of the session without the agent having to do anything. A flag
would be one more thing the agent has to type correctly in every
session, and an agent that forgot it would be treated as unsupervised:
it would be told to `maity wait` under a runner that already wakes it.

**Rejected alternatives:**
- A `--supervisor` flag on `maity resume`, carried by the start prompt:
  it depends on the agent typing it, and a compaction loses it.

## The runner tells the agent's resume it is supervised through `MAITY_SUPERVISOR`

**Id:** 8d425d7d-6b2f-4af0-92e1-d1bc9b1a10cd
**Type:** decision
**Status:** superseded
**Superseded by:** 497f16bd-9dc7-4aca-b4d2-b3055c782410
**Evidence:** confirmed
**Source:** docs/api.md §15.11 (resume accepts `supervisor`); the coordinator's approval of the environment variable, 2026-10-23; the card "cli: remove the compatibility layers for old states and hubs" (tsk-hg1jm7e8233n)
**Revisit when:** the runner resumes on the agent's behalf instead of the agent's own `maity resume`, or a harness drops the session environment before the agent's commands run

`adapters.launch` puts `MAITY_SUPERVISOR=maity-runner/<version>` into every
session's environment, beside `MAITY_PLACEMENT` and `GIT_COMMON_DIR`.
`maity resume` sends it as `supervisor` when it is set. A value that is
not a runner's name is a usage error. A hub that refuses the field fails
the resume (commands.md aba45d60).

**Reason:** the agent runs its own `maity resume`, so the runner cannot
put the field into that call itself. The environment reaches every
command of the session without the agent having to do anything. A flag
would be one more thing the agent has to type correctly in every
session, and an agent that forgot it would be treated as unsupervised:
it would be told to `maity wait` under a runner that already wakes it.

**Rejected alternatives:**
- A `--supervisor` flag on `maity resume`, carried by the start prompt:
  it depends on the agent typing it, and a compaction loses it.
- Resuming without the field when a hub refuses it (2718b0d9): it
  served hubs from before §15.11, which no longer exist.

## The allowlists are no boundary in `single`; in `agent_user` the OS user separates the runner from the agents, not the agents from each other

**Id:** b2cbf1a7-e25c-4803-8bc4-845c488512fc
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** runner.md 2bdc5809 (the allowlists as an accident guard, not a boundary), whose Revisit-when fired with the `agent_user` layout (R7a); runner.md 3edc329a (everything on the agents' side belongs to one agents' user); the review of the open needs-review entry, 2026-10-23
**See:** runner.md — 3edc329a-6a10-427d-a0a3-733127f14b20 — as of 2026-10-23
**Revisit when:** a run with a real second OS user confirms or refutes the separation (3edc329a: not yet done), one OS user per agent is introduced, or the Kubernetes backend makes the pod the boundary

The named `git` subcommands and the denied options and paths of
2bdc5809 stay what they were: they stop accidents and naive prompt
injection, and nothing more. Whether a boundary exists behind them
depends on the layout.

- `single`: none. The agents run as the operator's user. Any repository
  code an allowed build or test command runs can read what that user
  reads, the clone's credential and the runner's state included. An
  agent with a shell is as trusted as the operator's account.
- `agent_user`: the OS user is the boundary between the runner and the
  agents. The runner's state directory, its credential and its records
  belong to the runner's user and are out of the agents' reach. Between
  the agents it is not a boundary: they share one user, so one agent's
  repository code can read another agent's clone, socket and log. Only
  the sandbox read denies (3edc329a) keep the other clones' credentials
  out of a sandboxed command, and only where the harness sandbox is on.

**Reason:** the old entry stated "no boundary until agents run as their
own user". With `agent_user` that is half true: there is now a user
between the runner and the agents, but not between the agents. Leaving
it at "needs-review" left both halves unsaid. Evidence stays inferred:
the separation follows from file ownership and sudo, but no run with a
real second user has shown it yet.

**Rejected alternative:** marking 2bdc5809 active again as it stands.
It would claim that `agent_user` gives no boundary, which the runner's
own state contradicts, and it would say nothing about the agents among
themselves.

## Workspaces are keyed on the project id

**Id:** e4efe327-6cb4-4ec7-bb95-354d6253b18e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card "cli runner: project full_name in placements, config and workspace paths" (§6.25); the arbiter's ruling of 2026-10-27 on this agent's proposal, contract PR #444 (`project_id` and `project_aliases` in the runner's placement view)
**Revisit when:** the hub moves a project's clones itself, or a project's id can change

A clone lives at `<workspaces>/<project_id>/<clone>`, and the tmux
session is `maity_<project_id>_<clone>`. A placement must carry a full
name, a `project_id` that is a path token, and only full names in
`project_aliases`. Otherwise it is dropped like any malformed placement.
`limits.projects` takes full names only, and a placement passes when its
current name or one of its aliases is listed. Taking over a clone from
before the namespace in place, through a `legacy_slug` in its record, was
removed on 2026-11-01: the maintainer stated that no runner was ever set
up on production, so no such record exists, and the alpha rule keeps no
compatibility layer.

**Reason:** the full name changes with a rename or a transfer (§6.25). A
directory keyed on it would send the next pickup of the same placement
into an empty clone, and the agent's credential, which lives in the
clone's Git directory, would be left behind. The id never changes. A
bare slug in the
operator's config would admit every owner's project with that slug.

**Rejected alternatives:**
- Keying on the full name (`<owner>_<slug>`, this agent's first draft):
  lost at every rename and transfer.
- Reading a bare slug in the config as "any owner": an operator who
  allowed `shop` for one owner would run every owner's `shop`.

## Local mode: one agent in the foreground, no pairing, also on Windows

**Id:** dd77eab8-46a3-45dd-9f08-bde11f926942
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-qe0ka9e341gh, the lead's assignment of 2026-11-03; the reviews of #1294 (pmwg, dzse), lotse's request for a state table (2026-11-03); the review lead's scope decision for #1294 of 2026-11-03 (only the parts settled across reviewers, the run's lifetime to card tsk-3tzhegcrr48h); the review lead's order of 2026-11-03 for the next fixes (pmwg, dzse on 83b3a7ca); the review lead's order of 2026-11-03 for the fixes on 6b564a86 (nyh5, dzse); the manager's order of 2026-11-03 for a last text round on 9ebbdcd1 (wtwy; dzse, nyh5); the manager's order of 2026-11-03 for a text round on 1a77bbdc (wtwy; dzse); `docs/api.md` §15.13, §5.3
**See:** credentials.md — 116c5330-8dab-42ed-af06-74b6f02cee89 — as of 2026-11-03
**See:** runner.md — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-03
**See:** runner.md — c2acd907-0f26-4850-8272-063390f1d6a7 — as of 2026-11-03
**Revisit when:** a harness signals its provider limit; someone asks local mode for an interactive session; the deny rules or a harness's sandbox are verified on Windows; the hub should tell a stopped local session from a busy one; card tsk-3tzhegcrr48h settles how a run that outlives local mode is found and taken over

`maity runner <harness> --join <url>` redeems the link into a new workspace
under `<state home>/maity-local/<link host>/<handle>`, lets the agent's own
`maity join` write the credential into its `.git/maity`, and runs the
supervised loop in the foreground. The next run starts only when an event
waits or the last run left its work unacknowledged, with the full runner's
restart defaults. It stops on a signal, Ctrl-C, Ctrl-Break or a closed
console; on Windows a Job Object takes the harness with it. It is the one
`maity runner` command that runs natively on Windows.

The join runs once into a private staging workspace beside the target,
followed by local mode's own supervised `maity resume`, which stores the
instance id; then the staging workspace is renamed to `<handle>` or, when
that already holds a credential, to `<handle>#<instance>`; if that cannot
be done, it stays as a complete workspace and its path is printed. A
non-empty `--workspace DIR` is refused untouched. Path components get one
`_` in front when they would be a Windows device name, end in `.` or a
space, or start with `_`, on every OS. A harness without a command
allowlist (`codex`) refuses `--allow`. The one Git fetch and checkout
run with the runner's transport list (https and ssh) in the staging
workspace, before the rename, so a workspace appears only complete. Only
after both exit 0 does local mode write `.git/maity/checked-out`, and only
a workspace with that file gets a harness. One with a credential but
without it (`repository_refused`, `no_repository`, `fetch_failed`, a
partial checkout, a crash) gets a retry: a fresh staging directory beside
it, only the regular files of `.git/maity` copied over, then the old one
renamed aside to `.replaced-<time>-<name>` and kept whole, and the fresh
one renamed into its place (for a kept `.join-*`, to
`<handle>#<instance>`). Git never runs in a directory that existed
before that start, and nothing in it is deleted. For an IPv6 host the
directory always carries the port, so `[::1]:80` and `[::1:80]` differ.

One lock per workspace path, `maity-local/.locks/<key>`, keyed like the
adapter files, is taken before anything in the workspace is read and
held until local mode exits, across both renames and the harness's
start; a start that finds it held is refused at once. The key takes
every component as its parent's listing names it, so two spellings on a
file system that ignores case, or an 8.3 short name, take one lock.
Only local mode holds it: the descriptor is never inherited, so it lasts
as long as local mode. At most one harness per path is guaranteed only
while local mode lives; a run that outlives a crashed local mode (the
harness on macOS, its descendants on Linux) and a start that takes the
path over meanwhile are not covered yet and are card tsk-3tzhegcrr48h;
until then a person who restarts after a crash (a `kill -9` or the OOM
killer) first checks that no process still works in the workspace
(`lsof +D` on Linux and macOS).
Every use of `.git/maity`, local mode's and that of every
`maity` command in a local-mode session, opens the workspace, `.git` and
`.git/maity` without following a link and refuses any link, junction or
hard-linked file (`workspace_link`). The retry copies the credential
into the fresh directory first and resumes there; from the first file
copied, the fresh directory counts as possibly holding a secret. The
fresh directory gets a `retry-of` mark first, naming the one path it
may run at: the old one's, or for a kept `.join-*` `<handle>#<instance>`
once its resume named the instance, and the old one gets a mark naming
its own path before it is moved aside. A start anywhere else is refused
(`retry_leftover`) every time, so at any one time only the copy at that
path starts. That holds at a moment, not over time: once a copy has
arrived its mark is removed, and when the person later moves it on, a
leftover that was not removed can be renamed onto the freed path and
start; the contract names that and does not cover it. The mark is
compared with the workspace by identity, not spelling, and removed once
the copy is at its path. When its path holds another instance or
nothing, the person may remove it by hand after checking that no other
copy of the credential exists; when it holds this instance, never. The
staging and the retry's fresh directory are printed when they are
created, the fresh directory with the path its mark names, which is
printed again when it is rewritten to `<handle>#<instance>`, and a
start names every `.join-*` beside it with what it holds. A `.replaced-*` directory is never started
(`workspace_replaced`); its time is `YYYYMMDDTHHMMSSZ`. §15.13 lists
the states of a workspace path in one table; each review finding maps
to a row (the one under `running` is named as the limit, not fixed):

- `replacing` and `between`: the lock released before the renames, so a
  second retry could move away the tree a harness had just started in
  (pmwg, dzse on `a228f3ea`).
- `kept`: a partial checkout taken as ready (pmwg on `a0b0e809`).
- `replaced`: the old workspace deleted with unique work in its `.git`
  (pmwg on `a0b0e809`).
- `staging` and `placing`: a marker for the destination left by a failed
  rename, and one a harness could forge (pmwg on `c629ded4`).
- `orphaned` and `stranded`: a complete fresh directory whose path nobody
  printed after a crash or a failed rename (dzse on `a228f3ea`).
- `placing` from a kept `.join-*`: a retried staging workspace that kept
  its random name (dzse on `a228f3ea`).
- Every row that reads a workspace: `.git/maity` swapped for a link to
  another workspace's, whose credential the retry would copy (dzse on
  `a228f3ea`), and the same swap during a run, which a check at the
  start alone missed: local mode's next `maity wait` would follow the
  link with the other agent's credential (dzse on `3d34a8a3`).
- `running`: a harness or its descendants outliving a killed local
  mode (macOS `kill -9`, Linux descendants), so the next start took the
  free lock and launched a second harness (pmwg on `3d34a8a3`). The
  answer on `1d09396a` (an inherited lock and a run record) left gaps
  (pmwg, dzse on `1d09396a`), so the contract now names this as its limit
  and card tsk-3tzhegcrr48h takes it up with those findings.
- `abandoned`, `unfinished` and `orphaned`: one `orphaned` row for every
  crash while the fresh directory is built, though only a complete one
  fits it (pmwg on `3d34a8a3`); and an `F` with only the credential's
  temporary file, which the leftovers called free of secrets (pmwg on
  `1d09396a`).
- `unfinished` and `orphaned` at `F`: a start in a retry's leftover
  while the original could still be started ran the same credential and
  instance in two workspaces, and the `unfinished` row promised a retry
  in an `F` without the credential, which the entry rule refuses (pmwg,
  dzse on `83b3a7ca`).
- `between`, `orphaned` and `stranded` at `F`: the gate let a leftover
  start whenever the original's path held no credential, which a
  second, successful retry leaves for a moment, and from a kept
  `.join-*` for good, so two copies ran one instance (nyh5, dzse on
  `6b564a86`); and a stale, forged or differently spelled mark refused
  every start of a workspace with no way out and advice to delete it
  (dzse on `6b564a86`).
- `staging` to `kept` after a crash: a staging directory with the spent
  credential that nothing named (dzse on `3d34a8a3`).
- Every row with a lock: two spellings of one path on a file system that
  ignores case took two locks (dzse on `3d34a8a3`), and a missing name,
  which has no stored spelling yet, could still take two through a
  `--workspace` under `maity-local` (dzse on `1d09396a`), also while
  `maity-local` itself did not exist yet (dzse on `9ebbdcd1`).
- `orphaned`, `stranded` and `replaced` at `F` and at `.replaced-*`: the
  one-copy claim read as holding over time, though a leftover can take
  the path once the copy there moved on; the way out read as removing
  any mark, also one whose path holds this instance, after checking only
  that no copy runs; the advice to rename onto an empty path followed a
  path a harness could have written; and the old tree, restored under
  another name, started beside the admitted copy (dzse on `9ebbdcd1`).
  The first is named as a limit; the others are fixed.

The harness gets a runner's adapter context: the adapter files outside
the workspace under `maity-local/.adapters`, no `MAITY_PLACEMENT`, the
hub's and the repository's hosts, the paths a runner denies, and the
sandbox `maity runner check` reports: Claude Code's strict sandbox on
Linux with `bwrap` and `socat`, else off and said so; Codex only with its
sandbox, refused without; opencode the allowlist alone.

The hub's not-listening rule leaves out a supervised session only while
an active placement names its credential, so a stopped local mode shows
as an agent that is not listening (built by tsk-mcd2xwwa2fzv in
`hub/src/maity_hub/not_listening.py`). Local mode also refuses a link
whose host is not a plain DNS name or IP address (`..`, `.adapters`, a
trailing dot), because the host names a directory under `maity-local`.

**Reason:** people who want one agent on their own laptop should not need
a paired runner, a service and a placement for it. Everything Windows
lacked for the full runner (tmux, systemd, OS users) belongs to `serve`;
a foreground loop needs a process group, which Windows has as a console
group and a Job Object. The not-listening rule left supervised sessions
out because their runner reports a stopped run (§15.7); local mode has
no runner to report it, so the exemption has to follow the placement, not
the `supervisor` value. Keeping the credential in the clone reuses the
private-directory checks as they are, and keeping the workspaces outside
the runner's state directory means `gc` and `workspace claim` cannot
touch them. The adapter files lie outside the workspace because Codex's
sandbox lets the agent write the clone's `.git`, and anything there
could be widened for the next run. The retry builds a fresh directory
for the same reason: with no Git in any existing workspace there is no
permission an agent could forge or a failed rename could leave behind,
and this holds where the sandbox is off or, on Windows, unverified, not
only where it denies paths. The mark says "ready", not "Git may run":
a test of the work tree cannot tell a partial checkout from a complete
one, since checkout is not atomic, and a forged or removed mark leads
only to a harness in a tree an agent already wrote or to a fresh clone.
The old workspace is moved aside, not deleted, because an almost empty
`.git` can still hold branches, objects and reflogs with unique work.
The lock lies outside every renamed directory because a lock inside one
guards the tree, not the path: once the tree is renamed, a second start
locks whatever new tree the path names, and Windows renames no
directory with an open file, so a lock inside had to be released before
the rename. Outside, nothing is released before the rename it guards,
and no check after taking it is needed. The lock is local mode's alone
and never passed on, because a descriptor the run inherits can be
closed or unlocked by any process of the run, which then frees local
mode's lock too. The run is what must be alone on a path, and local mode
can die without it (macOS has no parent-death signal, and on Linux the
subreaper dies with local mode), but each way tried in review to make
the lock outlast local mode left a gap: a run record written after the
harness started, and a path left unlocked between runs once a process of
the run had unlocked it. Rather than ship a guarantee with known holes,
the contract states the one it keeps, at most one harness per path
while local mode lives, and leaves the rest to card tsk-3tzhegcrr48h.
A copied credential's temporary name makes its final name atomic, not
the directory free of secrets, so the leftovers count any file in
`.git/maity` as a possible secret. A retry's leftover is gated, not
only warned about, because the table itself offered the start in it and
nothing about a duplicate instance needs a surviving run: two live
local modes on two paths are enough. The gate cannot ask whether the
original's path holds a credential, because a second, successful retry
empties that path for a moment, and from a kept `.join-*` for good,
while its own copy runs; it asks where this copy is instead, since a
path names one directory at a time, so at any one time only one copy can
be at the path the mark names. Over time the path binds a copy only until
it arrives: its mark is removed then, so that a workspace moved later is
not refused, and a leftover left beside it can follow onto the freed
path. Closing that would need local mode to know every directory a copy
was ever moved to, which it cannot, so the contract names the gap
instead of claiming more. The ways on for a mark whose path holds
another instance or nothing ask the person first to check that no other
copy exists; the ways that rename a copy to the path its mark names
(when that path holds this instance, `orphaned`, `stranded`) do not,
since the copy goes where the mark puts it. That is
also why a retry from a kept `.join-*`
goes to `<handle>#<instance>`, which the instance alone decides, and not
to `<handle>` when that happens to be free: every retry of one staging
workspace meets at one path. The mark is compared by identity, as the
lock's key is, because a name retyped in another case on APFS or NTFS
still names the same directory; it is removed once the copy is at its
path, so a workspace moved later is not refused. Local mode never moves
a leftover itself, because the mark is a file a harness can write, and
a forged one may only refuse its own workspace's starts; the way out of
a mark whose path holds another instance or nothing is the person's,
removing the file after checking that no other copy exists, not only
that none runs, since every copy that exists can be started. When the
path holds this instance there is no such way out: the copy there and
this one would both exist and start. The advice to rename a workspace
onto an empty path asks for the same check and only for the path the
retry printed for the mark, when it wrote it at the creation and again
when it rewrote it to `<handle>#<instance>`, since the path comes from a
file a harness can write, and local mode does not move workspaces to
such a path either. The old tree gets a mark before the retry moves it
aside, so restoring that `.replaced-*` under another name than its path
is refused like any copy. A `.replaced-*` the person makes by hand
carries no mark (the copy at the path lost its own when it arrived), so
restoring it under another name is not refused: part of the gap over
time, named, not covered.
Local mode creates `maity-local` before it decides whether a
`--workspace` lies inside it, because a directory that does not exist
yet has no identity to compare with. The message reads the instance at
the named path only to say which way on fits. The key comes from the listing
because only the name the file system stores is one per directory; the
parents' real path alone left the last component's case open. The
no-link opening is there because Codex may write `.git`, and a link
needs no read access to its target; it runs at every use because
local mode keeps using `.git/maity` after the harness has run, through
handles so nothing can be swapped between the check and the use. The
retry resumes against the fresh directory's copy because that one no
harness ever reached. Every directory that may come to hold a
credential is printed before it does, and starts name the leftovers,
because a crash prints nothing, and a person who does not find a spent
credential would redeem a spent link. The sandbox follows what the adapters
already do on a runner (Claude Code strict or not at all, Codex only
sandboxed), so local mode adds no third policy. Codex's sandbox is
required because without it nothing confines Codex at all, while Claude
Code without its sandbox still has its permission rules, which the start
message says are no boundary.

**Rejected alternatives:**
- A paired runner on the laptop: a runner credential, a row and a
  placement for one agent, and still no Windows.
- Restarting after every exit: an idle agent would spend model tokens
  on runs with nothing to do.
- `stub` as a local-mode harness: it is already the name of an internal
  action, so action names win and no harness id may take one.
- Picking `<handle>#<instance>` before the join: the instance id comes
  only with the single-use exchange (§3.3), so the second join would have
  to guess it or spend the link twice (review of #1294).
- The handle verbatim as a directory name: valid handles such as `con`,
  `nul` or `com1` are device names Windows refuses as directory names.
- Ignoring `--allow` for `codex`: the person would believe a restriction
  applied that nothing enforces (a runner, §15.3, leaves a grant's list out for Codex and names it in `maity runner check`, 79837674).
- "The hub needs no change", leaving supervised sessions out as before:
  a local mode stopped by Ctrl-C, a closed console or a crash would hold
  a session that never counts as not listening, and the lead would not
  learn of it (review of #1294).
- A supervisor value of its own (`maity-local/<version>`) that the hub
  treats as a self-waiting session: also a hub change, the `supervisor`
  pattern would have to widen, and the supervised wake set and rules
  would need a second name for the same behaviour.
- Configuration files for the restart values: the full runner's defaults
  serve one agent in the foreground, and a file would be one more thing
  to find, validate and document for a command meant to need none.
- A readiness marker in `.git` that permits Git, or recovering by just
  running the fetch again: the agent can write `.git/config` and its
  hooks, so a later start could not tell a never-launched workspace from
  one a harness changed (review of #1294, pmwg). The `checked-out` mark
  permits only the harness, never Git.
- Reading "no checkout" from the work tree (nothing but `.git`, `HEAD`
  on an unborn branch): a failing required smudge filter leaves files
  and an unborn `HEAD`, so a partial checkout passed as ready (review of
  #1294, pmwg).
- Removing the old workspace after copying `.git/maity`: an unborn
  `HEAD` does not mean the rest of `.git` holds no unique work (review
  of #1294, pmwg).
- A pending record under `maity-local/.pending` that permits the one Git
  and its retry: a failed rename could leave one for another join's
  workspace, and where the sandbox is off a harness could recreate it
  and get Git run after it changed `.git/config` (review of #1294, pmwg,
  dzse). Exclusive creation fixes the first, nothing fixes the second.
- `_<port>` only when the link names one, for IPv6 too: `[::1]:80` and
  `[::1:80]` would both be `___1_80` and share a workspace (review of
  #1294, dzse, pmwg).
- The adapter files in `<workspace>/.git/maity`: writable from Codex's
  sandbox, so a run could widen the next run's settings.
- `--code` on the command line, as `maity join` has it: on Linux every
  user can read another's command line, and could redeem the link first.
- A process-id lock file: after a `kill -9` it stays, and a reused id
  would block the workspace for good; an operating-system lock ends with
  its process.
- The lock in `.git/maity/local.lock`, released before the renames and
  checked against the path after taking it: the check sees only renames
  before it, so a retry could still move away a tree a harness had just
  started in (review of #1294, pmwg, dzse).
- Waiting for a held lock: two starts each holding one lock and waiting
  for the other's would never end; a start refused at once can be run
  again.
- Following links in `.git` as before: an agent could point
  `.git/maity` at another workspace's (review of #1294, dzse).
- The no-link check at the start only: the harness can swap
  `.git/maity` during a run, and local mode's next `maity wait` runs
  outside any sandbox (review of #1294, dzse).
- The harness inheriting the lock, so it lasts as long as the run, and a
  run record under `maity-local/.runs` that refuses a start
  (`harness_running`) while a recorded run lives: the record came only
  after the harness had started, so a run that unlocked what it inherited
  left a window without lock or record, and after a run the path stayed
  unlocked while local mode waited, so a second local mode could take it
  over (review of #1294, pmwg, dzse). Moved to card tsk-3tzhegcrr48h with
  those findings and the proposals made (a launch gate, a second lock
  file only the harness inherits); this contract keeps only the
  guarantee while local mode lives.
- The lock keyed by the directory's inode: it would follow the tree
  through the renames, which is what the path lock replaced.
- Only the parents resolved, and `normcase` on Windows: two spellings of
  the last component on APFS, or an 8.3 short name, took two locks
  (review of #1294, dzse).
- One `orphaned` state for every crash while the fresh directory is
  built: an incomplete one cannot be started, and one without a
  credential holds nothing to recover (review of #1294, pmwg).
- Naming a start in a retry's leftover as one more limit: the table
  would still offer a start that runs one agent instance twice, with no
  run outliving local mode needed (review of #1294, pmwg, dzse).
- Case-folding a missing name for the lock's key: local mode cannot
  tell whether the file system will ignore case, and folding everywhere
  would give two real directories on a case-sensitive one one lock;
  refusing a `--workspace` under `maity-local` with `--join` leaves only
  names local mode spells itself (review of #1294, dzse).
- The gate only while the original's path holds a credential (as on
  `6b564a86`): a second, successful retry leaves that path empty in its
  rename window, and from a kept `.join-*` for good once its copy runs
  at the handle, so a leftover started beside it (review of #1294,
  nyh5, dzse).
- Taking the original path's lock in that gate as well: it closes the
  rename window but not a staging workspace's copy that already runs at
  its handle (review of #1294, nyh5, dzse).
- Local mode renaming a leftover into its mark's path itself, with
  `RENAME_NOREPLACE` (proposed in review of #1294, dzse): the mark is a
  file a harness can write, so local mode would move a workspace,
  credential included, to a path an agent chose, outside any sandbox.
  The person's rename is as safe, since a path names one directory at a
  time and the start checks what it finds there.
- Refusing only while the named path holds the same instance (proposed
  in review of #1294, dzse): another instance there says nothing about
  where the other copies run; the instance only picks the message's
  advice.
- Comparing the mark by spelling: a name retyped in another case on
  APFS or NTFS refused the workspace itself at every start (review of
  #1294, dzse).
- A retry from a kept `.join-*` to `<handle>` when that is free: a copy
  that crashed after picking it and a later retry that found it taken
  would end on two paths.
- Refusing a copy's arrival while a leftover beside the path holds its
  instance and names that path (proposed in review of #1294, dzse): it
  sees only leftovers beside the path, never a copy moved elsewhere, so
  the one-copy claim would still not hold over time; the contract names
  the gap and asks for the check before every rename onto a path.
- Removing the mark as the way out of every mark that does not fit (as
  on `9ebbdcd1`): with this instance at the named path, both copies
  would start (review of #1294, dzse; the manager's order).
- Checking only that no other copy runs before removing a mark (as on
  `9ebbdcd1`): a copy that is not running now can be started later
  (review of #1294, dzse).

## Under the runner, maity's own git runs only in the runner's clone, and only while it is plain

**Id:** b4a8030d-3b24-4b76-81cc-a84b0ca84c11
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** CLI hardening task, the boundary and the clone root chosen by the coordinator, 2026-11-04; a prefixed `maity` call (a command, a variable, `PYTHONPATH`, PATH before it) checked with Claude Code 2.1.318 and git 2.47.3 on the maintainer's laptop, 2026-11-04 (`claude -p` in a temporary clone with the runner's settings, no hub; markers in a `denyWrite` directory): refused by the runner's permission rules, kept in the sandbox with permissions open, and `excludedCommands` matched the plain command only; a placement refused at its next start over `.git/config.worktree`, 2026-11-10, and the lead's choice to accept the sandbox's placeholders while empty, with the runner deleting nothing in the clone, 2026-11-10; Claude Code 2.1.321's sandbox (bubblewrap) leaving them in a scratch clone, 2026-11-10 (`ls -la .git` of a plain clone of the same repository before, of the clone after a session that wrote none of them); the `.git/glab-cli`, `.git/modules` and `.git/worktrees` guards read in the list of protected paths of Claude Code 2.1.321's binary and seen empty after every session start with 2.1.323 on the runner's host (tsk-ydxv7x37fg08, 2026-11-13); card tsk-estwtzbae972 (an empty `.git/config.lock` the sandbox holds to keep `.git/config` unwritable, which refused a placement's own `maity report`/`checkpoint`; the lock's mechanism confirmed by `test_adapters.py` and `test_session_identity.py`, which leave an empty `config.lock`), 2026-11-18; PR #1954 review, 2026-11-18, correcting the reason: git never reads, adopts or commits a pre-existing `config.lock` (it writes `.git/config` through a lock it creates itself with `O_CREAT|O_EXCL` and renames only that one into place), so refusing a non-empty lock is a fail-safe default — accept only the known-inert placeholder shape — not a guard against git applying the lock; card tsk-rasfq0wt751a (security rating S226), 2026-11-20: one helper decides whether a session is placed, an empty or malformed id refused
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-04
**See:** report.md#what-maity-hands-to-git-and-gh-is-checked-first-and-gits-transports-are-fixed — 4f4e8ada-9e3b-47bc-8a9e-d44daf025512 — as of 2026-11-04
**Revisit when:** agents under the runner need a git configuration key a plain clone has not, the runner starts sessions without `GIT_COMMON_DIR` or `.git/maity`, someone needs submodules, Git LFS, worktrees, sparse checkout, partial clones or other repository format extensions under the runner, a maity command under the runner starts to show what git reads from the clone's objects to someone other than the agent, a sandbox stops denying the agent `.git/maity` or leaves other entries in a clone, or puts anything in the ones it leaves, maity's git under the runner needs to write, a harness's sandbox starts maity outside it when a command line sets variables or a PATH in front of it, or the runner's git moves after a session started

In a session the runner started (`MAITY_PLACEMENT` set), every git
maity itself starts first checks the clone the same way `gc` does
(`clonecheck.not_inspectable`, moved out of `runner/operate.py` so both
use one check): a `.git` made only of a plain clone's entries, a
configuration made only of a plain clone's keys, as git itself reads
that configuration (`git config --file -` on the bytes, includes off,
no other configuration), checked by section, subsection and key, so a
remote or branch name may hold a dot, and the keys git for Windows
writes on a clone are a plain clone's too. The clone is the
parent of `GIT_COMMON_DIR`, which the runner sets. Without it, or when
it does not resolve, maity runs no git; it never falls back to the
current directory. The current directory must lie inside that clone.
git then does not read the clone's `.git` for its configuration, HEAD or
refs: each run gets a repository maity writes under `.git/maity`, with
a configuration of maity's own. For Claude Code, whose sandbox maity
runs outside of, the sandbox denies the agent that directory. For
Codex, maity runs inside the sandbox, where `.git/maity` is writable
and `.git/config` read-only: maity's git there has the agent's own
rights, so nothing is gained by racing it. The clone's entries the check accepted reach git through
`GIT_CONFIG_*`, from the same reading the check made; HEAD and the refs
are copied as regular files only. Objects, the index and the work tree
are the clone's (`GIT_OBJECT_DIRECTORY`, `GIT_INDEX_FILE`,
`GIT_WORK_TREE`, `GIT_CEILING_DIRECTORIES`), and `GIT_OPTIONAL_LOCKS=0`
keeps `status` from writing into the clone. git reads no system or
global configuration (`GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL` at a
missing file), so HOME reaches git without its `.gitconfig`; maity's own
git under the runner only reads and needs none. The git maity starts
is the one the runner found on its own PATH and recorded beside the
marker (`.git/maity/git`), not one the PATH of maity's command line
picks; without that record maity runs no git there. The same git parses
the configuration for the check. git gets a fixed environment: HOME,
LANG, TMPDIR (on Windows what a program needs to start), a PATH of
git's own directory and the system's, the prompt switches and the
`GIT_*` values maity sets itself. On POSIX, what the command line that
started maity sets reaches git only through HOME, LANG and TMPDIR, none
of which names a program git starts or a configuration it reads: the
ignore and attributes files git would read under HOME point at a missing
file. On Windows (local mode, no Claude Code sandbox) the variables a
program needs to start pass on as well; `SYSTEMROOT` and the PATH come
from the system, not from maity's environment. The directory is removed after the run. On Windows (local mode), where a directory cannot be
opened and read from, each ref is checked with `lstat` before it is
read. A refused clone gets the way back: undo the change, a setting
with `git config --unset-all`. Submodules, Git LFS, worktrees and sparse
checkout are refused under the runner for the alpha, and the refusal
says so instead of offering a way back. The runner writes a marker,
`.git/maity/placement`, into each clone it starts an agent in; a marked
clone without `MAITY_PLACEMENT` runs no maity git, since the variables
were removed, not never set. Set, even empty, `MAITY_PLACEMENT` means a
placed session (`clonecheck.placed`); a value that is not a placement id
(`clonecheck.placement_id`, the pattern the supervisor checks, as a full
match) is a placed session of unknown identity and runs no maity git
either, never one read as unplaced (card tsk-rasfq0wt751a). That holds for each way git finds a
repository: a directory at or above the current one, a `.git` file
pointing elsewhere, `GIT_DIR` or `GIT_COMMON_DIR` (a `.git` file that
`GIT_DIR` names too), each followed through a `commondir`; read as
files, without git. The state lookup goes the same
way. A `.git` of more than 20 000 entries is
refused before it is all listed, inside one wide directory too: the
listing stops one entry past the cap. The state directory under the runner is the
clone's `.git/maity`, taken from `GIT_COMMON_DIR`, not from git, so a
refused clone still reaches its credential. A sparse checkout set up by
git is named as one, though git writes `config.worktree` with it, and a
partial clone by its remote's `promisor` and `partialclonefilter`, which
`git clone --filter` writes instead of an `extensions.` line. The check lists `.git` on
every run (about a quarter of a second at 10 000 entries); it is not
cached, since the clone may change between two runs, and the cap keeps
it bounded. git that gh starts
is not maity's and is not checked. Outside a placement nothing changes.

A clone Claude Code's sandbox ran in holds entries a plain clone has
not: an empty `config.worktree` and `objects/info/alternates`, an empty
`remotes/`, and empty `.claude-sandbox-noreplace/` directories (in
`info/`, `objects/info/` and `objects/info/commit-graphs/`). The
sandbox leaves them to guard the paths it protects; no command of the
session wrote them. The check accepts, while empty, a little more than
those six: an empty `config.worktree`, `objects/info/alternates` or
`objects/info/http-alternates` file, an empty `remotes/`, and an empty
`.claude-sandbox-noreplace/` directory wherever it appears in `.git`,
not only in the three places observed. It also accepts an empty
`glab-cli/`, `modules/` and `worktrees/`. Claude Code's binary lists
`.git/glab-cli`, `.git/modules` and `.git/worktrees` among the paths its
sandbox protects (read in 2.1.321), and on the runner's host 2.1.323 made
`glab-cli/` and `worktrees/` empty at every session start, so every
placed session refused its own clone for `maity checkpoint`, `report`
and the next start (tsk-ydxv7x37fg08). `modules/` is accepted from the
list without having been seen: it is the same guard, and the check
should not hang on which of the listed paths one release happens to
make. With anything in them, `modules/` is refused as submodules and
`worktrees/` as worktrees, as before. Empty means an empty regular
file or directory: a symbolic link, a FIFO, a socket or a device anywhere
in `.git` is refused, under any name, and so is a directory in `.git` that
cannot be listed, since unlisted it would look empty. Any of them with
something in it is refused as before. A known boundary: the check reads
each entry by type and size, not by ownership or link count, so a 0-byte
hard link to a file outside the clone passes in a placeholder's place the
same as an empty regular file would — a hard link is a regular file to
`lstat`, and git never reads these placeholders (it never reads
`config.lock`, an empty `config.worktree` is read only under an
`extensions.worktreeConfig` the check refuses, and an empty `alternates`
names no store), so a 0-byte hard link in their place changes nothing git
does. This is an accepted, understood boundary, not a hole. This
holds for every maity user, not only the runner. Empty, they change
nothing git does: an empty `config.worktree` is not even read without
an `extensions.worktreeConfig` the configuration check refuses, an
empty `alternates` names no object store, and an empty `remotes/` names
no remote, and empty `glab-cli/`, `modules/` and `worktrees/` hold no
glab configuration, no submodule and no linked worktree. The check also
accepts, while empty, a `config.lock`: Claude Code's sandbox holds an
empty, read-only `.git/config.lock` so that `.git/config` stays
unwritable — it is the lockfile git makes to write `.git/config`, and
holding it means every such write fails ("could not lock config file"),
which is how a sandboxed session is kept from changing `.git/config`
(seen in `test_adapters.py` and `test_session_identity.py`, which leave
an empty `config.lock` for the sandbox that "keeps `.git/config`
unwritable"). git never reads, adopts or commits a pre-existing
`config.lock`: it writes `.git/config` through a lock it creates itself
with `O_CREAT|O_EXCL` and renames only that one into place, so the lock's
content never reaches `.git/config`, and blocking git's own writes is the
lock's only effect — one that does not matter in a sandboxed clone.
Without accepting the empty lock, a placement whose session ran sandboxed
refused its own `maity report` and `checkpoint` over it (tsk-estwtzbae972).
A non-empty `config.lock` is refused as before — not because git would
apply it, but as a fail-safe default: the check accepts only the shape
the sandbox is known to leave, an empty regular file at that path, and
content is not a form the sandbox ever creates.

**Reason:** under the runner, maity's git runs outside the agent's
sandbox for Claude Code (inside it for Codex), in a clone whose
configuration the agent writes. The pinned
settings on maity's command line cover the settings known to matter;
the plain-clone check covers what is not enumerated, as it already does
for `gc`. Only the runner can say which clone is the agent's, and it
says so through `GIT_COMMON_DIR`; the current directory could be any
repository the agent made. The agent works in the clone while maity
runs, so a check followed by git reading the clone's own configuration
leaves a window in which that configuration changes; git reading only
what maity wrote closes it for what git runs. Objects stay the clone's,
read where the agent can write: a redirect to another object store
placed there after the check is followed, which is data git reads, not
a program it starts. maity's own git under the runner only reads, so
every call can run that way.

**Rejected alternatives:**
- The runner deleting the sandbox's placeholders before a start: the
  runner changes nothing in an agent's clone, and the sandbox makes them
  again on the next session.
- Accepting those names whatever they hold: a `config.worktree` or an
  `alternates` with content changes what git reads. Only the empty ones
  are known to be the sandbox's.
- Deleting the sandbox's `config.lock` before a start: as with the other
  placeholders, the runner changes nothing in an agent's clone, and the
  sandbox makes the lock again on the next session.
- Accepting any `config.lock` content (tolerating a non-empty lock): git
  never reads, adopts or commits a pre-existing `config.lock` (it writes
  `.git/config` through a lock it creates itself with `O_CREAT|O_EXCL`
  and renames only that one into place), so content in the lock is not
  configuration git would apply; but content is not a form the sandbox
  creates either, so tolerating it would widen the check past the
  known-inert placeholder shape for no gain. The empty lock is the only
  form accepted, a fail-safe default.
- Passing maity's own environment on to git: a variable set on the
  command line that starts maity names programs for git as well as the
  configuration does.
- Trusting a missing `MAITY_PLACEMENT`: removing it is all an agent
  needs to reach git without the check.
- Reading an empty `MAITY_PLACEMENT` as unplaced, as `os.environ.get`
  did at some sites while others tested only that it was set: there an
  empty value took the unplaced path, the runner's own, with no
  placement root, while a malformed one counted as placed (card
  tsk-rasfq0wt751a).
- Looking for the marker only from the current directory upward: a
  `.git` file or `GIT_DIR` elsewhere leads git to the marked clone all
  the same.
- Starting the git on the PATH of maity's command line, or passing that
  PATH on to git: whoever sets that command line picks the program.
- A variable naming the runner's git: the command line that starts maity
  sets variables too; a file in `.git/maity` is the runner's.
- Checking the clone, then pinning git to its own `.git`: the
  configuration can change between the check and git's read of it.
- The private repository in a temporary directory: the sandboxed agent
  may be able to write there, and the window would move with it.
- Copying the checked configuration file into the private repository:
  the file maity copies is again one the agent wrote.
- maity's own reading of the configuration's lines: git reads a header
  and a key on one line, where a line-by-line reading sees one key, so
  the check and git disagreed on what the file sets.
- The same check outside the runner: a person's own clone carries
  aliases, `pull.rebase` and other keys a plain clone has not, and
  `maity report` would refuse in ordinary use, where the person's own
  git reads that configuration anyway.
- The clone found from the current directory when `GIT_COMMON_DIR` is
  missing: that is the directory the check cannot vouch for.
- A copy of the check in the CLI beside the runner's: two lists of
  allowed keys drift apart.

## A placement's leftover subagent worktree is removed, not tolerated, and only when it is the clone's own

**Id:** a01035af-a4c1-4ab7-83a7-91670439fa50
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-gqk2gdxb4g73, 2026-11-19 (a Claude Code subagent's worktree-isolation leaves a git worktree at `.claude/worktrees/agent-<id>` inside the placement's clone, which registers its admin data so the clone reads as unsupported — "Worktrees are" — and refuses `maity report` and the next start before git runs; inside the harness sandbox the agent can remove neither the worktree nor `.claude/worktrees/*`, a protected path, so without help a session is stuck until a person cleans the host; a current Claude Code empties the worktree registration at session start, but a worktree a subagent makes mid-session lasts that session); the dispatcher's decision to remove rather than tolerate (option (a) over (b)), 2026-11-19
**See:** runner.md#under-the-runner-maitys-own-git-runs-only-in-the-runners-clone-and-only-while-it-is-plain — b4a8030d-3b24-4b76-81cc-a84b0ca84c11 — as of 2026-11-19
**Verification:** corroborated
**Revisit when:** the clone check starts tolerating a present worktree, a harness places a subagent's worktree somewhere other than the clone's own `.claude/worktrees/`, in-session self-service clearing of a leftover worktree is required, or the runner starts running git in an existing clone for anything

The clone check stays strict: a present worktree is unsupported, and the
check is not widened to tolerate one. The leftover is removed instead, by
one path only — the supervisor's prune on every placement (re)start — scoped
to this clone's own `.claude/worktrees/` and leaving a worktree that points
anywhere else exactly where it is.

The supervisor clears a leftover on every placement (re)start, before the
clone check would refuse it, and only after it has confirmed the clone is
this agent's own (a clone another agent or a person holds hits the in-use
refusal untouched, before anything is pruned). It runs no git — the runner
runs no git in an existing clone, which would run the agent's code as the
runner — so it removes by file operations only, each directory opened from
the one above without following a link, touching only a registration whose
working tree is, by name, this clone's own `.claude/worktrees/<id>`: the
working-tree directory itself, or a registration left dangling once that
working tree is gone, which has nothing to lose. A link on the way, a
non-directory planted in the working tree's place, and a registered worktree
pointing out of the clone, are all left — the last keeps a planted redirect
refusing the start. Having no git it cannot read whether a leftover holds
uncommitted changes, so a restart's prune discards whatever is in the
leftover worktree, including work a
subagent did not merge; there is no in-session save, and a leftover found at
a start is a past session's, with nobody to ask.

When the clone check refuses over a worktree under `.claude/worktrees/`, the
refusal tells the operator a restart clears it — but only when there is such
a leftover to clear: a worktree pointing elsewhere is genuinely unsupported
and offers no way out.

**Reason:** keeping the check strict and removing the worktree is narrower
than tolerating a present one. A worktree changes where git reads — its own
`HEAD` and index, a per-worktree configuration the main configuration does
not have — so tolerating one would reopen across worktrees exactly what the
check closes for the main clone. Pruning at placement start needs no git and
runs before the agent session, so no git ever runs in a clone that still
holds a worktree's agent-influenceable metadata. What makes the removal safe
is its scope: only a registration whose working tree is, by name, directly
under this clone's `.claude/worktrees/` is touched — its working-tree
directory, or a dangling registration whose working tree is already gone and
so has nothing to lose — with no link followed on the way; a link or a
non-directory in that place, and anything else, is left.

**Rejected alternatives:**
- Tolerating a present worktree in the clone check: relax the check so a
  `.git/worktrees` with content, or a per-worktree configuration, no longer
  refuses. Rejected because that widens what git may read for every clone
  and every command, across worktrees whose own `HEAD`, index and
  per-worktree configuration the main check never saw — the opposite of the
  strict posture the check exists for. Removing the one leftover keeps the
  check as it is.
- An agent-callable in-session remover that runs `git worktree` against the
  clone while the session is live, keeping uncommitted work behind an
  explicit `--force`. Rejected before the freeze: it would run git inside a
  clone that still holds a worktree's agent-influenceable metadata — a
  surface the runner has not taken on, since the whole clone check exists so
  maity runs no git in a clone an agent wrote. Pruning at placement start
  needs no git and runs before the agent starts, so the leftover is cleared
  without ever running git in such a clone. The cost is that a restart
  discards the subagent's uncommitted work, which is acceptable for a
  leftover a past session left with nobody to ask; a live, work-preserving
  self-service remover is left for later, if in-session self-service is ever
  required.
- The supervisor running git to clear the worktree: that is git in an
  existing clone, which runs the agent's code as the runner — the invariant
  the whole clone check rests on.

## maity takes the clone's `.git` only as the directory the runner recorded

**Id:** e44249f8-15d0-4104-8940-5ff48decd412
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of #1663, round 5 (a `.git` exchanged with a decoy under bwrap with the runner's deny list); review of #1683 (a learned private name and a decoy's clean filter under bwrap); reproduction on main 5abda036 for tsk-er1nymh4te1h, 2026-11-12: a decoy `.git` whose `maity/git` named a script made maity run it outside the sandbox (7 calls on `maity checkpoint`'s path); under Claude Code 2.1.322's own sandbox `mv .git` failed with EBUSY, because Claude Code bind-mounts the clone's `.git` itself
**See:** runner.md#under-the-runner-maitys-own-git-runs-only-in-the-runners-clone-and-only-while-it-is-plain — b4a8030d-3b24-4b76-81cc-a84b0ca84c11 — as of 2026-11-12
**Revisit when:** a harness's sandbox denies renaming the clone's `.git` through a setting the runner sets, the runner starts sessions without setting `MAITY_GIT_INODE` or `MAITY_GIT_PRIVATE`, Codex's maity starts running outside its sandbox, maity's state directory starts reading `.git` through a descriptor, or git can be given a repository by descriptor instead of by path

At a session's start the runner records the inode of the clone's `.git`
(`MAITY_GIT_INODE`, read on the agents' side with `ls -di` where the
runner cannot read it itself). Before maity starts git there, it opens
the clone's root, then `.git` from it once, without following a link,
and refuses a directory with another inode. It copies the refs (and,
for Codex, reads the recorded git; for the others it is read from the
runner's directory since 818828af) through that descriptor, so a `.git` renamed after
the check is not read. git's own repository for the run (its
configuration, HEAD, refs) is made outside the clone, in the runner's
directory for the agent, which the sandbox hides (`MAITY_GIT_PRIVATE`);
for Codex, whose maity runs inside its sandbox with the agent's own
rights, the runner sets the value `clone`, and it stays in `.git/maity`,
made through the descriptor. A directory inside the clone, a link or a
relative path is refused. Without the inode or that variable maity runs
no git: a session started by an older runner needs a restart. On
Windows (local mode) no directory opens, so the inode is compared by
name. The check of the clone (`_inspect`) and the objects
and index git reads still go through the name `.git`: under an exchange
the check reads the replacement and passes on only a plain clone's keys,
none of which starts a program, and objects and the index are data.

**Reason:** the sandbox denies the agent `.git/maity` and the paths that
redirect git, not renaming `.git` itself, and the clone's root is
writable. A directory of the session's own named `.git` then held a
`maity/git` that maity ran outside the sandbox. Claude Code blocks that
rename today with a mount of its own, which the runner neither asks for
nor checks, so an update of Claude Code could reopen it unnoticed.

**Rejected alternatives:**
- Denying writes to `.git`: the whole directory turns read-only, and
  commit, fetch and push write refs, the index, objects and logs there.
- Making `.git` a mount point in the sandbox settings (a rename then
  fails with EBUSY): the settings cannot ask for it.
- Recording the device too: `ls -di` prints only the inode on every
  system, and a decoy cannot come from another file system, since a
  directory cannot be renamed across one.
- Falling back to the name when the variable is missing: the fallback
  would be the hole again, for every session older than the runner.
- git's own repository under a random name in `.git/maity`: git opens
  it by a path through `.git`, and the name can be learned. A sandboxed
  command started while `.git` was renamed sees the real `.git/maity`
  under its new name, puts `.git` back and watches for new names; a
  decoy with that name gave git a clean filter that ran outside the
  sandbox (review of #1683).
- Handing git `/proc/self/fd` paths with `pass_fds`: Linux only, and a
  runner on macOS has no such path into an open directory.
- Pinning more keys with `-c`: configuration can start programs
  through many keys, filters among them.
- Taking an unset `MAITY_GIT_PRIVATE` as Codex: a session whose
  variable is lost, or a runner that forgets it, would put git's
  repository back under `.git/maity`, opened by a path through `.git`;
  the runner names Codex's case instead, and maity refuses an unset
  variable under the runner (review of #1683 round 2: unset, a decoy's
  filter ran outside the sandbox).

**Known gap:** the state directory (the credential) is still taken
through the name `.git`. `maity gh` reads its record and compares the
body-file walk through `opened_git`'s descriptor since #1663 (round 7). Under a sandbox
that lets the agent rename `.git`, a later sandboxed command can also
read the real `.git/maity` under its new name, because the deny applies
to the path; only the harness can close that. Claude Code 2.1.322
refuses the rename (EBUSY) with a mount of its own. Codex's git
repository stays in `.git/maity` by name: Codex's maity runs in its
sandbox, so a decoy's program runs there too (review of #1683 round 2,
in a Codex-like bwrap: once inside, never outside).

## A headless placement is offered no tool for asking a person

**Id:** e71f0da3-46ed-4276-b88a-3fcd6af905bf
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-1pxc2shwk43p (the maintainer, 2026-11-10: agents work autonomously, so a headless placement must not be able to ask an interactive question nobody can answer); `cli/src/maity/runner/adapters.py`; Claude Code's permission documentation (`dontAsk` denies `AskUserQuestion` even when an allow rule matches; a bare tool name in a deny rule removes the tool from the model's context); Codex's configuration source (`[tools.experimental_request_user_input] enabled`, on by default; `codex exec` rejects the tool's request)
**Revisit when:** a supervised placement gets a way to put a question to a person and wake with the answer, or a harness renames its question tool or the switch that turns it off

For a supervised placement, where the harness runs headless on each event,
the runner's generated configuration takes away the harness's tool for
asking the person at the terminal:

- Claude Code: `AskUserQuestion` as a bare name in `permissions.deny`.
  `--permission-mode dontAsk` already denies the call, but leaves the tool
  in the model's context; the bare deny removes it.
- Codex: `[tools.experimental_request_user_input] enabled = false` in the
  placement's `config.toml`. The tool is registered by default, and
  `codex exec` rejects its request.
- opencode: nothing to add; its configuration denies every tool it does not
  name.

Interactive placements, where a person is at the pane, keep what they had.

**Reason:** agents in Maity work autonomously, and nobody sits at a headless
run. Both harnesses refuse the question tool's call there, so a question
put through it reaches no one. A harness that answered it empty instead
would be worse: the run would go on as if a person had chosen. A person's
decision is asked for through Maity (`maity ask`), which reaches the human's
inbox and wakes the agent with the answer. With the tool not offered, that
is the way left to put a question to a person.

**Rejected alternatives:**
- Relying on `dontAsk` alone for Claude Code: the call is refused, but the
  tool stays in the model's context and offered.
- Taking the tool away from interactive placements too: their
  configuration is left as it was. For Claude Code, interactive placements
  run with `dontAsk` as well, which already refuses the call, so a person
  at the pane is not asked through this tool either; letting them ask would
  mean changing `dontAsk` for every other prompt there, a decision of its
  own. Codex keeps its question tool in an interactive placement.

## Claude Code placements write no attribution lines

**Id:** fe95ffe6-7f21-4e9b-b572-079444a9bde0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-dtdx205z8232 (agents on the runner added `Co-Authored-By: Claude …` to commits and a "Generated with" line to pull request bodies; the lead's decision on the key); Claude Code's settings reference (`attribution`, `attribution.commit`, `attribution.pr`, `attribution.sessionUrl`, `includeCoAuthoredBy`); a check with Claude Code 2.1.322 `-p` in scratch repositories, 2026-11-12; a check with 2.1.280 and 2.1.322, 2026-11-12, of a `--settings` file holding `attribution: false` with an allow rule and an `env` value; `cli/src/maity/runner/adapters.py`
**Revisit when:** Claude Code renames or drops the `attribution` keys, or the oldest Claude Code a runner supports is 2.1.281 or later

The settings the runner writes for every Claude Code placement, interactive
or supervised, sandboxed or not, set
`attribution: {"commit": "", "pr": "", "sessionUrl": false}`: no commit
trailer, no line in a pull request body, no session link.

**Reason:** pull requests and commits here carry no attribution lines, and a
squash merge carries commit messages into main. Claude Code adds both lines
by default, through its own instructions to the model, so agents had to
strip them by hand and sometimes did not. In the check, a run with this key
wrote neither line; the same run with `{}` wrote both.

**Rejected alternatives:**
- `includeCoAuthoredBy: false`: deprecated since Claude Code 2.0.62, and
  ignored once `attribution.commit` or `attribution.pr` is set anywhere.
- `attribution: false`: hides everything too, but needs 2.1.281 or later; an
  older binary rejects the value and skips the whole settings file, which
  carries the placement's permission grant. The reference says so for user,
  project and local files; the check showed it for `--settings` too: 2.1.280
  applied neither the file's allow rule nor its `env` value, while the same
  file with the empty-string object, and either file on 2.1.322, applied
  both. Empty strings work on every version that reads `attribution`.
- Leaving it to the agents to strip the lines: the harness tells the model to
  add them on every commit and pull request, subagents included, so a missed
  line reaches the forge.

Codex and opencode are not changed: their configuration references list no
attribution setting (not tried with the binaries).

## `maity runner install` sets up the system service; an incomplete configuration is enabled, not started

**Id:** 84732ea1-d314-465d-939c-fd274b2f8b0d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-sxpjwek61bhv (the maintainer agreed the scope on 2026-11-10: a system service only, the shipped unit's manual steps done by one command, `uninstall` keeping state unless `--purge`); the team lead narrowed it on 2026-11-10 to fixed paths, refusing instead of repairing, a root-owned creation record, and no removal while agents may run; `cli/src/maity/runner/install.py`. The choices below are the implementer's within that scope, not confirmed by the maintainer.
**Revisit when:** a per-user (`systemctl --user`) variant is wanted, the shipped unit's `ExecStart` line changes, or `install` learns to write `[limits]` and a harness itself

`sudo maity runner install <pairing url> --code-file -` does the steps the
unit's header lists:
1. It checks for Linux, root, systemd, tmux and runuser.
2. It creates the `maity-runner` system user, records it in
   `/var/lib/maity-runner-install.json`, and makes `/var/lib/maity-runner`
   (state, workspaces; 0700, owned by that user).
3. It writes `/etc/maity-runner/runner.toml` and checks the service user can
   read it.
4. It writes the unit.
5. It pairs as that user.
6. It runs `systemctl daemon-reload` and `enable`.
7. It runs `maity runner check`.

A second run is safe. It creates only what is missing, pairs only an
unpaired runner, and keeps a file that differs unless `--force`.
`uninstall` stops and disables the service, ends its agents and removes the
unit. `--purge` also removes state, workspaces, the configuration and the
account install made. The paths are fixed; other paths are the manual steps
of `maity runner unit`.

1. **`ExecStart` names the interpreter of the `maity` that runs `install`**
   (`<python> -I -m maity runner serve …`), the way the agents' side already
   starts it. Every word is quoted for systemd: `%` and `$` are doubled, and
   control characters are refused.
   - Rejected: keeping `/usr/local/bin/maity`. A pipx install lives
     elsewhere.
   - Rejected: looking `maity` up on PATH. `sudo` resets PATH to its
     secure path, so the lookup would find another copy, or none.
2. **Before pairing, `install` checks that the service user can run that
   interpreter and read the configuration.** A pipx install under a home
   the service user cannot enter would otherwise only fail when the service
   starts, after the single-use code is spent. The same goes for a
   configuration directory a restrictive umask made 0700.
   `/etc/maity-runner` is install's own and is always set to 0755.
3. **A configuration `serve` would refuse gets the service enabled, not
   started, with the reasons listed.** That covers missing `[limits]` or a
   harness, and a key this version does not support. `serve` exits 78 on
   such a configuration, and the unit does not restart 78, so a started
   service would sit failed until someone restarted it by hand.
   - Rejected: refusing `install` until the configuration is complete. The
     person would then write the file `install` exists to write.
   - Rejected: guessing projects, repositories or a harness. Those are the
     operator's choices.
4. **`uninstall` ends the agents (`stop-all`) after stopping the service,
   and removes nothing unless it knows they stopped, or `--force`.** Not
   knowing counts as failing: no configuration, one that does not load
   (install's own starter does not), or no account of install's to run
   `stop-all` as. The
   unit's `KillMode=process` keeps agents running across a service stop.
   Once the unit is gone nothing would supervise them, and once `--purge`
   has removed the state their workspaces would be gone from under them.
   - Rejected: leaving them running. Agents would go on working with a
     credential whose runner is gone.
   - Rejected: warning and going on. A purge would then delete what running
     agents still use.
   - What it can know without stopping anything (the account, whether the
     configuration is there and loads) is checked before the service is
     disabled, so a refusal leaves the service as it was. `--purge` removes
     the account before the trees: a `userdel` that fails then leaves the
     account, its trees, the configuration and the record for the next
     `--purge` (the service is stopped and its unit removed by then), and
     one that stopped after the
     account was gone finishes on the record that names it. The
     directories then keep the gone account's uid, so they are checked
     against the uid in that record, before anything changes: owned by
     it, no link, and not writable by group or others, since nothing
     sets their modes back on the way to removing them. A record without
     a usable uid names no account, and its home is refused like any
     other.
   - Rejected: the trees first, then the account. A failed `userdel` left a
     record without a configuration, and the next `--purge` refused until
     `--force`.
5. **Fixed paths, and root refuses rather than repairs.**
   - `install` and `uninstall` take no `--config`; they use
     `/etc/maity-runner/runner.toml`, the unit under
     `/etc/systemd/system` and `/var/lib/maity-runner`. Other paths are the
     manual steps of `maity runner unit`.
   - Every directory on the way to a file root writes or removes is opened
     from `/` one component at a time with `O_NOFOLLOW`, and each must be a
     directory of root's that group and others cannot write. Files are made
     and renamed, or removed, through the last descriptor. Nobody but root
     can then swap anything on the way between the check and the change.
   - The service user's directories (writable by that user, and in the
     `single` layout by every agent) must be real directories of that
     user's; they are opened the same way and changed through their
     descriptor.
   - Anything not as install would have made it — a link, another owner, a
     directory or a file of root's that others can write, a kept configuration whose `state_dir` is
     not the fixed one as `serve` resolves it, or whose `hub.url` names
     another hub than the pairing URL — stops the command before
     the first change. `--force` writes install's own configuration
     instead, but not over a credential paired under one for another
     hub: that credential is the other hub's, and `serve` would refuse
     it. A pairing URL that is not valid UTF-8 is refused before the
     account is made, since no file can hold it. A file of root's is checked on the descriptor it
     is read from, so what is read is what was checked. The `workspaces`
     of a kept configuration are not checked: that directory is the
     service user's to write, so no root write depends on it. Whether the
     runner is paired is read the same way:
     the credential must be a regular file of the service user's, reached
     without following a link, so root never answers for a file a link
     points to.
   - Root's record `/var/lib/maity-runner-install.json` (uid, home, time)
     says install made the account. `install` does not take over, and
     `--purge` does not delete, an account the record does not name.
     Without that account or its record, `--purge` refuses before any
     change when `/var/lib/maity-runner` or `/etc/maity-runner` exists:
     nothing shows install made them. The account's comment is only a
     label.
   - Rejected: a custom `--config`. Its directories can sit under paths the
     service user can rename, and checking each such tree is more than the
     manual steps cost.
   - Rejected: repairing owners, links and writable files or directories of
     root's. Each is a sign someone else has been there, or could have been;
     root fixing it would act on their setup. Modes that only differ from
     install's (0755 for `/etc/maity-runner`, 0700 for the service user's
     directories, 0644 for a file with install's own text) are set back:
     nobody else could have written through them.
   - Rejected: a marker in the account's comment field. Where users may
     change their own full name, an account's owner can set it.
   - Rejected: adopting any existing `maity-runner` account. An account of
     the same name made for something else would be taken over, and later
     deleted.

Every call that touches the system goes through one `Host` seam, so the tests
run without root or systemd.

## A failed clone says why in the runner's log, not in the report

**Id:** e814c00b-fde7-4c0a-a3ca-f7b3510900df
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-3w09my9zkrez (two placements on a fresh runner reported `clone_failed` with no exit code and no detail, and nothing showed why); `cli/src/maity/runner/workspace.py`, `supervisor.py`
**Revisit when:** §15.7 gets detail codes for `clone_failed`

When the clone fails, the runner's log gets one line with the reason:
`<placement>: clone_failed: <why>`. The reason is maity's own message when
git could not run (not found, refused by maity's clone check, timed out),
or git's last line of output when it exited with an error. The report to
the hub is unchanged: `clone_failed`, the exit code, no detail.
- The text stays out of the report. `detail` is a closed list of codes
  (§15.7), and a tool's message is no code. The log line for a new state
  carries codes and numbers only for the same reason.
- The reason is printable, capped at 300 characters (the line adds the
  placement and the reason code), and every URL in it loses its userinfo,
  through the same redactor as the rest of the CLI (`redact.without_userinfo`).
  An https repository URL the runner accepts carries none, and an ssh one
  at most a user name. A redirect or a helper's message could carry a
  password.
- Rejected: free text in `detail`. The hub would then store and show a
  tool's message, which is outside the contract.
- Rejected: logging nothing, as before. `clone_failed` without an exit code
  covers several unrelated causes, so nobody could tell which one it was.

## A refused join says its code, reason and why in the runner's log, in code form only

**Id:** 1b6e0e38-6392-4180-ae47-597064b9023b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-fveaj86ec6e2 (the owner's report on a new agent profile: "joining failed · pickup_not_allowed" and an empty runner log; the code pointers in note nte-f4jnqm2ymvve), 2026-11-20; `cli/src/maity/runner/supervisor.py`. The format and the rejected alternatives are the author's, not yet reviewed
**See:** runner.md#a-failed-clone-says-why-in-the-runners-log-not-in-the-report — e814c00b-fde7-4c0a-a3ca-f7b3510900df — as of 2026-11-20
**Revisit when:** §15.7 gets detail codes for the causes of `pickup_not_allowed`; the runner's log gets levels; the exchange answers with a why

Every refused join step writes one line to the runner's log.
A refused pickup writes `<placement>: warning: join pickup refused: <code>
(reason <reason>, why <why>)`, and a refused exchange writes `<placement>:
warning: join exchange refused: <code> (reason -, why -)`. The report
to the hub is unchanged: `join_failed` with the code (`join_detail`).
- `pickup_not_allowed` names its cause only in `details.why`
  (`credential_issued`, `handle_taken`, `creator_lacks_authority`, …, §15.9).
  `join_detail` keeps the code, so before this the dashboard showed only
  `pickup_not_allowed`, and the log showed nothing more than the state line.
- Each value is printed only when it has the form of a code, otherwise
  `-`. What the hub sends is data from outside the runner. The form keeps a
  line break, a control character, a message or a token-shaped value out of
  the log, but it says nothing about where a value came from. An unknown
  code, such as a why the hub adds later, shows as itself, which is wanted.
  The join's URL and code are not in a refusal and are never logged (as in
  `run_join`).
- The exchange runs in the child `maity join`, whose machine line carries the
  code alone (for `forbidden`, the reason in its place), and the exchange
  answers `not_found` without a why (§15.9). So that line names the code alone.
- "warning:" is a word in the line, not a level: the runner's log is plain
  lines on standard error (`serve.log`).
- Rejected: putting the why into `detail`. §15.7 makes `detail` the code of
  the refusal, and the hub stores and shows it.
- Rejected: printing the hub's values as they come, through a redactor (as
  the clone's reason in e814c00b). Those values are codes by contract, so
  the code form loses nothing, and it holds even if a proxy answers in text.

## Only a supervised placement tells the hub it is supervised

**Id:** 497f16bd-9dc7-4aca-b4d2-b3055c782410
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3qb19f0r56zf (the maintainer's runner test of 0.1.0a8, 2026-11-11: two interactive placements went away after each answer and missed later messages); `hub/src/maity_hub/rules.py` (`SUPERVISED`); `cli/src/maity/runner/adapters.py`
**See:** runner.md#default-session-modes-claude-code-attachable-codex-woken-by-events — 46741392-ca22-48e6-9417-d509c67d31a8 — as of 2026-11-11
**Revisit when:** the runner gets a way to wake an interactive session on an event, or the hub's supervised duty changes

`adapters.launch` puts `MAITY_SUPERVISOR=maity-runner/<version>` into the
session's environment only for a supervised (headless) placement, beside
`MAITY_PLACEMENT` and `GIT_COMMON_DIR`; the agent's `maity resume` sends
it as `supervisor`, as before (8d425d7d). An interactive placement gets no
such variable, so the hub gives it the ordinary duty: wait with `maity
wait`, which in Claude Code's interactive mode is a background command
that wakes the session.

**Reason:** the variable used to go into every session. The hub then told
an interactive agent "do not start `maity wait`, end your turn, the runner
wakes you", but only the supervised loop wakes a harness. The agent ended
its turn, stopped listening, and never saw the next message.

**Rejected alternatives:**
- The runner types into an interactive session's pane when an event comes:
  the pane is one a person may be attached to and typing in, and the
  keystrokes race with what the agent is doing.
- Keeping the variable and telling the hub the mode: a second field in the
  resume and a hub change for what the runner already decides at launch.

## Git in a sandboxed session works without writing `.git/config`

**Id:** 82e70deb-7cf9-4ea1-be2f-137186b20b2d
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3qb19f0r56zf (the maintainer's runner test of 0.1.0a8, 2026-11-11: `git switch -c <b> origin/main` failed on `could not lock config file .git/config`, as did `push -u`; `branch -D` warned; a `.gitmodules` permission warning on fetch); git 2.47.3 with a held `config.lock`, checked locally and in `test_the_session_git_needs_no_configuration_write`
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-11
**Revisit when:** the sandbox lets git write `.git/config` again, or git changes what `switch -c` or `push` store there

The sandbox keeps `.git/config` unwritable on purpose: what it sets can
run a program outside the sandbox. So the runner gives a session under
Claude Code's or Codex's sandbox, by `GIT_CONFIG_COUNT`,
`branch.autoSetupMerge=false` (a branch cut from a
remote one stores no upstream), `push.default=current` (a plain `git push`
pushes the branch to its own name) and `fetch.recurseSubmodules=false`
(fetch does not read `.gitmodules`, which the sandbox replaces with an
unreadable placeholder in a repository that has none). They override the
clone's own values, which in a runner's clone are a plain clone's: the
clone check refuses a key a plain clone has not. Without a sandbox none of
this is set and the clone's configuration stands. The start prompt of a
sandboxed Claude Code or Codex session names what still fails: `push -u`,
`--set-upstream`, `--track` and `branch -m`. `maity report` reads a
branch without an upstream as its own branch on the push remote
(report.md).

**Reason:** with these settings the plain commands an agent types work,
without the agent having to remember a flag in every session.

**Rejected alternatives:**
- Letting the sandbox write `.git/config`: hooks, `core.fsmonitor` or an
  alias there run code outside the sandbox the next time any git runs.
- Only telling the agent the flags (`--no-track`, an explicit refspec): an
  agent that forgets one fails, and a compaction loses the prompt's
  details.
- The three settings in every session, sandboxed or not (the first
  version of #1663): without a sandbox they overrode a repository's own
  tracking, push and submodule settings for no reason (review of #1663).
- Deny rules for `push -u` and `--track`: the push itself happens before
  the configuration write fails, so a deny would refuse a push that
  works; the prompt names them instead.

## The sandbox's placeholders are hidden in `.git/info/exclude`

**Id:** c4c60f8e-d87f-44f6-bce6-97f2d5671af8
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3qb19f0r56zf (22 untracked files in a placed clone, 2026-11-11); `git status --porcelain --untracked-files=all` in a sandboxed `claude -p` run of 2.1.322 with the runner's settings in a scratch clone, 2026-11-11
**Revisit when:** a Claude Code version adds or drops a placeholder, or the sandbox stops creating them

Claude Code's sandbox puts an empty placeholder in the work tree's root
for each protected path that is missing (`.bashrc`, `.gitconfig`,
`.gitmodules`, `.mcp.json`, `.claude/skills` and others), and `git status`
listed all 22 as untracked. Before a sandboxed Claude Code start the
runner writes those of them (`adapters.CLAUDE_PLACEHOLDERS`) that are
missing or an empty directory, root-anchored, into the clone's
`.git/info/exclude` between two marker lines; the block is rebuilt at
every start, every other line stays. The agent cannot write `info/` itself
(GIT_PROTECTED), and inside the sandbox it cannot create those paths. A
path with content (a file, a link, a directory with entries) is not
listed: it is real, untracked work that `git status` must keep showing.

**Rejected alternatives:**
- Listing every path, whatever is there (the first version of #1663): a
  real untracked `.gitmodules`, `.mcp.json` or `.claude/skills/…` then
  vanished from `git status` (review of #1663).
- An entry in the repository's `.gitignore`: it would be every project's
  business, for files only this runner's sandbox creates.
- `core.excludesFile` through the session's environment, pointing to a
  file in the runner's state: the sandbox denies reading the runner's
  state, so git inside it could not read the file (inferred, not run).

## A placed Claude Code agent runs `maity` alone

**Id:** 996b6f48-a8d7-4b81-b977-33cef46bc4cc
**Type:** constraint
**Type:** incident
**Status:** needs-review
**Evidence:** confirmed
**Source:** card tsk-3qb19f0r56zf (the runner test of 2026-11-11: after its first `maity resume`, a placed agent ran `maity` in pipes and chains, read "this clone has not joined a project", took the hub for broken and stopped without `maity wait`; its session transcript); Claude Code 2.1.329's sandboxing documentation and settings reference (code.claude.com/docs/en/sandboxing, settings-reference `sandbox.excludedCommands`), read 2026-11-20: a call leaves the sandbox only when the entries cover every command in it, the trigger of this entry's **Revisit when**; a re-check on Claude Code 2.1.329 and 2.1.325 in a container with bubblewrap, no hub and a marker credential, 2026-11-20 (security round 5, S200): the sandbox probe of card tsk-nnmgvz773z5n (`claude_sandbox_probe.py`, from its branch, not merged) and 26 added lines, run without and, on 2.1.329, with the runner's hook; card tsk-f5fy2zq26xcy (from the review of #2019), 2026-11-20: the hook refuses `MAITY_WAIT_TIMEOUT` before `maity`
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-11
**See:** runner.md#a-placed-claude-code-agents-maity-line-is-one-plain-call-held-to-that-by-a-hook — 63492c65-e6bf-4fd8-9a73-5a599f11707e — as of 2026-11-13
**Verification:** contradicted — a runtime re-check on 2.1.325 and 2.1.329 (S200) did not confirm the exclusion matching this entry and 2fa61a18 record without the runner's hook; with the hook in place every tested line that is more than one plain call was refused before it ran, and a line with a command other than `maity` kept its `maity` inside the sandbox, without the credential. The details are with the lead
**Revisit when:** Claude Code matches `excludedCommands` per part of a compound command, or the credential becomes readable inside the sandbox

Claude Code's sandbox hides `.git/maity`, and only a command that matches
`excludedCommands` (`maity *`) runs outside it. A pipe or a chain that
does not start with `maity` does not match, so its `maity` runs inside
and finds no credential; a line that starts with `maity` and holds more
than the call is refused before it runs (63492c65). The start prompt of
a Claude Code placement says to run every `maity` command alone. When `MAITY_PLACEMENT`
is set and no credential is readable, `maity` says that instead of "has not
joined a project".

Needs review since security round 5 (S200): Claude Code 2.1.329's
documentation says `excludedCommands` is matched per command of a
compound call, which is this entry's revisit condition. The runtime
re-check on 2.1.325 and 2.1.329 (Source) found that Claude Code's
exclusion matching differs from what this entry and 2fa61a18 record; the
details are with the lead. A chain or pipe with a command other than
`maity` stays inside the sandbox, as above. With the runner's hook in
place, every tested line that is more than one plain call was refused
before it ran, and the plain forms the hook passes ran outside with the
credential, but for one: `MAITY_WAIT_TIMEOUT=5 maity wait`, which the
hook passes, stayed inside, so its `maity` finds no credential. Since
card tsk-f5fy2zq26xcy the hook refuses that line, and a placed agent
passes `maity wait --timeout N` instead (63492c65). Not run:
the probe's managed-settings and user-settings steps (they change the
files the container's own Claude Code reads), and its step for another
clone's credential twice ended without the one call it asks for (the
call that ran found the file hidden). `capabilities.CHECKED` stays at
2.1.325 until a person re-checks this entry. The claim of 2fa61a18 and
the README's sentence on the checked behaviour were corrected on order
(S200): the hook, not the exclusion, holds a call with something in
front of `maity`.

**Reason:** the old message sent the agent to `maity join`, which it cannot
do, and hid that the cause was the shape of its own command.

**Rejected alternatives:**
- Making the credential readable inside the sandbox: repository code an
  allowed build or test command runs could then read it (ea36c196).
- Rewriting the agent's command in a hook: the harness owns the command.
  Hooks do run in a sandboxed placement, but the runner's own hook only
  refuses a line that is more than one plain `maity` call (63492c65); it
  does not rewrite it.

## A placed Claude Code agent's `maity` line is one plain call, held to that by a hook

**Id:** 63492c65-e6bf-4fd8-9a73-5a599f11707e
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** card tsk-bg81webs911m (the lead's order for a PreToolUse hook on a `maity` line, before the other reads of the card), 2026-11-13; Claude Code's hooks documentation (code.claude.com/docs/en/hooks), read 2026-11-13: command hooks run unsandboxed, exit 2 refuses a PreToolUse call, `onFailure: "block"` (2.1.295 and later) refuses it when the hook fails or times out; Claude Code 2.1.325 on the agents' machine, 2026-11-13 (`claude -p` with `--setting-sources user`, the hook in a `--settings` file, `dontAsk`, no sandbox, no hub): the hook refused `maity --version > out1.txt` before it ran and passed `maity --version`, and a hook at a missing path refused `echo`; the first review round of #1752 (the version the failure policy needs), 2026-11-13; card tsk-54492gk4xp69 part 1 (the lead's order to refuse `maity runner` from a placed session's tool call), 2026-11-17; the fifth review round of #1942 (the order to refuse a line that names `maity` and holds a comment, a heredoc or more than one line, and to count quoted words in line order), 2026-11-18; the `excludedCommands` matcher of Claude Code 2.1.327 (native binary, sha256 `343c744baa14bfd38286a7cb90871051f04379956da6c5b803a9e66019a76ac9`), read statically only in the sixth review round of #1942, 2026-11-18: the readings differ, and nothing was checked live; the sixth review round of #1942 (the order to hold a `maity` line after variable assignments or a wrapper command to the same rules, whichever way the exclusion matches), 2026-11-18; the seventh review round of #1942 (the decision to replace the wrapper list by one rule: only variable assignments may stand before `maity`, anything else is refused outright), 2026-11-18; a review leg of the seventh round (the confirmation that a word whose path ends in `/maity` counts as `maity` in every position, and the order to name that rule and test it), 2026-11-18; the eighth review round of #1942 (review A1269 and its order: a word counts as `maity` or `runner` also with the backslashes and quotes left in it taken off, the line starts with `maity` only when its first word is `maity` alone, and the sentence that assignments cannot run another program goes; review A1271 on the same start of the line), 2026-11-18; review A1270 of the seventh round, relayed in message 162483 (a quoted or escaped first word skipped before `maity`, `$"…"` locale quoting, quoted text read again one level less than `calls_runner` reads it, mutants that survived), 2026-11-18; the decision of the eighth round (message 162185) to allow only assignments to a list of names before `maity`, and every `+=` refused, 2026-11-18; review A1269 and the decision of the eighth round that amends 162185 (message 162361, relayed in 162371 and 162378): no `MAITY_*` wildcard, only `MAITY_` names documented for agents, every runner-trusted name refused and a guard test for the list, 2026-11-18; the inventory of the `MAITY_` names in `cli/src/maity` at d6474bb5 for that decision, 2026-11-18; the ninth review round of #1942 (review A1309 and the order in message 163399: a word that holds literal brace alternatives counts by each alternative; lowercase and bare `LC_` names before `maity` stay refused), 2026-11-18; the tenth review round of #1942 (review A1337, and the lead's order in message 164326 after the decision in message 164294 to do it in one round: a word's brace expansion, joined with the text around it, counts by each word it makes, capped at 256 words, a word over the cap refuses the line, and the reason the ninth round gave for leaving such names unread was wrong), 2026-11-18; the eleventh review round of #1942 (review A1371, and the lead's decision in message 165140: a letter range's step may carry a sign, and a word that holds an unquoted `{` and also a quoted or escaped `{`, `}` or `,` is not read and refuses the line, fail-closed, quote-aware expansion left for a later card), 2026-11-18; Bash 5.2.21 on the author's machine, 2026-11-18: `{a..e..+2}` and `{a..e..-2}` make `a c e`, `{e..a..+2}` makes `e c a`, `{a..e..0}` and `{a..e..+0}` make `a b c d e`, `{a..e..++2}` stays as it is; review A1372 of the tenth round, relayed in the twelfth review round of #1942 (Bash's rule for when a `}` closes a brace group, and the quote removal after a range of mixed letters), 2026-11-18; Bash 5.2.21 on the author's machine, 2026-11-18: the closing rule, ranges of mixed letters, number ranges and their zero padding, compared word by word with the hook's expansion; review notes of the eleventh round's head, relayed in the twelfth review round of #1942 (message 165755: other fail-open forms of the mixed-word refusal, a crash on a long step, false refusals of quoted programs), and the decision of the twelfth round (message 165756, relayed in 165786): quote-aware brace expansion replaces the mixed-word refusal, a fuzz test against Bash in CI, the step bounded as Bash bounds it, a failing hook refuses, 2026-11-18; the CI run of #1942 at b6d523e6 on Ubuntu 26.04 (job 135108287127), whose Bash expanded a word otherwise than the hook's 5.2 rules, and Bash 5.3's `braces.c` (Ubuntu's 5.3 source), read 2026-11-18; reviews A1406 and A1407 of the twelfth round's head, relayed in the thirteenth review round of #1942 (messages 166319 and 166393), and lotse's ruling for that round (message 166401, relayed in 166408): a line with a construct the hook does not model exactly is refused, 2026-11-18; the S200 re-check on Claude Code 2.1.329 with the runner's hook, 2026-11-20 (996b6f48: `MAITY_WAIT_TIMEOUT=5 maity wait` passed the hook and its `maity` found no credential; lines with only the other allowed names before `maity` got it), and card tsk-f5fy2zq26xcy from the review of #2019 (the order to take `MAITY_WAIT_TIMEOUT` off the list, with `maity wait --timeout N` as the way out), 2026-11-20, and the lead's ruling on it (the hint in its own reason, only for a prefix that assigns `MAITY_WAIT_TIMEOUT`), 2026-11-20; the review of #2024 and card tsk-12zb1s0zgdjw, 2026-11-20: a correction to how the hook reads backticks, with a Bash differential test, and the lead's ruling to keep the timeout hint for any unquoted word before `maity` that reads as an assignment to `MAITY_WAIT_TIMEOUT`, after `env` included, and to correct only its wording; the first and second review rounds of #2026 (both review legs, and the lead's and security's reset of the scope), 2026-11-20: substitutions and expansions that hide the name, read as a correction with a Bash differential test, and the boundary of what the hook guarantees; card tsk-wc9ayykt4hdg (the order that the hook hold on its own where `maity` meets a control character or a Unicode space, by either of two options), 2026-11-20. The grammar, the version gate and the rejected alternatives below are the author's, not yet fully reviewed
**See:** runner.md#a-placed-claude-code-agent-runs-maity-alone — 996b6f48-a8d7-4b81-b977-33cef46bc4cc — as of 2026-11-13
**See:** runner.md#claude-codes-sandbox-runs-strict-or-not-at-all — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-13
**Verification:** uncorroborated — what this entry says of Claude Code's sandbox exclusion rests on static readings of its 2.1.327 binary that differ from each other; none was checked live, and the hook relies on none of them
**Revisit when:** Claude Code can exclude a single call from its sandbox rather than a pattern over the command line; Claude Code's sandbox exclusion is checked live; the Claude Code version the runner starts changes; `maity` runs inside the sandbox and needs no exclusion; hooks stop loading from a `--settings` file under `--setting-sources user`; the names allowed before `maity` change; the brace limit (`BRACE_LIMIT`) changes, or Bash changes its brace expansion or its quote removal; the hook models a refused construct exactly, or a refused construct turns out to cost placed agents; the runner stops accepting Claude Code versions older than 2.1.295 even with `require_sandbox = false`; opencode gets an OS-level sandbox (tsk-nynpvag9zvhh)

Under its sandbox, a placed Claude Code session runs a hook before every
tool call (`runner/plaincall.py`), written by the runner into the
session's settings beside `excludedCommands`. A command line that starts
with `maity` passes only as one plain call: words of letters, digits and
`_-./:=@%+,~^#`, a backslash before any character but a newline,
single-quoted text, and double-quoted text without `$`, a backtick or
`!`, with no newline inside. Anything else on such a line (a pipe, `;`,
`&&`, `||`, `&`, a redirect, `$(…)`, backticks, `<(…)`, a heredoc, a
`$`) is refused before it runs, with the way out: the text in a file in
the clone, passed with `--body-file`. So `maity say … - <<'EOF'` does not
run for a placed Claude Code agent. Before looking for `maity`, leading
comment lines and blank lines are skipped, as Claude Code skips them when
it reads a call (S200, below), and so are leading spaces and characters a
plain call may not hold, so a line counts however the harness trims it; a character a plain call may hold
(`/`, `.`, `:` and the like, a quote, a backslash) is not skipped, so a
quoted or escaped first word (`"[" maity`, `"" maity`) is a word of its
own before `maity`, and the line starts
with `maity` only when `maity` is followed by a space, a tab, an operator,
an expansion (`$`, a backtick) or the line's end: a first word that only starts with `maity` is read by
the word split below like any other word. On a line that does not start
with `maity`, where `maity` is a word (as the word split below reads the
line, also a word of quoted text read again, a word that reads
`maity` once the backslashes and quotes left in it are taken off, and a
word with a brace one of whose alternatives reads `maity`; in any
case and by any path), only assignments to a short list of names may
stand before it: `NO_COLOR`, `LANG`, `LC_*` and
`TZ` (`ALLOWED_BEFORE_MAITY`), each by its exact name in capitals
(`LC_` followed by at least one capital, digit or underscore), written unquoted with `=`, one or several, quoted values allowed. The value is
not judged there; the one-plain-call rule refuses one that expands. Such
a line is held to the same one-plain-call rule. Anything else before
`maity` refuses the line outright: an assignment to any other name, or
with `+=`, a command word by name or path, whatever command it is, a
shell keyword, `!`, a redirection or fd duplication, a subshell or a
group, and `maity` by a path. The reason
names the plain form, `maity …` at the start of the line, and
`--body-file` for text that mentions `maity`, since such text is refused
as well (`echo maity | cat`, `git log --grep maity`). A word whose path
ends in `/maity` (in any case) counts as `maity` in every position, so
`cd /some/path/maity && make` is refused outright. A command
substitution in any form (backticks included, also inside double
quotes, or `$(…)`) that names `maity` is refused too, since the shell
reads the substitution's text as a line of its own, and an expansion
glued right after `maity` holds the line to one plain call, since it may
make nothing. The hook guarantees that a line Claude Code may take out
of the sandbox, `maity` after only the allowed assignments, runs only as
one plain call; names assembled from expansions are left to the sandbox
and to the CLI's own guard (#2016, `runner_own_file`). Rejected: reading
how expansions assemble a name, tried in the first review round and
dropped, since its rules refused ordinary agent commands
(tsk-12zb1s0zgdjw: a correction to the reading, with a Bash
differential test, not a new decision). A line in which
`maity` is no word, only part of a longer one (`maity.md`, `maity/`, a
clone directory named after a handle such as
`/some/path/maity-coder-claude-004`), is left to the permission rules,
apart from the two rules below.

Beyond that, on any line, whatever it starts with, two rules refuse a
call (tsk-54492gk4xp69, part 1). First, a line that names `maity`
anywhere (in any case, also with quotes or backslashes between its
letters) is refused when it holds a comment (a `#` at the line's start or
after a space or an operator, quoted or not), a heredoc operator (`<<`,
quoted or not) or more than one line: the hook does not read such a
line to the end, so it does not try. A line whose quotes never close,
or that holds `$'…'` text with a backslash or an unquoted `$"…"`
(Bash's locale quoting, whose text a translation may replace), is
refused whatever it holds. Second, a word `maity` followed later by a
word `runner` is refused (`calls_runner`), whichever commands or
operators stand between them. The check splits words at unquoted spaces,
tabs and operators and takes quotes and backslashes off; a word counts
as `maity` or `runner` also once the backslashes and quotes left in it
are taken off, and a word that holds a `{` also as each part of it
between `{`, `,` and `}`: the shell may make a word of its own of each
literal alternative of a brace, so a brace that holds both words counts
as `maity` followed by `runner`, and one whose alternative is `runner`
counts as `runner` after a `maity` word or a word the shell expands. A
word that holds a `{` counts as well as each word its brace expansion
makes, the alternatives joined with the text around them
(`{mait,--for=}y` makes `maity` and `--for=y`; nested braces and several
brace groups in one word expand as Bash expands braces, quoted and
escaped characters as text, letter
ranges such as `{a..e}` included, with a step that may carry a sign as
in Bash 5.2: the sign does not count, the endpoints give the direction,
and a step of 0 counts as 1), up to 256 words (`BRACE_LIMIT`). The hook
reads braces by Bash's own rule (`braces.c`) for when a `}` closes a
group: a `{` opens one only when a later `}` closes it, and that is the
first `}` outside nested braces after a `,` or a `..` outside nested
braces (a `..` right before that `}` does not count); a `}` before that is text in the group, and the scan goes on. A
`{` at the word's start, or after a space, that a `}` follows is text
(`find . -exec ls {} \;`), and a `{` that no `}` closes is text while a
group after it still expands. A group without a `,` is a range or text.
The braces are read quote-aware: the expansion is made from the word as
it is written, and quoted and escaped characters (empty quotes and
substitutions too) are passed over as Bash passes over them, so they
open, close and split no group. Each word the expansion makes then has
its quotes and backslashes taken off, as the shell's quote removal takes
them off; that also takes off the backslash a range of mixed letters
makes (such a range passes ASCII 91 to 96, the `\` among them). The
word's text, its quotes taken off, and each word its expansion makes
(split at spaces and operators) are expanded as well, as a shell that
reads them again expands them, and what that makes is read again, up to
four readings deep; a word that would still change in a further reading
is not read. Bash 5.3 reads some braces otherwise than
5.2: a `..` after a group's first `,` does not count, and a group with a
`..` and no `,` opens only when its text starts like a range. The hook
makes the words of both versions, so either may run the line. A range
that makes a backtick, which the shell
reads as the start of a command, is not read. A word
whose expansion makes more, that holds more than 256 brace groups, whose
braces nest deeper than the hook's stack allows, whose scan takes more
steps than a bound set by the word's length, or whose braces hold a
part this reading does not cover is not read: it
counts as `maity` and as `runner`, so it refuses the line. A range end
or step with more digits than an integer holds is text, as in Bash, and
a call the hook fails on is refused. Each part's
words are made only up to the limit and counted before they are joined,
so a word that would make millions costs no more than one at the limit.
A number range (`{1..9}`) makes only its first number for the check: its
other words differ from that one only in digits, and neither name holds
a digit, so `{1..1000}` passes. Tests compare the hook's expansion
with Bash's on generated words, unquoted, quoted and escaped, with a
fixed seed and a fresh one each run: no word may pass that Bash makes
into `maity` or `runner` unless the hook counts it as such or does not
read it. The split itself expands nothing and knows no comments or
heredocs, which is why the first rule refuses those lines rather than
reading them. A word the shell would
still expand counts as `maity` before a later `runner` word, and as
`runner` after a `maity` word in the same text; a word that starts with
an unquoted `~` and holds no `/` counts as one the shell expands. Quoted
text that holds spaces or operators is read again the same way, four
levels deep, and its words count in the line's order with the words
around it, so `maity` in one quoted text and `runner` in a later one
refuse the line; text nested deeper is refused, whatever it holds. Text
is not told apart from a call: `maity say … runner`, quoted or not, is
refused too, and the reason points to `--body-file`. Those commands are
the runner's own: it starts its in-session ones through the launch, the
pane's pipe and this hook, never through an agent's tool call, so no
placed session needs one.

Not read: values the hook cannot know, such as globs matched against
files and expansions of variables or of input. The check is a second
line behind the sandbox, not a parser of every shell form.

Corrected in the tenth review round of #1942: the ninth round counted a
word with a brace only by the parts between `{`, `,` and `}`, and left a
name the shell builds by joining those parts with the text around them
unread, as a command built from expansions, on the reading that such a
join leaves an extra word `maity`'s parser rejects. That reading was
wrong: an option that takes a value swallows the extra word
(`{mait,--for=}y {--for=,runne}r status` makes
`maity --for=y --for=r runner status`), and the joined forms are known
from the line alone. So the brace expansion is now made, up to the
limit, and the boundary of what is not read is only what the line does
not hold. Letter ranges are expanded on the author's reading that they
are as knowable as alternatives (`{l..m}aity` makes `maity`); the order
named alternatives only.
The hook does not depend on how Claude Code's sandbox exclusion matches
`maity *`. It fails closed on a line where `maity` is a word after
anything but the allowed assignments: such a line is refused, and one
after allowed assignments only is held to one plain call, as a line that
starts with `maity` is; a later `runner` word or an expanding word
refuses it either way. The shell does not read an assignment's words
again, and the hook does not judge what an assignment sets. An
assignment can still choose the program the shell runs or load code
into it (`PATH`, `LD_PRELOAD`, `PYTHONPATH`, `BASH_ENV` and the like),
so the names that may stand before `maity` are allowed by a list, and
every other name is refused. Claude Code's matcher
(2.1.327, native binary, Source) was read statically only; the readings
differ, so the hook does not rely on it. The differing static readings
are in the round-6 review record of #1942.
Telling the runner's own starts apart by who starts them, not by the
line, is the card's later part.

Rejected: reading the line the way `maity`'s parser and the shell would
(the first version of this check: commands split at operators, maity's
leading options walked to its subcommand). Each rule it had to mirror was
one more place to differ from the real parsers, and review found such
differences. Rejected as well: teaching the word split comments and
heredocs (the fourth round's review proposed it). It would be one more
form to mirror; refusing every line that names `maity` and holds one
costs little, since a placed agent's `maity` call needs neither. Refusing every `maity … runner` word order, and every
line the check cannot read to the end, costs refusing text that holds
both words (quoted text included), comments, heredocs and several lines
beside a `maity`, deeply nested quoting, lines with an unclosed quote
and lines with `$'…'` text that holds a backslash or with `$"…"`,
and lines with a word whose braces make more than 256 words or that the
hook does not read,
whatever they name;
each has a way out (a file with `--body-file`, one command per line
without a comment, a line without the nesting, or `printf` with single
quotes for the escapes, plain double quotes for `$"…"`). Rejected for
`$'…'` text: decoding its escapes, one more form to mirror; for `$"…"`,
reading it as plain double quotes, since a translation catalog can
replace its text.

Rejected for words that mix unquoted braces with quoted or escaped
brace characters (the eleventh review round), and chosen in the twelfth:
quote-aware brace expansion now, that is, expanding only the braces the
shell sees and keeping quoted ones as text. The eleventh round rejected
it: it would also stop refusing such words that name neither `maity`
nor `runner`, but it is more work, and refusing the word fails closed in
the meantime; it can follow as a card of its own. The twelfth round
reversed that (message 165756) and reads braces quote-aware, as above.

Rejected in the twelfth review round, after it was the decision of the
eleventh (superseded there by quote-aware expansion): refusing a word
that holds an unquoted `{` and also a quoted or escaped `{`, `}` or `,`,
as not read. It still failed open after three rounds of review, and it
refused everyday one-liners whose quoted programs hold braces with
quoted commas (`awk`, `jq`, `python3 -c`).

Decided in the thirteenth review round (lotse's ruling, message 166401):
the hook refuses a line that holds a construct it does not model
exactly, instead of modelling it. The brace reading above stays only for
plain braces. Refused are, at the least: `eval`, `source` or `.` as a
command, `trap`, and a shell's `-c` with a word after them that is not a
plain literal (no quotes, escapes, braces or expansions); `$'…'`; a
backslash-newline outside single quotes; a word with a brace the shell
may expand that also holds `${`, `$(`, a backtick or a process
substitution, joined across the parentheses that split it for the hook;
a backtick whose text holds a quote, a backslash or a `#`, or that never
closes; a `${` whose text holds a quote, a backslash or a backtick; a
comment on a line with a `{`; an unquoted heredoc whose body holds `$(`
or a backtick; and a quote that never closes. Heredoc bodies are taken
out before the line is read, so a plain heredoc passes, braces in its
body included, and so does a `$(…)` in double quotes, read to its `)`
with its own quotes passed over and kept in one word, a heredoc with a
quoted delimiter in it included (an unquoted one there, braces in such
a body, a body whose end the hook does not read exactly, or a comment in
the `$(…)` still refuse the line). In quoted text read again as a line,
only the `eval` rule counts, and only beside a `{`: such text may be
plain text in a `maity` call. The reason names the constructs, with
`--body-file` as the way out.

**Reason:** after twelve rounds of review, each of which found another
lexer corner that let a line through, modelling Bash's reading construct
by construct did not converge; refusing a construct that is not modelled
fails closed by construction. A refused `eval` or `bash -c` costs a
placed agent almost nothing, since it runs `maity` plain; plain heredocs
and substitutions keep passing, since those cost.

Rejected: modelling each construct exactly (continuations before `$'`,
`${` and `$(`; comments, heredocs and backticks beside braces; `eval`
chains past the reading bound; `${…}` inside a group): it did not
converge after twelve rounds.

Rejected for the names before `maity` (the eighth review round): keeping
every variable name and only rewording what the rule claims, since an
assignment can choose the program or load code into it whatever the
text says; and a list of refused names, which leaks the way the list of
wrapper commands of the fifth and sixth rounds did: a name nobody listed
passes.

Rejected as well: `MAITY_*` as a wildcard (the eighth round's first list,
message 162185; review A1269 and message 162361). The runner, its
supervisor and the placement set `MAITY_` variables that decide what
maity trusts: `MAITY_PLACEMENT` switches on the placed session's rules,
`MAITY_GIT_INODE` names the `.git` maity accepts, `MAITY_GIT_PRIVATE`
where git's private repository and the runner's records are,
`MAITY_STATE_DIR` the state directory and with it the credential and the
identity, `MAITY_SUPERVISOR` the session's mode at the hub,
`MAITY_RUNNER_CONFIG` the runner's own config, `MAITY_ERROR_LINE` the
supervisor's error channel, and `MAITY_SCRATCH` the scratch. One of them
on a line that runs `maity` outside the sandbox replaces the runner's
value with the agent's. So no runner-trusted name stands on the list.
`MAITY_STATE_DIR` stays off although docs/agents.md tells
agents to set it: that is for a second instance or a join outside a
runner's clone, where the hook does not run, and inside a placement it
is the runner's.

Since card tsk-f5fy2zq26xcy no `MAITY_` name stands on the list at all.
The eighth round had allowed `MAITY_WAIT_TIMEOUT` (cli.py `WAIT_ENV`,
docs/agents.md "Waiting on your harness"), the one name documented for
agents and read by the CLI. The S200 re-check (996b6f48) found that
`MAITY_WAIT_TIMEOUT=5 maity wait` passed the hook and then ran without
the credential, so the call failed although the hook had let it through.
The hook now refuses that line outright. A refused line with any
unquoted word before its first `maity` that reads as an assignment to
`MAITY_WAIT_TIMEOUT` gets its own reason (`WAIT_TIMEOUT_REFUSED`), which
names `maity wait --timeout N` ahead of the shared one: the word may
stand first, after `env`, as an argument or after an operator. Stopping
at the first word that is not an assignment was rejected, since it would
drop the hint for `env MAITY_WAIT_TIMEOUT=5 maity wait`, where the lead
ruled it right (review of #2024). Every other refused prefix keeps the
shared reason, so it carries no hint that does not apply (the lead's
ruling on the card).
docs/agents.md, docs/runners.md and the README tell a placed agent to
pass the flag. `MAITY_WAIT_TIMEOUT` itself
keeps working where the hook does not run (other harnesses, a plain
shell, a cloud environment's settings). Rejected: correcting only the
docs and leaving the name on the list, since the hook would then still
pass a line that cannot work in a placement; the card asked for the list
and the docs to agree.

`test_plaincall.py` keeps the list honest: it scans
`cli/src/maity` for `MAITY_` names in string literals and fails when one
is neither runner-trusted (its fixed `RUNNER_TRUSTED`) nor agent-facing
(its fixed `AGENT_FACING`, each name documented in docs/agents.md and
read by maity), and when any `MAITY_` name, a runner-trusted one or a
pattern, is on the list or matched by its assignment rule. A new
agent-facing variable is added to `AGENT_FACING`, not to the list.

The hook is the runner's own interpreter and module (`-I -m
maity.runner.plaincall`; on an ssh host `<maity> runner plaincall` with
the host's `maity` by its absolute path, as for the loop, 92a3aa0a), outside the clone and not the agent's to change. It has no
matcher, so it sees every tool, and checks any tool input with a
`command`. A hook that fails, cannot start or times out refuses the call
(`onFailure: "block"`), and unreadable input is refused too. The session's
settings set `disableAllHooks: false` over the agents' user settings.
Because the hook's refusal on failure needs `onFailure` (Claude Code
2.1.295), the runner switches Claude Code's sandbox on only from that
version (`capabilities.sandbox_version_ok`); an unknown or unreadable
version counts as older, and so does a prerelease of 2.1.295 (SemVer
sorts `2.1.295-rc.1` before `2.1.295`; build metadata does not count).
Where the sandbox's tools are there, such a start is refused unless
`require_sandbox = false` (92a3aa0a); then, and on a host without the
tools, the session runs unsandboxed (`sandbox_unavailable`), with no
exclusion for the hook to guard. The hook's shell form ends in `|| exit 2`, so a hook that cannot
start or fails refuses the call on any version; only a timeout needs
`onFailure`.
opencode, which runs without a sandbox and gets no hook, has rules meant
to allow `maity` only as one plain call after its allows; whether these
rules hold for every line shape is not verified. Without a sandbox those
rules are not a boundary either, so an opencode agent is treated as able
to run any command as the agents' OS user (req-kezp8rppfhn5).

Where a line's command starts is read past its leading comment lines and
blank lines (`_past_comment_lines`, security round 5, S200), the way
Claude Code reads a call: a comment line and a `maity` call under it
count as a `maity` line. That moves only the decision
where the command starts; `plain` and `read_whole` still read the whole
line, so such a line is refused as more than one plain call. Leading
assignments were already read past the same way: to the allowed names
the line is held to one plain call, to any other name refused outright,
and an assignment word that itself counts as `maity` (a value whose path
ends in `/maity`) is not read past. Reading past a comment line can make
no line pass that names `maity`: the whole line then starts with a `#`
or holds a newline, and `read_whole` refuses it (a test runs every
listed line under comment lines). The live re-check of S200 is in
996b6f48.

Since card tsk-wc9ayykt4hdg (2026-11-20), a line that names `maity`,
also once such characters are taken out, and holds a control character
other than a tab or a newline (C0, DEL, C1) or a space other than the
ASCII one (each character Python counts as a space, U+0085 and the
Unicode spaces among them) or a format character (Unicode category Cf:
U+180E, U+200B, U+FEFF, the zero-width joiners, the word joiner, the
soft hyphen and the bidi controls, all invisible, counted since the
review of #2070) is refused (`odd_spacing`). The check runs after the other rules, so a line they
refuse keeps its reason. The shell splits words only at a space, a tab
and a newline: `maity` followed by a carriage return, a vertical tab, a
form feed or a no-break space was part of a longer word to it, and no
rule above held such a line, while a harness that splits at that
character would read `maity` as the command. Rejected: the card's other
option, holding a line in which `maity` is followed by any character
outside the word set to one plain call. It covers only the character
right after `maity`, not one between an allowed assignment and `maity`
(`LANG=C`, a no-break space, `maity`) or between its letters, so the
hook would still depend on how the harness splits. The cost: text that
names `maity` and holds such a character (a no-break space in quoted
text) is refused as well, with `--body-file` as the way out; a line
that does not name `maity` is left as before.

**Reason:** only `maity` itself needs to run outside the sandbox. A line
that holds more than maity's call is held to the rules every other
command is, and the check does not rely on the shell to tell the parts
apart. A grammar of what may appear rather than a list of operators: a
spelling nobody listed (`${X@P}`, `$'…'`) falls outside it.

**Rejected alternatives:**
- A narrower `excludedCommands` pattern: the exclusion is a pattern
  over the line, and nothing in it says what may not follow `maity`.
- Deciding only the lines the exclusion lets out of the sandbox, by
  mirroring how it matches: that is the harness's behaviour, read only
  statically, with readings that differ, and it can change with any
  release; deciding every line in which `maity` is a word does not
  depend on it (sixth review round of #1942: fail closed whichever
  build runs).
- An allow-list of wrappers (`env`, `nice`, `sudo` and the like) whose
  `maity` line is held to one plain call, the sixth round's shape: a
  prefix nobody listed stays open, and a listed word that reads its
  arguments again defeats the plain-call check
  (seventh review round of #1942). Refusing every prefix but variable
  assignments costs refusing text that mentions `maity` as a word after
  another command; it has a way out (`--body-file`).
- Parsing each wrapper's options to find the command it runs: one more
  parser to mirror, for each command that may stand before `maity`.
- A list of refused operators (the order's first shape): an expansion
  nobody listed would pass.
- Letting heredocs through: their line holds `<` and a newline like any
  other redirection; a file in the clone carries the same text.
- `maity` checking its own command line: a program sees its arguments,
  not the line around it; a redirect is done before it starts.
- The hook in exec form (`args`): the shell form with the runner's
  quoted paths also runs on a harness version that predates exec form.
- No exclusion for `maity` at all: a larger change, for a card of its
  own.
- Only a warning for a Claude Code older than 2.1.295 (the first round
  of #1752): there a hook that fails or times out lets the call through,
  so the promise above would not hold for a version the runner accepts
  (review of #1752).
- Refusing every Claude Code placement on such a version, sandbox
  required or not: without the sandbox there is no exclusion and nothing
  for the hook to hold; a runner without `require_sandbox` already runs
  such sessions where the sandbox's tools are missing.
- Letting a comment line before a plain `maity` call pass, which a
  literal reading of S200's note ("skip comment lines") allows: it would
  undo the fifth review round's refusal of a line that names `maity` and
  holds a comment, a decision a person made, and the hook would have to
  read the comment exactly; the note was read as deciding where the
  command starts, which fails closed. Letting an assignment to any name
  stand before `maity` was rejected the same way: an assignment can
  choose the program or load code into it (the eighth round, above).

## A sandboxed Claude Code start needs the hook to run; an old or unknown version is refused where the sandbox could run

**Id:** 92a3aa0a-eed2-412a-9bad-5d0af30e7add
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-bg81webs911m, the follow-up to #1752 the lead ordered (lotse seq 127403, 127806, 128291) with the review of #1752 (hcrb, seq 128028: a version token needs its boundaries), 2026-11-14; Claude Code's settings documentation (managed settings take precedence over a `--settings` file; `disableAllHooks`, `allowManagedHooksOnly`). Which paths and switches count is the author's reading, not checked against a managed Claude Code install
**See:** runner.md#a-placed-claude-code-agents-maity-line-is-one-plain-call-held-to-that-by-a-hook — 63492c65-e6bf-4fd8-9a73-5a599f11707e — as of 2026-11-14
**Revisit when:** Claude Code reads managed settings from another place or under another switch, or reports whether hooks are on; a host without bubblewrap must run Claude Code sandboxed; the opt-out `require_sandbox = false` is no longer used; agents on an ssh host may install their own `maity` on purpose

Four rules hold a sandboxed Claude Code session to the hook of 63492c65:

- **Settings that switch hooks off refuse the start.** Before every
  sandboxed Claude Code start (supervisor `_refusal`) and in `maity
  runner check`, the runner reads the managed settings (Linux
  `/etc/claude-code/managed-settings.json` and each `*.json` in
  `managed-settings.d/` beside it, macOS under `/Library/Application
  Support/ClaudeCode/`; on an ssh host the Linux paths, read there) and
  the agents' user's `~/.claude/settings.json`
  (`capabilities.claude_hooks_off`). `disableAllHooks` or
  `allowManagedHooksOnly` set to anything but `false` in a managed file,
  or `allowManagedHooksOnly` in the user's, refuses the start
  (`harness_refused`) with the file and the switch in the log. A managed
  file that is not a JSON object, cannot be read, or a host that cannot
  be asked counts as switched off. The user's `disableAllHooks` does not
  count: the session's own settings file sets it back to `false`.
- **The hook starts the host's `maity` by its absolute path.** On an ssh
  host the runner looks `maity` up on `agent_path` once per connection
  (`targets.pin_maity`) and writes that path into the hook and the loop
  (`Ssh.maity_path`); a host without it, or with a path that is not plain
  (`/` and `A-Za-z0-9._+-`), is refused. Locally the hook already is
  the runner's own interpreter by its absolute path.
- **An old or unknown version is refused where the sandbox could run.**
  `require_sandbox` has three values (`capabilities.sandbox_refused`):
  `true` refuses any start without the sandbox, `false` none, and unset
  (the default) refuses Claude Code when its sandbox tools are there but
  its version keeps the sandbox off (older than 2.1.295, a prerelease of
  it, or unknown; `capabilities.sandbox_held`, `Target.held`). A host
  without the tools runs unsandboxed as before, with a warning.
- **A version is a token of its own.** The probes read a version only
  between the start, a blank, `(` or `v` and the end, a blank, `)`, `,`
  or `;` (`capabilities.VERSION`). `2.1.295+` or `2.1.295-_dev` is no
  version: the probe keeps the whole line, which the gate reads as
  unknown, so the rule above refuses it.

**Reason:** the sandboxed session relies on the hook for its `maity`
line (63492c65). Managed settings win over the session's `--settings`
file, so a switch there would start the session without the hook, and
an unsandboxed start of a version that the gate refuses was the same
outcome by another way. Refusing, with the reason in `check` and the
log, leaves the choice to the operator: remove the switch, update Claude
Code, or opt out with `require_sandbox = false`. A name looked up on a
session's PATH is whatever comes first there; the path found once on the
configured `agent_path` is the one `check` reported.

**Rejected alternatives:**
- Starting unsandboxed when hooks are switched off: the session would
  run with the exclusion for `maity` and no hook, or without its sandbox
  where the operator installed one.
- Checking the settings only in `maity runner check`: managed settings
  change without the runner; they are read at every start.
- Making `require_sandbox = true` the default: a host without
  bubblewrap, where Claude Code has never run sandboxed, would stop
  starting agents with no change on it.
- A `PATH` check at each start instead of the absolute path: the hook
  runs with the session's environment, not the one checked.
- Taking the leading part of a malformed version token as the version:
  `2.1.295+` would pass the gate as `2.1.295`.

## Placed agents open their pull requests through `maity gh`, pinned to the clone's repository

**Id:** 9f43804d-cfdc-4496-b07b-b01e65fc6410
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on req-mvywh1gykvpg (option o1), 2026-11-11, recorded on card tsk-3qb19f0r56zf: placed agents open their pull requests themselves, scoped to the project's repository; the shape (a maity command instead of gh rules) by the lead on #1663, messages 113208 and 113224
**Revisit when:** the runner gets a forge credential per placement or per repository (tsk-anek9pkb5r82), or a harness's sandbox can deny reading a file to one command and allow it to another

Every placed session denies `gh` and `gh *` (`adapters.GH_DENIED`);
under the harness's sandbox, which the rules rely on, no placed session
runs gh (without it, see the second known gap). A repository's grant sets `pull_requests = true`,
and its agents then run `maity gh pr create` and `maity gh pr view`
(`maity/ghpr.py`). Like every `maity` call, it runs outside the harness's
sandbox. It takes only the options it knows, with no abbreviations, so
bundles such as `-dR` are refused. It does not take `--repo`, a URL, or an
option gh would read a file with. It starts gh with `--repo=` set to the
repository the runner recorded at launch (`pull_requests`, in its directory for the agent
since 818828af; `.git/maity/pull_requests` before), and
it gives gh only the environment it names (`ghpr.ENV_PASSED`: `HOME`,
the locale, the temporary directory, proxies and certificates), so no
variable names another repository, configuration or login, or a program
to start. gh runs in an empty directory of its own, never in the clone,
and maity names the branch (`--head`, the pull request to view), read
with its own pinned git, so gh's git reads nothing of the clone's `.git`.
maity reads a `--body-file` itself and passes it to gh on standard input. `maity gh pr view` never
uses gh's own text view: without `--json` it asks gh for a fixed list of fields (`ghpr.VIEW_FIELDS`,
plus `comments` with `--comments`) and prints them as text itself. gh's text view builds its query
by gh's version, and an older gh (2.46, a distribution's package) asks for `projectCards`, which the
forge now refuses, so every plain `gh pr view` failed on such a runner (the E2E of #1663). An `allow` entry naming gh is not applied:
`maity runner check` warns about it and names `pull_requests`, and the
runner still starts. Codex gets neither `allow` nor `pull_requests`
(79837674-493a-43dd-8670-e8b163309bca): it cannot honour a command
allowlist, and its `maity` runs inside its sandbox, while `maity gh` is
set up only for a `maity` outside it. Without its sandbox, such a grant
refuses the start.

**Reason:** before this, an agent could push but could not open its pull
request, and the card's test needs it to. The forge login on the machine
belongs to the account all agents push as, and it reaches every
repository that account may. Only code that parses the command can pin
the repository. A glob rule cannot.

**Rejected alternatives:**
- gh allowed through `allow` rules, with `--repo`, `-R` and `--hostname`
  denied (this PR's first version): `-dR other/repo` bundles the flag past
  every glob, `gh pr view <URL>` names another repository, and `-F` reads
  any file the agent names, so a rule never pins anything (review of #1663).
- For `pr view`, requiring a newer gh in `maity runner check` instead of
  naming the fields: runners use their distribution's gh, and the next
  field the forge retires would break the text view again (#1663's E2E).
- Granting all of `gh`, or api.github.com: `gh api` and any tool could
  then act on every repository the account reaches. The sandbox network
  gets no api.github.com, and `maity runner check` warns when a grant
  adds it.
- Hiding gh's configuration from the sandbox (denyRead): `git push` in
  the sandbox authenticates through `gh auth git-credential`, which reads
  that file, so pushing would stop working.
- A per-repository token: none exists on the machine, and arranging one is
  the operator's business (tsk-anek9pkb5r82).
- The runner or a person opening the pull request for the agent (the
  fallback offered for the test): the maintainer chose that agents do it
  themselves.

maity reads a body file through descriptors only. It works out on the
text alone which names lead from the clone's root to the file, refusing a
path that leaves both the clone and the placement's scratch
(783e476c-3975-43de-9c4e-7c3a5da57be7). It opens the clone's root (for
a file in the scratch, `/`), then each
directory on the way from the one before with `O_NOFOLLOW` and
`O_DIRECTORY`, refusing a link and the clone's `.git` (by device and
inode, so a case-insensitive volume's `.GIT` is caught too). It opens the
last name with `O_NOFOLLOW` and `O_NONBLOCK` and reads only a regular file
with one link. Reason: maity runs outside the sandbox, and any name maity
looks up twice can point elsewhere the second time. This covers every
directory and file below the clone's root. `.git` itself is the one
`clonecheck.opened_git` checked against the inode the runner recorded at
the start (#1683): the walk compares with that descriptor, and the
runner's record is read through it, never through the name `.git` again
(round 5 had exchanged `.git` for a decoy). Round 3 swapped a
directory between a check and an open by name. Round 4 exchanged a
directory with a link between the open, the resolve and the stat, and
maity read the clone's credential and a file the sandbox hides (review
of #1663, rounds 3 and 4). Where the system has no `dir_fd` or
`O_NOFOLLOW` (Windows), maity takes no body file at all and points to
`--body`. Rejected: checking the resolved path and then opening it by
name (racy); opening once and then comparing the inode with the path
resolved again (the path can point elsewhere at each lookup); asking the
kernel for the descriptor's path (`/proc/self/fd`, `F_GETPATH`): it
differs per system and its parents would still be checked by name or
need the same walk; refusing every link in the clone (a work tree may
hold links); a lock (sandboxed code does not take it); on Windows,
keeping the check by name (it is racy, and refusing costs only the
switch to `--body`).

**Known gap:** the login stays readable in the sandbox, because `git push`
needs it. So code that an allowed command runs (tests, builds) can read
it and push to any repository the account may push to. `maity gh` closes
gh's paths and keeps the forge's API out of the sandbox, but not this one.
It stays open until tsk-anek9pkb5r82 lands, either as a push outside the
sandbox with the same pin or as a credential scoped to the project's
repository.

**Known gap:** without the harness's sandbox (opencode, Claude Code off
Linux or without bwrap and socat), nothing keeps repository code from
running gh or rewriting `.git/maity/pull_requests`: the deny rules are no
boundary there. On an ssh target, gh must be at the path the runner found
on its own host, or `maity gh` refuses.

Closed gap (review of #1663, round 5): under the harness's sandbox, code
that can write the clone's root could exchange `.git` with a directory
of its own, and with it the record that names gh. Since #1683
(tsk-er1nymh4te1h) the runner records `.git`'s inode at launch and maity
opens `.git` once from the root's descriptor, refusing a different one;
`maity gh` reads the record and compares the walk through that
descriptor.

## A placed lead merges, edits, readies and reads CI through `maity gh`, gated by a grant and the hub's role

**Id:** fada2113-3767-4eb2-a26a-c21e693a4e1a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on req-ynxe01x39drc (option A), 2026-11-20; card tsk-pvnj16k8d6m0 and the lead's approval of the plan with its decisions (edit lead-only, whole-line footer filter, 400-line log cut), 2026-11-20; the arbiter's go on req-mvdwmhwymgyb for the files list in docs/api.md; card tsk-bmknv06ps0c6 and the lead's approval of its plan (the edit through one REST PATCH), 2026-11-21; `cli/src/maity/ghpr.py`
**See:** runner.md#placed-agents-open-their-pull-requests-through-maity-gh-pinned-to-the-clones-repository — 9f43804d-cfdc-4496-b07b-b01e65fc6410 — as of 2026-11-20
**Revisit when:** the runner gets a forge credential per placement (tsk-anek9pkb5r82), the hub gives roles a right that names merging, or placed authors need `pr edit` on their own pull requests

A lead that runs as a runner placement cannot run gh, by the same
design as every placed session (9f43804d). `maity gh` therefore takes
five more shapes for it: `pr merge <number> --match-head-commit <sha>
--subject <text>` with a body, a squash merge only; `pr edit` for the
title and the body; `pr ready`; `run list --commit <sha>`; and `run view
<run id> [--job <id>] [--log-failed]`. They are built like `pr create`:
strict options, every value as `--name=value` after maity checked it,
the repository from the runner's record, gh in an empty directory with
the same environment. Two gates come on top, both checked before a body
is read or gh starts. The runner writes a `gh_lead` record only for a
grant with `lead = true` beside `pull_requests = true`, and never for
Codex. maity reads the caller's role from the hub at each call: `GET
/me` names the member the session's credential is, and that member's
view gives `role_base`, which must be `manager` (a project role built
on manager counts, by the lead's decision on #2054: a project role
grants no more than its base, context/trust.md). It also refuses when
the hub does not answer, when `/me` does not list this project, for an
isolated member, under `--for`, when `MAITY_STATE_DIR` is set under a
placement, and when the runner's directory for the agent is not
`…/agents/<this placement>/git` reached with no link, all three this
user's and none writable by group or others. In every layout the runner
makes all three as the agents' user, this session's uid (`single`, ssh:
the runner's own user; `agent_user`: the agent user, in whose own
`~/.maity-runner` they lie), and keeps `agents/` at 0700 itself
(`supervisor.agent_dir_for`, `AsUser.tighten`), since a mkdir with
parents leaves it at 0775 under a umask of 002. The session that signs is read through the clone's checked
`.git` descriptor, `maity/`, `state.json` and the credential each opened
from the one before without following a link (`state.read_placed`,
`Session.through`), before any client exists; where that cannot be done
(Windows) the lead commands are refused. Everything gh prints is cleaned
before it reaches the terminal. These checks are defence in depth where
the harness's sandbox holds (Claude Code, Codex); on agy and opencode,
no boundary between placements, they are none either.

**Reason:** a lead merges, fixes pull request bodies, readies drafts and
reads CI every day. As a placement it had only `pr create` and `pr view`,
so each merge waited for a person. The forge login on the machine is the
operator's and reaches every repository, so the boundary has to be maity
parsing the call, as for `pr create`. The role comes from the hub
because local state and the resume packet on disk are not proof of the
role now. A role taken away must stop the next merge, and a lead's
membership is the hub's to say. Merging requires the full head sha:
gh then refuses a head that moved after the lead read it, so a push
that lands after the review cannot be merged unseen. It also merges only
directly: a base branch with a merge queue hands the method and the
moment to the queue, so the squash and the head named would be a flag,
not the outcome (review A1804 of #2054). maity therefore reads GitHub's
merge-queue state for the pull request first, through one fixed GraphQL
query (`isMergeQueueEnabled`, `isInMergeQueue`, `headRefOid`; the owner,
name and number as variables), and refuses unless both queue fields are
false and the head is the one named, or when it cannot read them.
GraphQL answers for a queue whatever required it and for every reader. The body filter drops only whole `Co-Authored-By:` and
"Generated with" or "Generated by [tool](link)" lines (the second the
form the containers append). That is what the project leaves out of squash commits, and
rewriting text inside a line could change what an author wrote. An edit
is one REST call through gh, `PATCH repos/<owner>/<name>/pulls/<number>`
with only the title and the body as JSON on stdin, the owner and name
from the pinned repository alone and a branch turned into its number
first (tsk-bmknv06ps0c6): `gh pr edit` in older gh asks the forge for
`projectCards` (Projects classic), which the forge refuses, so the edit
failed and set nothing (lotse#ajwe on #2073, 2026-11-21), while the REST
call does not depend on gh's GraphQL field set. The
log is cut to its last 400 lines because a failing job's cause is near
its end, and a whole log would flood the lead's context.

**Rejected alternatives:**
- Letting a merge queue take the merge: the queue chooses the method and
  merges later, so neither the squash nor the expected head would still
  be maity's to promise.
- The queue fields through `gh pr view --json` (round 5): gh does not
  export them there, so a standard gh refused the read and maity every
  merge (review A1804 of round 5).
- The base branch's ruleset rules (`gh api …/rules/branches/<base>`,
  round 6): they show a queue a ruleset requires but not one a classic
  branch protection rule requires, and not seeing a queue is not knowing
  the merge is direct (review A1804 of round 6). Reading branch
  protection as well needs admin rights on the repository.
- `gh pr edit` for the edit (as #2054 shipped it): its GraphQL field set
  depends on gh's version, and older ones ask for `projectCards`, which
  the forge refuses (tsk-bmknv06ps0c6).
- A lowest gh version named by `maity runner check` instead of fixing the
  edit: runners with a distribution's older gh would lose `pr edit`
  altogether, and the forge may drop more fields that a newer gh still
  asks for.
- `pr edit` for every placed author under `pull_requests`: gh's login is
  the operator's, so maity cannot tell whether a pull request is the
  caller's own, and a body edit is a write on someone else's pull
  request. Left for a card of its own with its own boundary.
- `gh pr checks` for CI: the project reads a required check from the
  pull request's own newest run on the exact head, never the commit's
  checks (context/process.md, the CI watcher). `run view` gives the
  run's jobs by name instead.
- The role from the resume packet or the clone's state: a demoted lead
  could go on merging until its next resume.
- The role of the member id the clone's state names
  (`GET …/members/{id}`), this PR's first version: that read answers for
  whichever id is asked, so the id would come from local state, not from
  the identity the hub authenticated (review A1720 of #2054). `GET /me`
  answers for the credential that signed the call.
- The literal role name `manager` only (this PR's second version): a
  project role built on manager would then be refused although it holds
  manager's rights, unlike every other right in the project.
- Reading the state by path and comparing it with the placement clone's
  `.git/maity` afterwards (this PR's third version): the state and the
  signing credential were already read when the comparison ran, so it
  proved nothing about what was read (review A1738). The descriptor read
  is taken only for the lead commands; the other commands keep loading
  their session by path, which is wider than this card.
- A runner's agents directory compared with its default state directory,
  or recorded a second time by the runner: a runner with another
  `state_dir` would be refused, and a second record only moves the trust
  (the lead's choice on the security leg's P3); the path is checked for
  links and for its directories' modes instead.
- `agents/` and `<placement>/` allowed to be the runner's user's, `git/`
  alone this user's (this PR's fourth version): it rested on the belief
  that in the `agent_user` layout the runner makes the two upper
  directories as itself; it makes all three as the agent user, in that
  user's own `~/.maity-runner`, so the exemption fit no layout and let
  another local user own `<placement>/` (review A1758; the lead withdrew
  the acceptance).
- Allowing the group-write bit a umask of 002 leaves on `agents/`, as the
  runner's own-file check does for the ssh host's files: the runner makes
  and tightens `agents/` to 0700 instead, so the check stays strict.
- Allowing `--admin`, `--auto`, another merge method or
  `--delete-branch`: none of them is needed for the daily work, and each
  widens what a placed lead can do past the review and CI gate.
- A grant per placement instead of per repository: the runner's grants
  are per repository. The per-member gate is the hub's role, which an
  admin changes without touching the runner.
- A `maity runner check` warning for a lead placement whose member is
  not a manager: the check reads no member from the hub, so it cannot
  know. The role is checked at each call instead.

## Under a placement maity writes a file only inside the clone, and reads its records from the runner's directory

**Id:** 818828af-24cb-4b2a-be54-1bff2211ccb0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-bg81webs911m (the rule, and the lead's order for a first pull request with `files get` and the recorded git only), 2026-11-13; the shapes and the rejected alternatives below are the author's, not yet reviewed
**See:** runner.md#placed-agents-open-their-pull-requests-through-maity-gh-pinned-to-the-clones-repository — 9f43804d-cfdc-4496-b07b-b01e65fc6410 — as of 2026-11-13
**See:** runner.md#maity-takes-the-clones-git-only-as-the-directory-the-runner-recorded — e44249f8-15d0-4104-8940-5ff48decd412 — as of 2026-11-13
**Revisit when:** a harness runs `maity` inside its sandbox; the runner stops setting `MAITY_GIT_PRIVATE`; someone needs `--force` under a placement

Under a runner placement (`MAITY_PLACEMENT`) `maity files get` writes
only inside the runner's clone, never under its `.git`
(`maity/inclone.py`). The walk is the one `maity gh` uses for its body
file, moved there: the path is worked out on its text, then the clone's
root is opened and each directory after it from the one before, without
following a link, and refused when it is the `.git` that
`clonecheck.opened_clone` checked. The walk starts at the root's
descriptor that check opened (without following a link) and read `.git`
from, so a directory put at the clone's path after the check is not
written to (review of #1749). The bytes go into a file of maity's own in
the last directory, without a name where the system has `O_TMPFILE`, and
that open file is what gets the name: linked through `/proc/self/fd`, or
by its own name compared by device and inode before and after the link,
or, without hard links or once its name is gone, copied from maity's own
descriptor into an exclusively created file. Either way it counts as
saved when the name holds that file (device and inode) at the moment of
that check; a failed copy is left under its name and named in the
refusal, never removed by name, since POSIX cannot remove a name only
while it holds a given file. A named staging file (no `O_TMPFILE`) is
removed afterwards only when its name still holds maity's file at that
check, made while maity's descriptor is still open; a name that holds
another file by then, or none, is left untouched, and a left name is
noted on standard error. A saved file is not refused over it. Linking fails on an existing name, so no file is replaced
there, `--force` included; another file that took the temporary name
never gets the target's, and one that took the target's name during the
copy is refused and left alone (review of #1749). Without `-o` the
file goes to the clone's `.git/maity-files/`, outside the work tree,
opened from the checked `.git` (d1d6b49d in commands.md). Where a name
cannot be opened through a directory's descriptor (Windows), no file is
saved; `-o -` is not offered either since 783e476c. Outside a placement
nothing changes.

The git maity starts under the runner and the record `maity gh` reads
(`git`, `pull_requests`) are written by the runner into its directory
for the agent, the one `MAITY_GIT_PRIVATE` names (`clonecheck.runner_record`),
not into the clone's `.git/maity`. A record left there is not read. Only
Codex keeps them in `.git/maity` (the value `clone`): its `maity` runs
inside its sandbox with the agent's own rights. A session started by an
older runner has no record there and runs no git until its placement is
restarted.

**Reason:** under a placement `maity` runs outside the harness's
sandbox and reads and writes paths the agent names. A path must not take
it where the sandbox keeps the agent out, and a program maity starts must
not be named by a file inside the clone, which the agent writes. The
runner's directory for the agent is outside the clone, hidden from the
sandbox, and already checked by maity before git's own repository is made
there.

**Rejected alternatives:**
- One helper that checks a path and returns it (`placement_path`): the
  path is looked up again by name when it is opened, and between the two
  a directory can become a link (rounds 3 and 4 of #1663's review).
- Replacing an existing file under `--force` when maity wrote it: what
  maity wrote would need a record of its own, kept where the agent cannot
  write. The agent can remove the file itself, inside its sandbox, and
  then fetch it again.
- On Windows, checking the path by name: it is racy (the body file's
  choice); `-o -` remained until 783e476c.
- Confining the writes alone and keeping the records in the clone:
  without the harness's sandbox the clone's `.git/maity` is writable
  anyway, and every other path maity writes for the agent would have to
  be closed first.
- A variable naming the git program: it would work too; the directory
  holds both records in one place the runner already makes and maity
  already checks.

**Known gap:** a file with a name can be opened by that name. Where the
system has no `O_TMPFILE` (macOS, some file systems), maity's file has a
name in the clone until it is linked, and code running as the same user
can write into it between the digest check and the link. In the copy
without hard links the target has its name while maity writes it, and
such code can write into it as well. The target is then the file maity
made, with those writes: its identity is checked, its content is not.
The identity check itself is a snapshot: such code can rename or replace
the name after it, before maity reports the file saved. The same holds
for the staging file's removal: between the check and the unlink such
code can put another file under the staging name, and that file is then
removed. POSIX has no unlink only while a name holds a given inode; the
window is accepted, since the name is maity's own unpredictable one in
the clone and code that can put a file there can remove it itself.

## Under a placement maity reads a file for the agent only inside the clone or the placement's scratch, and writes no attachment to standard output

**Id:** 783e476c-3975-43de-9c4e-7c3a5da57be7
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** card tsk-bg81webs911m (the rest of the card: every path maity reads for the agent, the lead's list of those paths and of the ways out to test (an absolute path, `../`, `.git/maity/`, a symbolic link, a hard link), and the order to offer no `-o -` under a placement), 2026-11-13; the shapes and the rejected alternatives below are the author's, not yet reviewed; the scratch paragraph from card tsk-dpe3d5g5eh4k (the lead's go, 2026-11-17)
**See:** runner.md#under-a-placement-maity-writes-a-file-only-inside-the-clone-and-reads-its-records-from-the-runners-directory — 818828af-24cb-4b2a-be54-1bff2211ccb0 — as of 2026-11-13
**See:** runner.md — 03fee927-492a-4983-a4cc-738d192e26f0 — as of 2026-11-17
**Revisit when:** a command gets a file option that does not read through `cli._placed_read`; an option needs more than 10 MiB; a placed agent needs to name a file with more than one hard link; a harness runs `maity` inside its sandbox

Under a runner placement every file maity reads for a command goes
through `cli._placed_read`, which reads it with `inclone.read` from the
root and `.git` that `clonecheck.opened_clone` opened and checked once:
`files put`, `--attach`, every `--…-file` option (`--body-file`,
`--summary-file`, `--last-file`, `--next-file`, `--review-file`),
`api --json`, `--action-body`, the jour fixe's `--file`, `profile
avatar`, `memory add --soul`, `task restricted set --file` and
`join --join-file`; `maity gh`'s body file already did. It must be a
regular file in the clone, outside `.git`, reached without a link, whose
opened inode has exactly one link, of at most 10 MiB (1 MiB for an
avatar). A refusal is a usage error before any call; the one of
`task restricted set` names no part of the path, as its other refusals
do not. stdin (`-`) stays where an option takes it. Text is decoded as
before: UTF-8, newlines as `read_text` gives them, a leading byte order
mark dropped. Where a name cannot be opened through a directory's
descriptor (Windows), only stdin is taken. `maity files get -o -` is
refused under a placement before any call, so the walk into the clone is
the only way maity writes an attachment there.

A path outside the clone is read on the same terms from the placement's
scratch, when the runner recorded one (`clonecheck.SCRATCH_RECORD`, in
its directory for the agent, beside the `git` record): the walk then
starts at `/`, each directory on the way to the scratch and below it
opened without following a link. The record,
not `MAITY_SCRATCH`, names it, and a record pointing into the clone or
not an absolute path is ignored. Writing (`files get -o`) stays inside
the clone.

**Reason:** maity runs outside the harness's sandbox, and what it reads
for a command can go to the hub (an upload, a message, a request body).
A path the agent names must not let it read what the sandbox hides from
the agent: this clone's `.git/maity`, another clone's credential, the
runner's state. A hard link in the clone to such a file is the same
inode under a second name; refusing every opened file with more than one
link catches it whatever and wherever the other name is. Standard output
goes wherever the command line sent it, which maity cannot see.

**Rejected alternatives:**
- Comparing the opened file's device with the clone root's: a hard link
  is always on the same device, so it would pass.
- Refusing a hard link only when its other name lies outside the clone:
  the other names of an inode cannot be listed.
- Keeping `-o -` when standard output is a terminal: a harness reads a
  command's output through a pipe, so it would be refused anyway, and a
  terminal check says nothing about where a redirect points.
- Checking the path by name first (`realpath` and a prefix test) and
  then reading it: the name is looked up twice (as in 818828af).
- Taking the scratch from `MAITY_SCRATCH`: the agent sets its own
  environment, so the variable could name any directory its user may
  read, another clone's included.

**Known gap:** a file whose other name is removed between the open and
the link count reads as one link; that takes write access to the
directory of that other name.

## The walk to the placement's scratch passes through the directories above it, never reads them

**Id:** 0bab0087-a0f1-4809-9e5c-31c878f35d11
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** cards tsk-x6wvgna4w95x and tsk-vt5hye6a6k6v; reviews A1715 and A1716 of PR #2053; live probe A1718 in a Codex placement on maity 0.1.0a17 and a second Codex placement's refusal, 2026-11-20; `cli/src/maity/inclone.py`. The refusal and its message are confirmed by the probe; the choice of fix and the rejected alternatives are the author's, not yet reviewed
**See:** runner.md#under-a-placement-maity-reads-a-file-for-the-agent-only-inside-the-clone-or-the-placements-scratch-and-writes-no-attachment-to-standard-output — 783e476c-3975-43de-9c4e-7c3a5da57be7 — as of 2026-11-20
**Revisit when:** a harness's sandbox hides a directory on the way to the scratch from search, not only from reading; a harness that runs `maity` inside its sandbox is supported on a system without `O_PATH`

On the way from `/` to the recorded scratch, `inclone._walk` opens each
directory with `O_PATH | O_DIRECTORY | O_NOFOLLOW` (Linux), from the one
before, checks that it is a directory, and reads nothing from it. Below
the scratch, and for the file itself, nothing changes: each directory is
opened without following a link, and the file must be a regular file with
one link. Where there is no `O_PATH` (macOS) the directories above the
scratch are opened for reading, as before.

**Reason:** Codex runs `maity` inside its bwrap sandbox. Its profile hides
the workspaces root (`"none"`) and opens the scratch again (`"write"`), so a
path still leads through the hidden directories, but they cannot be opened
for reading. The walk opened each of them for reading, so under Codex every
file in the scratch was refused with "the way to the placement's scratch
(…) is not plain directories", absolute or relative, for `--body-file` and
`--attach` alike (probe A1718). The agent's own shell had just written the
file through the same path, so the session holds the right to search those
directories. `O_PATH` needs that right and nothing more.

**Boundary:** a descriptor opened with `O_PATH` reads nothing. A link on the
way is still refused: with `O_DIRECTORY` and `O_NOFOLLOW`, Linux refuses it
(ENOTDIR), and a check that each step is a directory catches anything else.
Under Claude Code, maity runs outside the sandbox as the agents' user. Passing through a directory gives it nothing that this
user's own path lookup does not already give, and the file checks are as
before.

**Rejected alternatives:**
- Starting the walk at the recorded scratch path by name (`os.open(root,
  O_NOFOLLOW)`): the kernel follows a link in every component but the last,
  so a link above the scratch would no longer be refused.
- Making the scratch's parents readable in the Codex profile: every Codex
  session could then list the workspaces root and the other placements'
  scratch names, which the profile hides on purpose.
- Telling Codex agents to keep such files in the clone: a review's evidence
  or another head's clone in the work tree is what the scratch exists to
  keep out of commits (docs/agents.md).

## The runner nudges an interactive agent that stopped listening, then resumes it

**Id:** 20fe2a78-29ec-49fa-b428-0a785db95d14
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-cbz655mvt4ss (the lead asked for it after both placed agents on a VM went silent at once on 2026-11-12 while their placements reported `running`; the "no client attached" guard confirmed by the lead); `cli/src/maity/runner/supervisor.py` (`_idle`), `tmux.py`; docs/api.md §15.14
**Revisit when:** the hub's half of §15.14 (check-in, nudge) is routed, or a harness gives the runner a machine-readable signal that its session waits for input

An interactive agent listens by running `maity wait`. When that ends (a
full disk, a provider limit, a turn the agent closed), the agent sits at
its prompt, its process stays alive, and its placement stays `running`.
Nothing noticed it: the hub's check-in and nudge are not routed yet, and
§15.14 had the runner leave an interactive session alone. Now the runner
looks at each interactive session once a minute.
- **Not listening** means two things together: no process below the
  harness but its own helpers (neither a `maity wait` nor a tool, however
  quiet), and the pane unchanged. The first version looked only for a
  missing wait, and a review showed a quiet build would then be ended. An
  unsandboxed Claude Code at its prompt has no child process; every tool
  runs as one (seen with `ps` on a live session). A sandboxed one on Linux
  keeps a `socat UNIX-LISTEN:` bridge per proxy for its whole life
  (fkyb's review, from the sandbox runtime's source, not seen live): such
  a bridge is not counted as work, or the check would never fire under
  the sandbox the runner turns on wherever bwrap and socat are present.
  Only a socat with the bridge's whole shape counts: it listens on a
  socket whose own name is `claude-http-<hex>.sock` or
  `claude-socks-<hex>.sock` and forwards to `TCP:localhost:<port>` (or
  127.0.0.1; the runtime adds keepalive options after the port, so only
  the address before the first comma is compared), as the sandbox runtime
  builds it. A first version compared the whole word and took the real
  bridge for work (fkyb's review). Rejected: `/claude-`
  anywhere in the path, which exempted a service in a `claude-`
  directory (hcrb's review); any `claude-<word>-<id>.sock`, which
  exempted an agent's own service named like that (v5vp's review); an
  agent's own socat on another socket is a tool, and so is any process
  below a bridge but its own forks (hcrb's review).
- A missing process alone is not enough: an agent writing a long answer
  has no child process for a while. An unchanged pane alone is not enough
  either: an agent waiting for events shows nothing new. The processes
  come from `ps -A -ww`. The pane is compared by hash, so its text is never
  kept, logged or sent.
- Idle ends are counted on their own and in a row toward `crash_cap`,
  then hold the placement as `failed`/`hung`/`idle`: a hung session never
  ends quickly, so the quick-exit crash count never saw it. Rejected:
  counting them within `crash_window`. One end takes 40 minutes with the
  default times, and the window is 30, so five never fit and the cap was
  never reached (fkyb's review). A `maity wait` seen below the harness
  starts the row over: the resume worked.
- The baseline after a nudge is the pane with the line typed and before
  Enter, so whatever the harness does with the line, a reply included, is
  a change: a session must never be ended 10 minutes after a genuine reply
  (the lead's decision on hcrb's review). Rejected: measuring after Enter,
  at the next look (the first version) or at the first capture after
  Enter (round 2); a reply already on screen by then became the baseline.
  If the line does not show within the short window (a stalled screen, a
  slow read), Enter waits for the next look, which measures the pane
  first. Rejected: keeping the hash from before the nudge, which took the
  late echo for an answer and nudged forever; and taking the baseline at
  the next look after Enter had gone out, which made a reply the baseline
  again (both fkyb's reviews). A line that has still not shown at that
  look keeps its Enter back until a look sees it, so its own late echo is
  never an answer; one that never shows within `reply_within_minutes`
  ends the session. A nudge counts toward the cap only once an answer to
  it is seen: a change of the pane after its Enter, or a process the
  harness started. A look the runner cannot use (a person attached, an
  unreadable pane) is no answer, and the reply time runs on. A held-back
  line dropped before its Enter does not count; its line may still be
  in the input, so the next nudge sends it rather than typing a second
  copy behind it. Rejected: counting at typing, which ended a session for
  "three answered nudges" after zero Enters (fkyb's review); counting at
  Enter, which did the same after three unanswered Enters with a person
  attaching in between (v5vp's review); clearing the input before typing,
  which could throw away what a person typed there. Once a person was
  attached, the input is theirs: the next nudge types afresh behind
  whatever they left instead of pressing Enter on it alone (fkyb's
  review); like any nudge, it then sends a draft they left together with
  its line, and a second copy if they left the line as it was.
- Since Enter itself changes a live harness's pane, only a session that
  does not react at all is ended after `reply_within_minutes`. An agent
  that answers every nudge but never goes back to its wait would be
  nudged forever, so after three answered nudges with no `maity wait`
  seen in between its next quiet spell ends it, without another nudge.
  Rejected: resetting on any change without a cap (an agent that only
  answers stays deaf for good).
- A new generation clears the resume flag: it may change the harness, the
  model or the mode, and §15.14 wants a fresh session then.
- A live tool below the harness keeps the session out of the check for as
  long as it runs. An interactive session gets no `tool_call_max_minutes`
  backstop (`hung`/`tool`) yet: a tool that hangs forever there is not
  ended. Rejected: treating a quiet tool like an idle prompt, which ended
  a long build after 40 minutes.
- After `hang_after_minutes`, the runner types one fixed line into the
  pane, and only while no client is attached: a person at the pane would
  have the runner type into their session. After `reply_within_minutes`
  more, it ends the session and reports `exited`/`hung`/`idle`. It
  starts the session again with Claude Code's `--continue`, so the
  conversation survives. Until the hub carries the owner's
  `health.settings` to the runner, the minutes are the defaults, 30 and
  10.
- Anything the runner cannot read (no `ps`, a tmux error) starts the
  count again. The runner never acts on a guess.
- `-ww`: without a terminal, ps cuts the command line at 80 columns, and
  `maity wait` behind a long venv path fell past the cut. The real-tmux
  test found it.
- Rejected: restarting at once without the typed line. A typed line costs
  the agent nothing, while a restart costs it its tool state. For Codex
  and opencode a restart still starts a new conversation.
- Rejected: asking the hub whether the instance listens. The runner's
  credential reads no members, and the processes are on the runner's side
  anyway.

## A reset starts the generation's first session fresh, and `sessions` goes only to a hub that knows it

**Id:** a5205d13-c553-4d3b-aedf-f0f134c3011c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-r4apvj4kbf3a (the runner honours a reset for every harness it supports and reports it); card tsk-dqxmc1f0cxj0 (an adopted session counted, the count reset on every new generation); docs/api.md §15.6, §15.7, §15.14
**See:** https://github.com/oliver-zehentleitner/maity — 37b4b9a1-a0f0-4f6f-bb26-b607590ffa18 — as of 2026-11-20
**Revisit when:** the runner keeps the harness's session id and resumes on every start (§15.14), or the hub's report model stops refusing unknown fields

A placement whose `fresh_session` is true starts the generation's first
session fresh: the start prompt, no `--continue` (Claude Code) or `-c`
(Antigravity), whatever resume the record holds. Codex and opencode resume
nothing at an interactive start, and a supervised loop starts with its
`first` command, so they are fresh already. A later resume in that
generation, after a `hung` end, continues the new session. The runner logs
`reset: a fresh session, the last one not resumed` and counts fresh starts
in the record's `sessions` (a start whose `Launch.resumed` is false),
reset by a new generation. It is not part of the report's key: it moves
at a start, and the `running` report after it carries the new count. It sends
`sessions` only when the placement it read carries a `fresh_session` key.

**Reason:** today a new generation already clears the resume flag, so a
reset changes no argv yet; the explicit check keeps a reset fresh once a
restart resumes the session, as §15.14 wants, and covers a record that
holds a resume from a state file. The hub's report model is strict: an
older hub answers `invalid` to a report with `sessions`, every tick, so
the field waits for the hub that carries `fresh_session`, which takes it.

**Rejected alternatives:** sending `sessions` always: a runner newer than
its hub would have every report refused. A field of the runner's own for
"reset done": `sessions` is already in the contract and says the same. A
fresh start for the supervised loop's retries after a failed first run:
the loop's `again` continues the clone's latest conversation, which after
a first run that failed before writing one is the conversation before the
reset; left as it is, since the loop's handling sits beside a change in
flight there (#2016) and the same holds for every restart today.

An adopted live session of the current generation counts as one started
(`sessions` at least 1), and every path that takes a new generation sets
`sessions` back to 0, the `target_unknown` refusal included (card
tsk-dqxmc1f0cxj0, from the review of #2020). A runner restarted inside a
reset's generation before a save carried the count to actual.json, or
without actual.json, would otherwise hold 0 for a session that runs, and a
`hung` end later would start fresh a second time instead of resuming;
saving the count at the start alone would still miss a lost actual.json.
The refusal's report would carry the generation before's count.

## A stopped agent's clone stays for its retention time, then the runner removes it

**Id:** 161d5507-5b44-45d6-8bec-cacd58de58a2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-34gb7frfbsk7 (disks of runner machines filled with the clones of agents that no longer ran there); the owner's answer to req-fdfb49yzqnhv, verbatim: "ich bin für eine zeitspanne die der workspace noch liegen bleiben darf zb 3h oder 24h falls doch noch was daraus benötigt wird oder "sofort entfernen" das soll eine option sein bitte"; the lead's decision on unsaved work (2026-11-12); docs/api.md §15.5
**Revisit when:** a placement can save an agent's unsaved work somewhere other than its clone, or the owner asks for unsaved work to go too after the retention time

Partly built (tsk-34gb7frfbsk7): this records the contract's decision. The
hub's part is in; the runner's clock, checks and removal, and the
dashboard's view, follow in their own pull requests.

A clone stays on the runner until the operator removes it, and the
clones of agents that no longer run there fill the disk. The contract
has a stop start a retention time, chosen per placement (`immediate`, `3h`,
`24h` by default, `7d`); after it, the runner removes the clone, and a
start within it continues in the same clone. The time is the owner's
answer: something in the clone may still be needed.
- Unsaved work (uncommitted or untracked files, unpushed commits,
  stashes) keeps the clone however long the retention, shown with its
  size, and the owner can have it removed by hand. The runner never
  throws away work nobody has looked at. Rejected: removing it anyway
  once the time is up, because the owner chose the time; the owner's
  reason for the time was that something might still be needed.
- Rejected: removing the clone only when the placement closes (the first
  draft). The owner asked for a time after a stop, and a stopped
  placement that is never deleted would keep its clone for good.
- Rejected: one fixed time for every placement. The owner asked for a
  choice, with "remove immediately" among it.
- The runner removes only on the hub's word (a stopped or closed
  placement it lists), never because a placement is missing from its
  list, and under the checks of `maity runner gc` plus a process check
  and stashes, because the service runs on while it removes. The removed
  clone's credential is revoked, so nothing carries over to a later
  start.
- Removal by hand is for people only (the profile's owner or a project
  admin): it deletes unsaved work. A request stays until a report names
  it, so a report the runner decided before seeing it cannot drop it
  (spq4's review). The runner reads `remove_requested_at` on every
  placement it may remove, active under `desired: stopped` or closed, and
  names it in its report; `removed` clears the request whatever it names,
  because nothing is left to remove. `removed` is accepted in any state of the placement,
  because a start that arrives during the removal would otherwise find
  neither a credential nor a way to rejoin.
- A closed placement stays listed to its runner as long as its clone is
  held, not for 30 days: a kept clone outlives any window, and it is the
  clone that fills the disk. The same holds for people (`closed=true`
  in the dashboard's list) and after a detach: the runner still reads
  and reports on those closed placements, or the clone would be
  orphaned on its disk (v5vp's review). After a detach, the workspace
  report still reaches a placement whose `removed` this runner already
  reported, though `closed=true` no longer lists it: a retry whose first
  answer was lost must get its `200`, or the runner retries for ever.
  Rejected: taking `not_found` after its own `removed` as done, since the
  runner cannot tell it from a wrong id or a placement it never had.
- Each workspace report names its clone (`workspace_epoch`, raised when a
  removal is taken), and `removed` is final per clone. Rejected: one
  final `removed` per placement. A placement that starts again gets a new
  clone, so either its own later removal could not be reported, or a
  late retry about the old clone could revoke the new clone's
  credential (v5vp's review). The runner makes a removed clone's
  successor only after the hub took the `removed` report, under the epoch
  of that answer; a clone made earlier would carry the old epoch and all
  its reports would be dropped (spq4's review). A placement that
  continues another placement's clone reports under its own epoch, the
  one it read when it started there. Rejected: carrying the older
  placement's epoch over, which could make its first report later than
  the hub's and so `invalid` (spq4's review).

## The runner installs and updates the harness tools and maity, only where its owner allows it per tool

**Id:** 4c984f97-09b8-479b-bd1a-f56bb41057fd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-29nmydbzrg5z, the owner's request and agreed shape (chat 2026-11-12, opt-in per tool, the vendor's installer in the runner user's space, no swap under a running agent, a kept previous version, versions on the runners tab with "Update now", maity updated the same way with the older sessions restarted); the owner's answers of 2026-11-12: req-r2egh0ry0c4c (older sessions restart at their next idle point; answer event 119533), req-vpcfh15h247c (local target only, ssh targets reported; answer event 119538), both relayed by the lead in 119605; docs/api.md §15.16
**Revisit when:** an ssh target's owner wants the runner to manage its tools, a harness tool ships without an installer the runner can run in the user's space, or a tool's update needs a step only a person can do

The harness tools are built (tsk-29nmydbzrg5z, runner part; how they are
fetched and checked is the next entry); `maity`'s own update and the
dashboard follow in their own pull requests.

Operators kept the runner's tools and `maity` current by hand, and
sessions started by an older `maity` stayed on it until someone
restarted them. The contract lets the runner do it, per tool and only
when its owner says so in the runner's configuration (`install`,
`update = "daily"`); without that it touches nothing, as before. The
shape is the owner's (confirmed), and so are two points he answered for
this contract: a session an older `maity` started restarts at its next
idle point, never mid-step, and the runner manages only its own machine,
reporting what it finds on an ssh target. The parts below that are not
in his words are this design's (inferred).

- **The installer is fixed in the runner's code**, per tool, never
  taken from the configuration or the hub: a path or URL in a file the
  runner reads would let whoever can edit it run any program as the
  runner user, and the hub never grants anything to a runner. A new
  tool's installer is a code change with its own review.
- **Beside, never under.** A newer version goes in beside the one in
  use and is used from the next start of a session, and only after it
  answered its version; a running session keeps what it started with.
  The previous version stays for `maity runner tools rollback`, a local
  command, because a rollback is the operator's call on the machine.
  An older version goes only once no running session started from it,
  and an install and a rollback hold the tool's lock across processes,
  so neither overwrites the other's `state.json` (a4xv's review).
- **A start keeps the tool its gate looked at.** The start gate reads the
  harness's probe, sandbox and held state once, under the supervisor's
  lock, and the launch uses that same view (`GateView`), held through
  the clone and join, which can take minutes. A rollback in that window
  therefore still starts the version just left, under the sandbox
  decision made for that version, and the session then counts as one
  on an older version. Rejected: a fresh look under the lock right
  before the tmux start, refusing or retrying when it changed; it would
  add a second gate whose answer can differ from the first, for a
  window that ends in a consistent start either way (47me's review).
- **Only a runner that manages a tool reports tools.** The runner sends
  `capabilities.tools`, and runs its tool thread, only when its
  configuration sets `install` or `update` for some harness. A hub from
  before §15.16 refuses the unknown field and the runner would stop at
  `hello`, and the CLI ships before such a hub is deployed everywhere;
  a runner that manages nothing has nothing to report, so it stays as
  it was. The lead chose this over waiting for the hub release
  (confirmed, lotse 139517). Rejected: a retry of `hello` without
  `tools` after the refusal, and reading the hub's version first; both
  add a second path to every start for a gap that closes with the next
  hub release.
- **"Update now" is read, not pushed.** The hub stores the owner's
  request on the runner, and the runner's tool thread reads `GET /runner`
  at most once a minute while a tool is updated daily, apart from the
  event wait so an install of minutes never holds it up. Every event
  belongs to a project, and a runner without an attached project would
  never hear one, so a poll within a minute is what an event would give
  anyway. The hub drops a
  request only when the report that ends the attempt names it, its
  `requested_at` exactly as the runner read it, as a removal by hand is
  closed (161d5507). Rejected: dropping it once a report shows a check at
  or after it, which compares the runner's clock with the hub's, and the
  signing window allows minutes of skew: a check decided before the
  request could erase it (v5vp's review). One exception, without the
  token: a report that lists the tool with `update: "never"`, leaves it
  out or carries no `tools` drops its request, since that runner will
  never carry it out and the owner would see it standing for nothing
  (vhqe's review). Because equality decides, no two requests for a tool
  may share a time: the hub makes each one strictly later than the last
  it issued for that tool, a mark it keeps after the request is settled
  or dropped. Rejected: taking that floor from the standing request and
  the runner's last report, since a late or missing report moves it back
  and a reissued time is settled by an old report (hcrb's review), and a
  runner's far-future value would push it (47me's review).
- **A rollback is a state of its own.** After `maity runner tools
  rollback`, the tool reports `rolled_back` while the version in use is
  older than `latest` (a second rollback back to `latest` reports
  `current`), and while it is, the runner does not take the version it
  left, or one that failed its version answer, on its own again; only a
  newer version ends it.
  Otherwise the daily check would undo the operator's rollback the same
  day (v5vp's review).
- **Only the owner asks**, and only for a tool the runner says it
  updates (`updates_off` otherwise): the configuration is the owner's,
  and project admins who use the runner do not change its software.
- **Logins stay the owner's.** A tool that needs a login after its
  install is reported `login_needed` and offered to no placement until
  then; the runner never reads, writes or asks for a credential.

Rejected:
- An installer named in the configuration: the reason above.
- Swapping a tool in place and restarting every session at once: an
  agent mid-step would lose its work, and the owner ruled out a swap
  under a running agent.
- An event per attached project for "Update now": the reason above.
- Project admins asking for an update: the runner's software is its
  owner's, as its configuration is.
- Restarting the older sessions at once, after the stop grace: faster,
  but it can end a task mid-step (the owner's answer).
- Installing on ssh targets too: a vendor's installer would run on a
  machine whose owner did not set it up for that, with more ways to fail
  (the owner's answer); a later card can add it.

## The runner takes a tool only as an exact vendor release it can check, and keeps it beside its state directory

**Id:** 841ed5f8-10e3-4682-8d8e-76adf97edf15
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-29nmydbzrg5z, the lead's rules for the installers (2026-11-14: no script fetched and run unless its version is pinned, the vendor's package at an exact version, the vendor's checksum checked, refuse rather than fall back, what each tool verifies written down for the security team) and the lead's approval of the agent_user scope (2026-11-14); the vendors' install scripts and documentation read 2026-11-14 (Claude Code's signed `manifest.json`, release key fingerprint 31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE; Codex's GitHub releases with a SHA-256 `digest` per asset and a sigstore bundle); `cli/src/maity/runner/installers.py`, `tools.py`, `keeper.py`; updated 2026-11-17 when opencode was offered (req-g4d2cskx6zxv): it still has no installer, and the "not offered to placements yet" wording was dropped
**Revisit when:** a vendor stops publishing the checksum or signature used here, the runner gains a sigstore verifier, or an operator of the agent_user layout needs managed tools
**See:** runner.md#the-runner-installs-and-updates-the-harness-tools-and-maity-only-where-its-owner-allows-it-per-tool — 4c984f97-09b8-479b-bd1a-f56bb41057fd — as of 2026-11-14

The contract says "the vendor's installer"; the runner runs none of the
vendors' install scripts. It downloads one exact version's release
straight from the vendor and refuses it unless the vendor's own check
passes, before anything is unpacked or run:

- **Claude Code:** the release's `manifest.json` must carry a valid
  signature by Anthropic's release key, checked with `gpgv` against the
  key shipped inside `maity` (the fingerprint above is pinned; nothing
  fetched at install time is trusted as a key). The manifest must name
  the version asked for, so an older signed manifest cannot be replayed,
  and the binary must match its SHA-256 and size. A host without `gpgv`
  is refused.
- **Codex:** the release tagged `rust-v<version>`, neither draft nor
  prerelease, its package tarball matched against the SHA-256 that
  GitHub's release API states, from the one expected URL, unpacked with
  tarfile's `data` filter. Not checked: the sigstore bundle, since the
  runner has no verifier for it; that trust is GitHub's and the vendor's
  account over HTTPS.
- **opencode** has no installer: its install route offers no checksum,
  so the runner installs and updates no opencode (the operator installs it).

The versions live in `~/.local/share/maity-runner/tools`, not in the
state directory: the state directory is hidden from every sandboxed
command (supervisor.private_paths), and Codex's sandbox starts the Codex
binary and its bundled helpers inside the sandbox. In the agent_user
layout `install` and `update` are refused at load for now: the agents
run as another OS user, and the runner user's own directory is not
theirs to rely on. A managed session is started with the tool's own
self-update switched off (`DISABLE_UPDATES` for Claude Code,
`check_for_update_on_startup = false` for Codex), so only the runner
changes the version.

**Rejected alternatives:**
- Running the vendor's install script (`curl … | bash`): it would run
  whatever the vendor's server sends that minute, with no version the
  runner chose (the lead's rule).
- Trusting the manifest's or the API's checksum alone: for Claude Code
  the signature is offered, so it is used; the checksum is only as good
  as the document that carries it.
- Fetching the release key at install time: a key from the same server
  as the manifest proves nothing about the manifest.
- Falling back to an unchecked download when `gpgv` or a digest is
  missing: refused instead (the lead's rule).
- Keeping the versions under the state directory: the harness sandboxes
  could not run them.
- A world-readable tools directory for the agent_user layout now: only
  built when someone needs it (the lead's decision).

## Placed sessions commit as the runner's `[git]` identity, set through the environment

**Id:** ad2b5d74-ce26-40cc-ae2c-50f22c3e008a
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-z27pwcfr03wm (the runner test of 2026-11-11 on #1592: `git commit` in a placed Claude Code session failed with "empty ident name (for <maity-runner@…>) not allowed", the checks were refused); the lead's decisions on that card, message 123366, 2026-11-13; the review of #1735 (the control-character finding) and the review lead's fix order, message 123623, 2026-11-13; git 2.53 in a scratch repository with an empty `HOME`, no system configuration and a read-only `.git/config`, 2026-11-13; `cli/tests/test_session_identity.py`
**See:** runner.md#git-in-a-sandboxed-session-works-without-writing-gitconfig — 82e70deb-7cf9-4ea1-be2f-137186b20b2d — as of 2026-11-13
**Revisit when:** a placement should commit as an identity of its own (per agent or per repository), git stops letting `GIT_AUTHOR_*`/`GIT_COMMITTER_*` override the configuration, or a harness filters these variables out of the commands it runs

Every placed session gets `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`,
`GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL` from the runner
configuration's `[git]` table (`name`, `email`, both required in it), for
every harness and layout (`adapters.git_identity`). Without the table the
default is the generic `Maity agent <maity-agent@invalid>`, and
`maity runner check` warns while a harness other than `stub` is configured.
`config user.name` and `config user.email` are no longer among the granted
git subcommands. It is the session's default, not a lock: `git commit
--author` sets another author, and a program the session runs (an allowed
check) can start git with an environment of its own. Both values are
refused when the configuration is read unless `str.isprintable()` accepts
them.

**Reason:** the session had no identity anywhere. Its environment is a
fixed few variables, the agents' user on the runner VM has no
`~/.gitconfig` and an empty passwd name, and the agent could not set one:
the sandbox keeps `.git/config` unwritable and `git -c` is denied. The
variables win over every git configuration, so a plain `git commit` works
with nothing written anywhere. They also close a gap the card did not
name: in the `single` layout the agents' home is the operator's, whose
`~/.gitconfig` is not among the hidden secrets, so placed sessions there
had committed under the operator's personal address. The generic default
keeps every runner working while naming no one; `.invalid` (RFC 2606) can
never be a real address, so no owner's or team's address is built into an
open-source default. Setting the team identity is each deployment's
operator step. The `config user.*` grants became pointless (the variables
win) and, without a sandbox, wrote `.git/config`.

**Rejected alternatives:**
- `user.name`/`user.email` through `GIT_CONFIG_COUNT`, beside the settings
  already passed that way: it works as well, but `GIT_AUTHOR_*` and
  `GIT_COMMITTER_*` are git's own variables for this and win even over a
  `-c user.name`; `--author` still changes only the author.
- Letting the agent set its identity (`git config` writable, or `-c`
  allowed): `.git/config` and `-c` can run a program outside the sandbox
  (82e70deb).
- The team identity as the built-in default: every operator's runner would
  commit under the maintainer's address unless they noticed (the lead's
  decision, option a of three).
- Requiring `[git]` with no default: an existing configuration would stop
  passing `check` and `serve` on upgrade.
- An identity per repository grant: not needed now (the lead's decision).
- Refusing only control characters (category Cc: C0, DEL, C1) in the two
  values, the first fix the review of #1735 asked for: it would keep format
  characters such as U+200C, which some names use, but also invisible ones
  in every commit. The review lead preferred everything `str.isprintable()`
  refuses; an identity for agents does without U+200C. The first version
  refused only C0 and DEL in the name and nothing in the address, so a NUL
  passed `check` and failed only when a session was started (review of
  #1735).

Which checks a repository's grant allows stays the operator's choice in
the runner configuration; the contract only says the hub neither sees nor
checks it (§15.1, §15.3). `docs/runners.md` shows the entries for a Python
repository. Rejected: the repository declaring its own checks in a
committed file. The project's committed configuration is never loaded
(adapters' module docstring), because a branch could then widen its own
grant. `git apply` stays ungranted (the lead's decision).

## Files on the agents' side are read bounded, and a clone only in the start task

**Id:** 096be6c1-a4b4-400e-9e1d-f876c8000edd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-vyp87d3hnbem (the lead's security review of 2026-11-13, item 1, and the fix it named); implementation 2026-11-14; the anchored walk from a code review of the change on 2026-11-14, which reproduced a `.git` swapped for a link between the listing and the read
**Revisit when:** the runner reads the agents' side through a channel of its own instead of running commands there, or the supervisor stops holding one lock for every placement
**See:** runner.md#the-limit-file-is-read-on-the-agents-side-by-the-runners-own-module-not-by-dd — aa29acab-65eb-4f60-a8da-ee284877266f — as of 2026-11-14

Every file the runner reads from the agents' side (a clone's
`.git/config`, its `.git/info/exclude` and `.git/maity/state.json`, a
pane log, the agents' user's Claude Code settings, and the managed
settings the hook check reads) goes through
`AsUser.read`, which reads the way the limit file was already read
(`limitread`): no link followed, no wait on a FIFO, a regular file only,
at most a limit the caller names. Every read is anchored at a directory
the runner knows (`under`: the clone, the agents' file directory, the
agents' home, the managed settings' own directory): that directory is
opened, each directory below it is opened from the one before with
`O_NOFOLLOW | O_DIRECTORY` (`dir_fd`), and the file from the last of
them, so no link anywhere below the anchor is followed. In the runner's own process that is `limitread.take`;
through sudo or on an ssh host it is the runner's own module there
(`--under`, `--bytes`, `--offset`), within `READ_TIMEOUT`, a timeout
turned into an `OSError` every caller handles. The supervisor's tick,
which holds the lock `update` and the reports wait on, reads only the
runner's own workspace record of an existing clone (`workspace.owned`);
the clone's `.git` is checked (`clonecheck`) and then read for its origin
by the start task (`workspace.prepare`).

**Reason:** the agents can replace any of these files, and the clone's
`.git` too, between two looks at it. A read that follows a link to an
endless device, waits on a FIFO or takes a huge file into memory, done
while the supervisor holds its lock, stops every placement on the runner,
not only the one whose clone it is. One way of reading for everything on
that side means a new caller cannot pick the unsafe one by accident.
`O_NOFOLLOW` covers only a path's last name: an agent could swap its
already listed `.git` for a link to a directory outside the clone, and a
read of `.git/config` by its full path would take that directory's file
as the clone's. Walking down from the anchor refuses that swap.

**Rejected alternatives:**
- `tail -c` and `head -c` through sudo, as the logs were read: bounded in
  size with `head`, but they follow links and wait on a FIFO, and a
  killed `sudo` leaves them waiting.
- `dd` with `iflag=nofollow,nonblock`: macOS's `dd` has no `iflag`
  (aa29acab).
- Comparing `.git`'s inode with the one seen at the listing (as
  `MAITY_GIT_INODE` does for git's own runs): it covers `.git` alone,
  not the other directories on the way to a log or the limit file, and
  leaves a window between the comparison and the open.
- Walking from `/` without following any link: refuses ordinary
  configured paths that run through a link (`/home` on some systems,
  macOS's `/var`); the anchor is the runner's own path, only what lies
  below it is the agents'.
- Keeping the origin check in the tick with a safe read: still a command
  through sudo or ssh, up to its timeout, under the lock every placement
  needs.
- Falling back to `tail` where an ssh host's `maity` is older than the
  runner's: it would keep the unsafe read alive. Such a host reads
  nothing, as for the limit file, and an existing clone there is refused
  as `origin_mismatch` until the host's `maity` is updated.

## A placement's log is held to `log_keep_bytes` by its own writer, keeping the newest half

**Id:** 9bdc2aa5-b5dc-489a-bda6-db7c06d3eed5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-vyp87d3hnbem (the lead's security review of 2026-11-13, item 2: `limits.log_keep_bytes` was documented and never applied); implementation 2026-11-14; cutting to the newer half instead of rotating confirmed by the lead on 2026-11-14; the real-size check from a code review of the change on 2026-11-14, which reproduced another writer's append taking the log past the limit
**Revisit when:** someone needs a pane's older output after the limit, or tmux's `pipe-pane` gains a size limit of its own

tmux's `pipe-pane` hands a pane's output to `maity.runner.logcap` (`maity
runner logcap` on an ssh host) instead of `cat >>`. The module runs on the
agents' side, appends to `<agent_files>/logs/<placement>.log`, and when
the next chunk would take the log past `limits.log_keep_bytes` it first
cuts the file to its newest half, through a copy renamed over it. A
write that fails (a full disk) drops that chunk and the module reads on.
The module is the log's only writer, but the log lies on the agents'
side, where they can write it too: before every write, and once more
when the pane ends, it takes the file's real size (`fstat`), not its own
count, and reopens the path when the file there is no longer the one it
holds (device and inode). Bytes another writer appends count at the
module's next write, so the log holds the limit after each of its
writes and when it ends.
`maity runner logs --follow` starts again at the log's beginning when it
finds the log shorter than what it showed.

**Reason:** the writer is the only process that sees every byte as it
arrives, so it holds the limit without a second process watching the
file. A private count of its own bytes missed what others append, and a
log renamed away and replaced kept receiving output in the old file. Keeping the newest half leaves the output that
explains a failure, which is what the log is read for, and bounds the
disk to one limit per placement.

**Rejected alternatives:**
- Rotating to `<placement>.log.1`: twice the limit on the disk, and a
  second file `logs` would have to know about.
- The supervisor cutting the logs on its tick: a command through sudo or
  ssh per log and tick, racing the writer's appends.
- Emptying the log when it is full: drops the output that led up to the
  limit, usually the part someone wants to read.

## A placement's scratch lives beside its clone, one per placement, and is never kept

**Id:** 03fee927-492a-4983-a4cc-738d192e26f0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's go on the design note for tsk-dpe3d5g5eh4k, 2026-11-17; the maintainer's card after the agents' VM filled with leftovers, 2026-11-16; the lead's decision on the gc refusal rules and the runner's own end after the reviews of #1915, 2026-11-17; the lead's decision that gc reads the sessions first, after the review of #1917, 2026-11-17
**See:** runner.md — 783e476c-3975-43de-9c4e-7c3a5da57be7 — as of 2026-11-17
**Revisit when:** agy's sandbox is shown to write somewhere the runner can name per placement; opencode's adapter grants its file tools a writable path outside the clone; a harness needs its scratch reported to the hub

Each placement gets `<workspaces>/<project_id>/.scratch/<placement id>`,
passed as `MAITY_SCRATCH` with `TMPDIR` inside it, but `TMPDIR` only when
a Unix socket still fits under it: Claude Code binds its sandbox socket
`claude-socks-<16 hex>.sock` (34 bytes) under `TMPDIR`, a socket path holds
at most 107 bytes on Linux (103 on macOS), and a deep workspaces root made
it 117 in cli 0.1.0a16,
so no Claude Code placement's sandbox started. Where `<scratch>/tmp` leaves
no room the session gets no `TMPDIR` at all (it starts from a clean
environment, so tools use `/tmp`) and only `MAITY_SCRATCH` names the scratch
(`adapters.scratch_tmpdir`). Under the default root `~/maity-workspaces` that
is the usual case: a home longer than `/home/ab` already leaves no room. The runner removes it
when the placement closes; after a stop it is to go on the clone's clock,
which is not built yet (tsk-34gb7frfbsk7). Nothing
in it counts as unsaved work, and only the operator sees its size and
removals (`maity runner status`, `removed.jsonl`). `maity runner gc
--scratch` removes one only when the hub's list says its placement is
not active and the sessions it read first hold none of it; sessions it
cannot read keep every scratch. It is the rule the service applies when
a placement closes. Only Claude Code and
Codex get one, the harnesses whose sandbox the runner can open for it;
agy's sandbox is not shown to write there, and opencode's adapter has
no proven writable scratch (its file tools are denied paths outside the
clone, `external_directory: deny`).
maity reads a named file there as in the clone, which widens the
clone-only read (the entry under See) to the path the runner recorded.
`maity runner scratchop` works only on a placement's scratch below the
root it is given, and `maity runner` refuses its operator commands to a
placed agent; an agent's
scratch of another placement of the same OS user stays reachable until
the operation has a runner-only entry (tsk-54492gk4xp69).

**Reason:** reviews and tests left evidence folders, temporary clones and
virtual environments in the agents' shared home, which no removal of a
clone reaches. A known place per placement can be removed when the
placement ends without asking what in it matters.

**Rejected alternatives:**
- Inside the clone: git sees it, and the clone's removal keeps a clone
  with untracked files as unsaved work, so the leftovers would keep
  the clone.
- Inside an `antigravity` workspace folder: the runner refuses a folder
  holding anything but `repo`, since agy loads what is there.
- One scratch per clone instead of per placement: a placement that
  continues a clone would inherit another's leftovers, and the scratch's
  end is the placement's.
- Its size in `workspace_outcome`: a new field for something the
  operator alone acts on; the lead kept the hub out of it.

## A placement's test slots and test cluster live in its own scratch, so its slots bound only its own runs

**Id:** 2ce039de-925e-4244-9a90-8336e9375d68
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-w7qtcbzcshn9, filed by the lead from tsk-deaaanqsq5e2 (placed sessions bypassed `tools/run_slot.sh`'s slots), 2026-11-20; security's rejection of a directory shared by a user's placements and the lead's choice of the scratch, 2026-11-20; the security review of #2032 (other placements' scratch denied, scram with a per-placement password kept outside every sandbox), 2026-11-20; red team's probe that Claude Code's sandbox refuses a Unix socket in the own scratch, and the lead's ruling to leave the cluster out of Claude Code placements and not to allow Unix sockets there, 2026-11-20
**See:** runner.md — 03fee927-492a-4983-a4cc-738d192e26f0 — as of 2026-11-20
**Revisit when:** a runner-mediated slot lock bounds heavy runs across placements (tsk-w7dx3h9mn8dp); each placement runs as its own OS user; `with_postgres.sh` moves its socket out of the data directory; the test cluster reaches Claude Code placements over TCP (tsk-zk2cse7s2rf7); a Codex session is found unable to start the cluster

The runner sets `MAITY_RUN_SLOTS_DIR=<scratch>/slots` for every placement
with a scratch beside its clone, and `MAITY_RUN_NAME=<handle>#<instance>`
(the handle alone before the hub has named an instance; a value of any
other shape is left out). The session gets `MAITY_PG_DIR=<scratch>/pg` and
its password only where `<scratch>/pg/.s.PGSQL.<port>` fits a Unix socket
path (`adapters.pg_dir`, room for a five-digit port), as `TMPDIR` does (the
entry under See). Otherwise the runner logs that it left them out. A
Claude Code placement gets no test cluster yet (`adapters.gets_test_cluster`):
on Linux its sandbox refuses `socket(AF_UNIX)` with EPERM (seccomp, before
any path is checked), even inside the placement's own scratch, so the
runner draws no password file for it and starts it without `pgenv`. macOS
is untested and treated the same. Its test slots work as everywhere. A
cluster over TCP on 127.0.0.1 for these placements is tsk-zk2cse7s2rf7.
Codex keeps the cluster, though no Codex session has started one yet. No path
is opened in any sandbox beyond the scratch, which the sandbox already
writes and which goes when the placement closes. Within a placement,
`with_postgres.sh` keeps reusing its own cluster across runs.

Two hardening steps keep the scratch the placement's own:
- **Other scratches denied.** Every other placement's scratch is listed at
  the start (`supervisor.other_scratches`) and joins the private paths, as
  the other clones' credentials do. Claude Code denies them (`denyRead`,
  `denyWrite`). In Codex they stay inside the hidden workspaces root, so
  `outermost` leaves them out of the profile. A listing that cannot be
  completed refuses the start. The list covers the scratches that exist at
  the start. One made while a Claude Code session runs is a known residual,
  tracked as tsk-rbys2j9q0m48: that session can read it, but live probes
  showed it can neither write it (the sandbox writes only its own paths)
  nor connect to that placement's cluster socket (the sandbox refuses
  every Unix socket, its own included). agy and opencode are not kept out
  by these rules.
- **Password-protected cluster.** The cluster takes a password, which
  `with_postgres.sh` gets as `MAITY_PG_PASSWORD` and uses to make the
  cluster with `scram-sha-256`. The runner draws it once per placement into
  `<workspaces>/.maity-pg/<placement id>` (scratchop `pg_make`: 0600,
  created exclusively without following a link, never overwritten, removed
  at the close). That holder is 0700, outside every scratch and clone, and
  at a fixed path, so every sandbox is denied it from its first start; a
  placement made later adds no path to deny. The session never reads the
  file. The runner starts it through `pgenv`, which reads the password
  outside the sandbox and sets it, with `MAITY_PG_DIR`, in the session's
  process environment, never on a command line or in tmux's environment
  (`launch.env` reaches tmux as `-e`). Both are set or neither, so a
  cluster with `trust` is never made in a scratch. `pgenv` is a module the
  runner starts with its own interpreter, never a `maity runner`
  subcommand: an agent's `maity` runs outside its sandbox, and `pgenv`
  starts any command it is given. So placements on an ssh host, whose
  interpreter the runner does not know, get no test cluster yet.

The password keeps out a same-user process that can reach the socket path
but not the session's files or process environment. A fully unsandboxed
process of the same user can read the session's environment, and the
password does not claim to stop it.

**Reason:** the scripts' default, `~/.local/state/maity/`, is outside what
either sandbox writes, so placed sessions ran their heavy suites without a
slot and without a line in the slot log. Placements of one OS user serve
different projects and must stay apart, so a cluster or a slot file must
not be writable by two of them. A writable data directory lets its writer
plant PostgreSQL configuration (`archive_command`, preloaded libraries,
include files) that runs when another session starts the server, and
shared lock files allow squatting. The scratch is already per placement,
0700, made without following a link and removed at the close, so it adds
nothing to what security reviews.

The cost: slots now bound one placement's runs only. They no longer queue
the heavy suites of different placements on one machine. That is left to
a slot lock the runner holds and agents cannot write (tsk-w7dx3h9mn8dp).

**Rejected alternatives:**
- One `<workspaces>/.runs` shared by a user's sandboxed placements (the
  first shape of this card): rejected by security for the reasons above.
- A new `<workspaces>/.runs/<placement-id>` per placement: the same
  lifecycle as the scratch, plus a second directory to make, grant,
  remove and collect. Its only gain is a socket path about 20 bytes
  shorter.
- The scripts' default under `~/.local/state/maity/`: that directory also
  holds `MAITY_STATE_DIR` credentials of agents joined by hand, so it
  cannot be opened to a sandbox.
- A new password at each session start: the cluster outlives a restart,
  so each start would have to reset the role's password (`postgres
  --single` with the server stopped) and could break a run still using it.
  One password per placement needs neither.
- The password file in the placement's own scratch, read by the session:
  the scratch is not denied to a session that started before it existed.
- Denying the whole workspaces root and re-allowing the own clone and
  scratch: it rests on an allow inside a deny that is not shown to work in
  this sandbox, and the own credential's deny would sit inside it.
- A non-superuser cluster role: the hub's own tests run as a superuser
  (`hub/tests/test_db_role.py`).
- Claude Code's `allowAllUnixSockets`, so its sessions could bind the
  cluster's socket: on Linux it turns the sandbox's whole seccomp filter
  off, not only the socket rule (red team's probe). A cluster over TCP on
  127.0.0.1, which the sandbox allows, comes in tsk-zk2cse7s2rf7 instead.

## A sandboxed Claude Code placement starts only where the host gives its seccomp step what it needs, and `runner check` probes that the step applies

**Id:** c774c132-1f84-4b61-bb01-13a6ee7ca7e3
**Type:** decision
**Type:** constraint
**Status:** open
**Evidence:** inferred
**Source:** card tsk-rbys2j9q0m48, filed from the security review of #2032, 2026-11-20; the ops team's read-only reading of the Claude Code 2.1.328 and 2.1.329 binaries (minified): the supported machines, the helper's resolution and the built-in helper handed in by file descriptor, the warning sent to the sandbox runtime's debug logger, 2026-11-20; `/proc/self/status` of an unconfined shell on a test host (`Seccomp: 0`, `Seccomp_filters: 0`), 2026-11-20; the ops team's live run of Claude Code 2.1.329 on an x64 Linux runner host (a throwaway session, no placement): headless with `SRT_DEBUG=1` the filter was applied, the interactive interface showed no sandbox-runtime line while it ran, 2026-11-20; the lead's decision for the static preflight, the headless probe in `check` only and dropping the pane check, 2026-11-20; the security review of #2063 (the pinned socket settings, the user settings refused) and the lead's decision to warn, not refuse, on a version whose probe has not passed, 2026-11-20; the security delta review of #2063 (the settings read only at a start), 2026-11-20; the code review of #2063 and the review lead's decision (an ssh target's kept preflight forgotten while unreachable, the settings read before the probe), 2026-11-21
**See:** runner.md#a-placements-test-slots-and-test-cluster-live-in-its-own-scratch-so-its-slots-bound-only-its-own-runs — 2ce039de-925e-4244-9a90-8336e9375d68 — as of 2026-11-20
**Revisit when:** every move of the Claude Code version pin (`capabilities.CHECKED`): run the `check` probe, and read the supported machines and the probe's two lines from the binary again; Claude Code shows the block's state itself or fails closed without the step; it is verified whether Claude Code reloads user settings during a session; each placement runs as its own OS user

**Decision.** On Linux, before every start of a sandboxed Claude Code
placement (`Supervisor._refusal`) and in `maity runner check` (local and
each ssh host), the runner reads as the agents' user the machine
(`uname -m`; `x86_64`/`amd64` as `x64`, `aarch64`/`arm64` as `arm64`, in
lower case) and `/proc/self/status` (`capabilities.claude_seccomp`). It
starts the placement only for a machine in `CLAUDE_SECCOMP_ARCHES` (x64
and arm64) on a kernel that has a `Seccomp:` line and, from Linux 5.9, a
`Seccomp_filters:` line. Their values are the reading task's own (0 for an
unconfined shell) and are ignored, as long as they read as numbers. Any
other machine, a missing line or an answer that cannot be read refuses the
start (`harness_refused`, the reason in the log) and is an error in
`check`. An `ok` is kept per target for the service's lifetime, and
anything else is read again at the next start. That is enough for the
machine and the kernel: neither changes while the service runs, and a
reboot restarts it. Seatbelt (macOS) has no seccomp step and is not
checked.

The placement pins its socket settings and refuses user settings that would
change them. Its settings file sets `sandbox.network.allowAllUnixSockets`
to `false` (`adapters.claude_settings`); a `--settings` file wins over the
user's settings, as the runner already relies on for `disableAllHooks`.
Placements load the agents' user's settings (`--setting-sources user`), so
a sandboxed Claude Code start is refused, and `check` reports an error,
while that file carries `sandbox.network.allowAllUnixSockets`,
`sandbox.network.allowUnixSockets` or `sandbox.seccompConfig`, whatever
the value, or cannot be read as a JSON object
(`capabilities.claude_socket_settings`, read as `claude_hooks_off` reads
it, at every start). The managed settings win over the `--settings` file,
so they are read for the same keys and refused the same way, an unreadable
managed file included.

After an `ok` preflight, `check` alone (never a start) runs the installed
Claude Code once headless as the agents' user
(`capabilities.claude_socket_probe`): the sandbox on with socket blocking
left on, `SRT_DEBUG=1`, one harmless command, a bounded timeout. Its
standard error decides: the runtime's line that it applies the seccomp
filter for Unix socket blocking is `ok`; its warning that the helper is not
available is an error that the block is off; a timeout, a non-zero exit,
output that cannot be decoded or neither line is an error that the block
is not confirmed. The model's answer is not kept. Operators run `check`
after every version pin. `check` reads the hook and socket settings first
and runs the probe only while both are clean: a pass under settings that
refuse every start would be kept for a configuration no start runs with,
so none is run or kept then.

An `ok` preflight is kept in `Target.seccomp`. A local target keeps it for
the service's run; an ssh target forgets it when it turns unreachable
(`Supervisor._reachable`), because the machine that answers under that
name when it is back may be another one or run another kernel. A re-read
at every start was weighed and left out: a dropped connection is the
point where the host behind the name can change, and the reviewers chose
that cheaper refresh.

`check` keeps, per target, the Claude Code version whose probe passed in
the state directory (`capabilities.PROBE_FILE`, written with
`state.save_state` like the runner's other state files) and forgets it
when the probe does not pass. At each sandboxed Claude Code start on Linux
the service reads it (`Supervisor._probe_warning`): an installed version
that differs, or no record, is logged with a line to run `check`, once
per target and installed version for the service's run
(`Target.probe_warned`), and the start goes ahead. `check` reports the
same line as an error, so the operator sees it, when its probe does not
pass or is not run; a pass in the same run is recorded before anything is
compared, so it adds no such line. The runner installs Claude Code
itself, so refusing every start after a version pin until someone runs
`check` would be an outage.

**Reason:** every placement of a host runs as the same OS user, so the
seccomp step is the only thing between a sandboxed command and the other
placements' sockets and the agents' tmux server. A read-only path does not
stop a connect. The other-scratch residual of the entry under See (a
scratch made after a session started is readable to it, but it cannot
connect to that placement's sockets) holds only while the step runs. Read
from the binary: Claude Code supports the step on x64 and arm64 only (ia32
is named unsupported, any other machine too), and when no helper resolves
it runs the command in bubblewrap with Unix sockets open. It sends the
warning to the sandbox runtime's debug logger, which (inferred) writes only
with `SRT_DEBUG` set. So nothing a session shows says the block is off,
and only a check before the start fails closed. The static preflight sees
the host, not whether Claude Code hands its built-in helper in by file
descriptor (the other places it looks for one are empty under the runner's
native install); the headless probe shows that. It stays out of the start
because it spends a small prompt on the agents' Claude login each time.

**Open residual.** That the built-in helper is handed in is established
for 2.1.329 on x64 by a live probe on 2026-11-20; re-check on every
version pin with the `runner check` probe. A start does not run the probe,
so a host where it fails still starts placements while its preflight
passes; `check` reports it as an error.

**Open residual.** The socket-settings check reads the managed and user
settings at a start. If Claude Code re-reads its settings files during a
session, a change to the user settings made after the start, from outside
a Claude Code sandbox, is not seen until the next start.
`allowAllUnixSockets` is pinned by the placement's settings file and still
wins; `sandbox.seccompConfig` is not pinned. Whether Claude Code reloads
user settings during a session is not verified.

**Rejected alternatives:**
- Claude Code's `allowAllUnixSockets`: it turns the whole seccomp filter
  off (the entry under See).
- A preflight that looks for the helper file beside the binary and starts
  it around a socket attempt, as the nested user namespace is started: the
  helper is built into the binary, so a file lookup finds nothing on any
  host and would have refused every Claude Code placement. No command of
  Claude Code starts the step alone.
- The headless probe before every start: a prompt on the login per start,
  and a start would wait for a model call.
- Reading each session's pane for Claude Code's warning, ending the
  session and holding its binary (built first in this card), dropped for
  good: the warning is debug-only by default, so the check never fired and
  failed open, and in the interactive interface no sandbox-runtime output
  reaches the pane or standard error while it runs, even with `SRT_DEBUG`
  (live, 2026-11-20).
- Checking the values of `Seccomp:` and `Seccomp_filters:`: they describe
  the reading task, not the kernel, and are 0 on a host that supports
  filters.
- Refusing a start whose installed Claude Code is not the version whose
  probe last passed: for now. The runner installs and updates Claude Code
  itself, so every placement would stop after each version pin until
  someone ran `check`; the start warns instead.
- Relying on the placement's pinned `allowAllUnixSockets` alone, without
  refusing user settings that carry socket keys: `allowUnixSockets` and
  `seccompConfig` are not pinned by it, and the merge of the two files is
  Claude Code's, not shown for every key.

## agy and opencode are no boundary between placements of one OS user, and no deny of other scratches is written for agy

**Id:** dcd10585-3918-4bec-ae2e-6a9030597093
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** card tsk-rbys2j9q0m48, filed from the security review of #2032 (items for agy and opencode, with the opencode wording), 2026-11-20; the agy settings the runner writes (`adapters.antigravity_settings`) and the agy settings entry of this file (a read deny seen to hide `.git/maity` in a test, a write deny's reach unknown)
**See:** runner.md#a-sandboxed-claude-code-placement-starts-only-where-the-host-gives-its-seccomp-step-what-it-needs-and-runner-check-probes-that-the-step-applies — c774c132-1f84-4b61-bb01-13a6ee7ca7e3 — as of 2026-11-20
**Revisit when:** agy documents or is shown to apply its deny rules to sandboxed commands at the OS level, writes included; opencode gets an OS sandbox (tsk-nynpvag9zvhh); each placement runs as its own OS user (req-ynkndnybr9z3)

docs/runners.md states that an agy placement's scratch under
`/tmp/maity-scratch-<uid>/` can be read and written by every other agy
placement of the same agents' user on the host, and that opencode, which
has no OS sandbox, reaches everything that user can, other placements'
scratch directories and sockets included. Neither harness is described as
a boundary between placements. The runner writes no deny of the other agy
leaves into agy's settings; nothing in the code changed for either.

**Reason:** every placement of a host runs as one OS user, so the 0700
parent and the random leaf keep out other users only; privacy between
placements can come only from the harness's own sandbox. agy's
`permissions` rules are file-tool rules. One test saw a read deny hide a
directory from agy's sandboxed commands too, but whether agy keeps its
commands out of a denied path in general, writes included, is not shown,
and agy has no documented OS-level path deny for commands. The runner's
`unshare` probe (`AGY_NAMESPACES`) only shows that the namespaces agy needs
can start, not what agy mounts in them. opencode's `external_directory`
binds only its file tools.

**Rejected alternatives:**
- A read and write deny of the other agy leaves (their names are in the
  runner's records) in agy's settings: it would read as a boundary that is
  not shown to hold for commands, and leaves made later would be missing
  from it, as with Claude Code's list.
- Moving agy's scratch back beside the clone, where Claude Code and Codex
  are kept out of it: agy's sandbox cannot write there (the agy scratch
  entry of this file).

## `runner check` starts a nested user namespace inside bubblewrap, and a refusal is an error

**Id:** 0f216e9d-1661-4887-a035-094efa301dfa
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the lead's card tsk-5b5x3k5zvg7x after the Claude Code smoke test on an Ubuntu runner, 2026-11-18; reproduced on that host the same day
**Revisit when:** Claude Code's Linux sandbox stops opening a second user namespace; the runner sets up the host's AppArmor itself (runner init); Ubuntu changes `bwrap-userns-restrict`

On Linux and the local backend only, beside finding bwrap and socat, `check` runs `bwrap … -- unshare
--user --map-root-user true` once as the agents' user and on their PATH, every command by its absolute
path. Only a refused mapping (unshare's write to `/proc/self/uid_map`,
`gid_map` or `setgroups` fails, read under `LC_ALL=C`) is an error. A probe
that times out, does not start or fails otherwise is a warning that
blames nothing, and so is a missing tool. Seatbelt (macOS) is not probed,
and neither is an ssh host yet: there the lock goes undetected.

**Reason:** Ubuntu's AppArmor profile `bwrap-userns-restrict` (seen on 26.04) lets
bubblewrap start and takes every capability from what it starts. Claude
Code's session then runs, and so does `maity`, which runs outside the
sandbox, so the placement looks healthy. But every sandboxed command fails
on the seccomp step's nested user namespace, a subagent's included. On
that host no card work is possible, so a warning would understate it.

**Rejected alternatives:**
- Read `kernel.apparmor_restrict_unprivileged_userns` or look for the
  profile file: what decides is the loaded profile's rules, and hosts
  differ in both. Starting the same nesting is the only answer that does
  not need to know why.
- Start Claude Code itself in the check: it costs a model call and needs
  the login, as with agy's sandbox.
- Every failure of the probe as a refusal: a timeout, a launch error or a
  tool missing on the agents' PATH then claimed that sandboxed commands
  fail and blamed AppArmor on a host without the lock (review of #1949).

## Claude Code's background-shell pressure reaper is disabled per placement

**Id:** b1e8643a-320b-481c-9fea-97303c6d3177
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** incident card tsk-g28jgwgxab70 on the lab host; the Claude Code changelog entry for 2.1.193 (the reaper and its opt-out variable)
**Revisit when:** Claude Code renames or drops `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP`, or the interactive placement stops listening by running a background `maity wait`

For every Claude Code placement the runner sets
`CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP=1` in the start environment, so
Claude Code's background-shell memory-pressure reaper does not kill the
placement's background `maity wait`. It is set on the base environment both
the interactive and the supervised launch inherit.

The variable turns Claude Code's memory-pressure stop off for every idle
background shell of the placement, not only that `maity wait` — the accepted
trade-off of the fix. The runner sets no memory bound of its own:
`backend.local.memory_max` is refused as not enforced yet, and the shipped
service unit sets no `MemoryMax` or ulimit, so under host memory pressure a
placement's background shells are bounded only by the kernel OOM killer and
the operator's own unit or cgroup limits. The reaper only ever stopped idle
background shells, never the Claude Code process, so keeping the placement
reachable is worth more than that stop; the lever against host memory
pressure is the agent count per host. A memory-pressure warning or capacity
guidance in the runner (incident candidate 3) is deferred, tracked with
candidates 2/3 of the incident card.

**Reason:** on the lab host a low-memory event (not a kernel OOM) had Claude
Code's own reaper — automatic memory-pressure reaping of idle background
shell commands, added in Claude Code 2.1.193 — kill the `maity wait` of two
interactive Claude Code placements. The sessions stayed `running` but stopped
listening, and their leases expired. The variable is the documented opt-out.
It is set unconditionally: older Claude Code ignores an unknown environment
variable, so no version gate is needed. It is harmless in a headless
(supervised) placement, where background tasks are already disabled
(`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`) and there is no background shell to
reap, so it is set uniformly for every placement rather than only the
interactive one.

**Rejected alternative:** detect that an interactive session is no longer
listening and restart it (incident candidate 2). Deferred — the runner
already restarts a session that goes quiet, and keeping the `maity wait`
alive is the narrower fix; the detection-and-restart path is tracked as a
separate item of the incident card.

## A placement without room under its scratch gets a short TMPDIR of its own in `/tmp`

**Id:** 893d9dfd-6d56-4a8f-b46a-5f43c9e26737
**Type:** decision
**Status:** superseded
**Superseded by:** 3c02dc4f-3189-4926-b52a-d3a2571e16a5
**Evidence:** inferred
**Source:** card tsk-0zb9mgzmbwn4, 2026-11-20 (the lead's go for this shape, with a live check before the merge); the ops live check on a runner host, 2026-11-20, with Claude Code 2.1.329 and Codex 0.171.0; card tsk-k7svzz2p4v7y, 2026-11-21 (the lead's go for Claude Code's CLAUDE_CODE_TMPDIR, no TMPDIR, no allow change); the ops live probes P1 to P3 on a runner host with Claude Code 2.1.329, 2026-11-21 (two test placements, main's own `adapters.launch`); Claude Code's documentation of CLAUDE_CODE_TMPDIR (code.claude.com/docs/en/env-vars.md); `cli/src/maity/runner/supervisor.py` (`_tmpdir`, `_remove_tmpdir`, `_remove_stale`), `workspace.py` (`OWN_TMPDIR_HARNESSES`), `adapters.py` (`session_tmpdir`, `own_tmp_env`, `own_tmp_leaf`). The live results are confirmed; the shape and the rejected alternatives are the author's and the lead's
**See:** runner.md#agys-scratch-lives-under-the-hosts-shared-temp-directory-not-beside-the-clone — 8ec06e26-42b6-47b7-9f23-2bad37da3dfa — as of 2026-11-20
**See:** runner.md#a-placements-scratch-lives-beside-its-clone-one-per-placement-and-is-never-kept — 03fee927-492a-4983-a4cc-738d192e26f0 — as of 2026-11-20
**Revisit when:** the runner pins a new Claude Code version (check again whether its sandbox lets a placement write a leaf re-opened inside a denied parent, where its sandbox socket goes, and what `$TMPDIR` its sandboxed commands get); Claude Code gives sandboxed commands a temp directory per session; the probe whether the parent's `denyWrite` is needed at all (tsk-k7svzz2p4v7y, P4) answers; placements get an OS user each

Where a Codex placement's scratch leaves no room for a Unix socket under its
`tmp`, as under the default `~/maity-workspaces`, the runner makes `tmp` in
a fresh 0700 leaf with a random name under the per-user
`/tmp/maity-scratch-<uid>` parent, the one agy's scratch uses, and sets it
as the session's TMPDIR. Codex's profile already hides that parent (`none`)
and opens this one leaf again (`write`) for the placement alone; a sibling
leaf stays hidden. The leaf is recorded like agy's (the scratch names file),
made fresh at every start, and removed when the placement closes. A leaf
that a restart fails to remove, agy's included, is kept on record
(`tmp_scratch_stale.json`) and tried again at every start and at the close,
so a failed removal orphans nothing (review A1769). If another user on the
host has made `/tmp/maity-scratch-<uid>` first, the runner refuses it and
makes no leaf, and the session starts without a TMPDIR, as before (security
review A1770). Where the scratch's own `tmp` fits, it stays the TMPDIR.
Where the leaf would not fit either (macOS with a uid longer than four
digits), and on an ssh host, the session gets no TMPDIR, as before.

A Claude Code placement gets the same leaf, but only as its
`CLAUDE_CODE_TMPDIR` (tsk-k7svzz2p4v7y). It gets no TMPDIR, and its settings
open nothing for the leaf. Claude Code writes the leaf itself, from outside
its sandbox: its own temporary files (`<leaf>/tmp/claude-<uid>/`: the project
directory, task outputs, edit diffs, plugin staging) and its sandbox socket
(`<leaf>/tmp/cc-socks/<pid>.sock`). They no longer sit in the
`/tmp/claude-<uid>` directory every Claude Code session of the user shares,
and they go with the placement.

What the placement's own sandbox sees of its leaf (ops, Claude Code 2.1.329,
2026-11-21, note nte-b77aew1t6jbn on tsk-k7svzz2p4v7y):
- Claude Code itself opens its own `claude-<uid>/` there to its sandbox, so
  under the parent's read and write deny it is visible and readable to the
  placement's own commands, though not writable.
- `cc-socks/` stays hidden.
- Another placement's leaf does not exist in the sandbox.

The 0700 mode and the random name are no boundary against an unsandboxed
process of the same OS user, which reaches the leaf as it reaches every file
of that user (review A1855). The commands its sandbox
runs keep the `$TMPDIR` Claude Code hands them: with no TMPDIR set, that is
`/tmp/claude-<uid>`, still that shared directory, writable from every such
sandbox (security's card tsk-z5c3798r1ces).

The live checks showed why it is only `CLAUDE_CODE_TMPDIR`.
- 2026-11-20: in Claude Code 2.1.329 an `allowWrite` and `allowRead` on the
  leaf beat the parent's `denyRead`, so the leaf is visible and its siblings
  stay hidden, but not the parent's `denyWrite`. The leaf is mounted
  read-only, so `echo x > "$TMPDIR/a"` and `mktemp` failed with "Read-only
  file system", and so did Claude Code's own cwd file. Codex 0.171.0 wrote
  the leaf, sealed the siblings, and refused listing the parent. 2026-11-21
  repeated it on the same version, with the same result.
- 2026-11-21: with `CLAUDE_CODE_TMPDIR` set and no TMPDIR, Claude Code's own
  files and its `cc-socks` socket went under `CLAUDE_CODE_TMPDIR`, and the
  sandbox started and ran commands. Its HTTP and mux bridge sockets
  (`claude-http-<16 hex>.sock`, `srt-mux-<pid>-0.sock`) go under TMPDIR,
  else `/tmp`. Its sandboxed commands got `$TMPDIR` = `$TMPDIR/claude-<uid>`,
  or `/tmp/claude-<uid>` with TMPDIR unset, whatever `CLAUDE_CODE_TMPDIR`
  was. Two test placements got the same directory there and could list it
  and write in it.

**Reason:** without a TMPDIR the temporary files of the session's tools went
to the shared `/tmp`. Every placement of the same OS user could see them,
possibly another owner's. Before the socket rule (#2014) they stayed in the
scratch. A leaf under the parent that the sandbox already hides gives the
same separation as the scratch, with a path short enough for the socket, and
reuses the make, record and removal code agy's scratch already has.

**Rejected alternatives:**
- Dropping the parent from Claude Code's `denyWrite`, so that its leaf is
  writable: under one OS user a sibling leaf's 0700 separates nothing, so
  every Claude Code placement could write the others' TMPDIR. The sandbox is
  never given a wider allow (the parent, or `/tmp`) to make a leaf work (the
  lead's call with security review A1770).
- `CLAUDE_CODE_TMPDIR` in the scratch, independent of the socket rule: the
  scratch is writable from the session's own sandbox, so its sandboxed
  commands could change Claude Code's own temporary files and its socket
  directory. Its `cc-socks` socket also fits there only for a short enough
  home. The hidden leaf keeps both out of the sandbox's reach and always
  fits.
- TMPDIR set to the long scratch `tmp`, now that `CLAUDE_CODE_TMPDIR` takes
  the `cc-socks` socket: Claude Code's HTTP and mux bridge sockets still go
  under TMPDIR, about 33 bytes past a path of about 83, over the 107 a
  socket path holds.
- A separate per-user parent that no sandbox hides, with random leaves:
  same-user sandboxed placements could list it and reach each other's
  temporary files, which is weaker than the scratch.

## A Claude Code or Codex placement without room under its scratch gets a private TMPDIR in a leaf under the read-denied `/tmp` parent

**Id:** 3c02dc4f-3189-4926-b52a-d3a2571e16a5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-0zb9mgzmbwn4, 2026-11-20; card tsk-k7svzz2p4v7y, 2026-11-21 (the lead's go for this step under three gates: security's agreement with the P4 reading on tsk-z5c3798r1ces, a security leg, and an ops live check on the PR's own head); the ops live probes on a runner host with Claude Code 2.1.329 and two test placements, P1 to P3 and P4, 2026-11-21; the ops live check of 2026-11-20 with Codex 0.171.0; Claude Code's documentation of CLAUDE_CODE_TMPDIR (code.claude.com/docs/en/env-vars.md); `cli/src/maity/runner/supervisor.py` (`_tmpdir`, `_remove_tmpdir`, `_remove_stale`), `workspace.py` (`OWN_TMPDIR_HARNESSES`), `adapters.py` (`session_tmpdir`, `own_tmpdir_in_use`, `own_tmp_env`, `own_tmp_leaf`, `private_tmpdir_refusal`, `claude_settings`); the security assessment on tsk-z5c3798r1ces (purple team, 2026-11-21: a private TMPDIR for every Claude Code placement, fail closed, Codex and agy unchanged); the lead's call for a strict refusal on ssh targets too, 2026-11-21. The probe results are ops' and confirmed; this exact shape (only the leaf's `tmp` opened, the leaf itself as CLAUDE_CODE_TMPDIR) awaits the ops live check on the PR's own head; the shape is the author's and the lead's
**See:** runner.md#a-placement-without-room-under-its-scratch-gets-a-short-tmpdir-of-its-own-in-tmp — 893d9dfd-6d56-4a8f-b46a-5f43c9e26737 — as of 2026-11-21
**See:** runner.md#agys-scratch-lives-under-the-hosts-shared-temp-directory-not-beside-the-clone — 8ec06e26-42b6-47b7-9f23-2bad37da3dfa — as of 2026-11-21
**Revisit when:** the runner pins a new Claude Code version (check again that its sandbox writes the re-opened `tmp`, that a sibling leaf does not exist in it, where its sockets go, and what `$TMPDIR` its sandboxed commands get); Claude Code changes how a read deny is mounted (an empty mount over the parent) or gives sandboxed commands a temp directory per session; placements get an OS user each

Where a Codex or Claude Code placement's scratch leaves no room for a Unix
socket under its `tmp`, as under the default `~/maity-workspaces`, the
runner makes a fresh 0700 leaf with a random name, with a fresh `tmp` in
it, under the per-user `/tmp/maity-scratch-<uid>` parent agy's scratch
uses. The leaf's `tmp` is the session's TMPDIR. The leaf is recorded like
agy's, made fresh at every start, removed when the placement closes, and
retried at every start and at the close when a removal fails (review
A1769). The rest is as before. If another user has made the parent first,
no leaf is made. Where the scratch's `tmp` fits, it stays the TMPDIR. Where
the leaf would not fit (macOS with a uid longer than four digits), and on an
ssh host, the session gets no TMPDIR.

Each sandbox re-opens the leaf for its own placement alone:
- Codex's profile keeps the parent `none` and opens the whole leaf
  (`write`).
- Claude Code's settings deny the parent for reading only, and open the
  leaf's `tmp` (`allowRead`, `allowWrite`). Claude Code then hands its
  sandboxed commands `$TMPDIR` = `<leaf>/tmp/claude-<uid>`, private to the
  placement.
- Claude Code's own temporary files (`claude-<uid>/`: the project directory,
  task outputs, working-directory files, edit diffs, plugin staging) and its
  sandbox socket (`cc-socks/`) go in the leaf itself, as its
  `CLAUDE_CODE_TMPDIR`, beside the re-opened `tmp`. They go with the leaf.
  Claude Code itself opens `claude-<uid>/` to the placement's sandbox for
  reading and writing, though it is in none of the runner's allows; only
  `cc-socks/` stays hidden. That was found in the ops live check on #2084's
  head (Claude Code 2.1.329, 2026-11-21, note nte-8md57zfz9zkq). It stays
  within the placement: the other placement could not reach it. It is what
  already holds wherever the scratch's own `tmp` is the TMPDIR. The lead
  accepted it (2026-11-21).
- Its HTTP and mux bridge sockets go under TMPDIR, `<leaf>/tmp`, and fit.

This holds for a placement started with this configuration. A session the
runner adopts across an upgrade, and a supervised loop that keeps running,
keeps the environment it was started with: the guard and the settings apply
only when the supervisor starts a session (review A1869). So a Claude Code
placement started before this change keeps the shared `/tmp/claude-<uid>`
until the placement itself is restarted. Restarting the runner service does
not do it, and the upgrade note and the operator guide say so.

A sandboxed Claude Code placement that gets no TMPDIR of its own fails closed.
That happens where the scratch's `tmp` does not fit and no leaf can be made:
the parent is held by another user, the leaf would not fit, or it is an ssh
target, where the runner makes no leaf. The runner then refuses the start
(`harness_refused` with no detail, as `harness_refused`'s details are a
closed contract list; the cause and the remedy, a short `workspaces` root,
in its log; `adapters.private_tmpdir_refusal`). An unsandboxed Claude Code
placement is not refused, since its commands already reach every file of the
OS user. Codex still starts without a TMPDIR there, as before. On ssh targets
this refuses what started before. No placement on the project's runners ran
on one when it was decided (the lead, 2026-11-21), and a leaf on ssh hosts
is a card of its own.

**Reason:** without this, the commands of every Claude Code session of one OS
user got the same `/tmp/claude-<uid>` as `$TMPDIR`, writable from each
sandbox, so one placement's temporary files were in another's reach
(security's card tsk-z5c3798r1ces). The probes found what separates the
leaves:
- P3: with the parent denied for writing as well as reading, Claude Code
  2.1.329 mounts the re-opened `tmp` read-only ("Read-only file system").
- P4: with the parent denied for reading only, the own `tmp` is writable
  (`touch` and `mktemp`, seen from outside). Another placement's leaf does
  not exist in the sandbox: touch, ls and mkdir give "No such file or
  directory". `/tmp` itself stays read-only. A mkdir in the parent succeeds
  but lands in the empty mount the read deny puts there, which no one
  outside or in another placement sees, and which is gone afterwards.
- So it is the read deny's empty mount, not the write deny, that keeps the
  leaves apart. Dropping the write deny opens nothing to another placement.

This supersedes 893d9dfd. That entry rejected dropping the parent's write
deny on the assumption that a sibling leaf would then be writable. P4 shows
it is not.

**Rejected alternatives:**
- The parent left in Claude Code's `denyWrite`, with only
  `CLAUDE_CODE_TMPDIR` in the leaf (tsk-k7svzz2p4v7y's step 1): Claude Code's
  own files leave the shared directory, but its commands keep the shared
  `/tmp/claude-<uid>`.
- Claude Code's whole leaf opened, as Codex's: its socket directory would be
  writable from its sandbox too, which Claude Code itself keeps hidden.
- A write deny on `<leaf>/claude-<uid>`, to keep Claude Code's own files from
  its sandbox: its sandboxed commands write there by design (in P3, with that
  area read-only, Claude Code's own cwd file failed), so it would break
  Claude Code. Not probed further.
- `CLAUDE_CODE_TMPDIR` or TMPDIR in the long scratch: the bridge sockets under
  TMPDIR do not fit (about 33 bytes past a path of about 83, over 107).
- Dropping the parent from Codex's `none` too: Codex's profile already
  re-opens the leaf under it, so there is nothing to gain.
- A sandboxed Claude Code placement with no TMPDIR of its own started anyway,
  with the shared `/tmp/claude-<uid>`: security asked for a private TMPDIR for
  every placement and no silent fall-back to the shared directory.
- ssh targets exempt from that refusal: the lead chose strict, since no
  current placement runs on one.

## `maity runner` is taken only as the first argument

**Id:** 3e25f276-cde1-47cc-bcdc-05812f499803
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-2cprkm334fqf, 2026-11-20; `cli/src/maity/cli.py` (`_main`). The shape and the rejected alternative are the author's and the lead's, not yet reviewed
**See:** runner.md — 63492c65-e6bf-4fd8-9a73-5a599f11707e — as of 2026-11-20
**Revisit when:** `maity` gains another command group that only the runner or its operator may run; the CLI parses its arguments with something other than argparse

`maity` refuses the `runner` command group unless `runner` is its first
argument. Anything before it, such as a global option (`--for`, also
abbreviated) or `--`, is a usage error (exit 2) before anything runs. Every
other command keeps its global options.

**Reason:** the runner's commands are for the runner and its operator. The
harness rules that keep them away from placed agents look for `runner` right
after `maity`, but argparse also takes the group after `--` or a global
option. One check where the CLI reads its arguments makes the rules' shape
the CLI's own, on every harness at once.

The check runs right after argparse has parsed the arguments, on what it
took as the command. Some Python versions refuse a `--` before the command
themselves ("invalid choice"), and every version refuses `-- --`. Either way
it is a usage error (exit 2) and nothing runs, so the tests of these
spellings accept argparse's refusal, but only for words with a `--` before
`runner`.

**Rejected alternatives:**
- Widening each harness's rules to every spelling argparse accepts. They
  differ by harness, argparse also accepts abbreviated options, and a missed
  spelling would leave a gap that the CLI's check closes for all of them.
- A check on the raw words before parsing ("`runner` among the words, but
  not first"). It would refuse legitimate commands: `placement start
  --runner <name>` with a runner named `runner`, and any message text with
  the word. A raw check that avoids that would have to re-implement
  argparse's reading of global options, abbreviations and `--`, which is
  more fragile than taking argparse's own result.

## A placed Claude Code session makes no git worktree in its clone

**Id:** 6e3b9c41-27d8-4f5a-b0c3-9a1d47e82f65
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-d5e4d9s95ytj, 2026-11-21: two incidents on 2026-11-20, in which a Claude Code subagent in a placed session made an isolated git worktree under the clone's `.claude/worktrees/`, after which maity refused git in the clone ("Worktrees are not supported…"), `maity report` and `maity gh pr create` failed, and the session's sandbox refused to remove the worktree; Claude Code's documentation (permissions: a bare tool name in a deny rule removes the tool from the model's context; hooks, `WorktreeCreate`: the hook replaces Claude Code's own git worktree creation for `--worktree`, `EnterWorktree`, subagents with `isolation: "worktree"`, workflow agents and background sessions, and "if the hook fails or produces no path, worktree creation fails with an error"); `cli/src/maity/runner/adapters.py` (`claude_settings`). The plan is the lead's; the settings were not yet run on the hosted Claude Code version; the 2.1.50 floor for the `WorktreeCreate` event: Claude Code's v2.1.50 release notes, as cited in review A1808 (round 2 of #2075), not verified against a live binary
**See:** runner.md — a01035af-a4c1-4ab7-83a7-91670439fa50 — as of 2026-11-21
**Verification:** uncorroborated
**Revisit when:** the `Agent(isolation:worktree)` parameter deny rule is verified on the hosted Claude Code version (it would take the worktree option from subagents before they try); the hook is seen working on the hosted version, or Claude Code documents from which version it has the `WorktreeCreate` event; Claude Code renames `EnterWorktree` or the `WorktreeCreate` hook, or changes what a failing hook does; the clone check starts tolerating a worktree

The settings file the runner writes for every Claude Code placement,
sandboxed or not, headless or interactive, keeps the session from making a
git worktree in its clone:

- `EnterWorktree` as a bare name in `permissions.deny`, so the model is
  not offered the tool.
- `git worktree` and `git worktree *` denied for the shell (for opencode
  too), over a repository grant that allows them: a registration outside
  `.claude/worktrees/` is one the start's prune does not clear. Not
  `git * worktree *` (review A1807): it also denied ordinary commands that
  only mention the word, `git log --grep worktree` or a commit message.
  Known gap: the deny does not match a global option before the
  subcommand (`git -C <dir> worktree …`); Claude Code still refuses such a
  line because no allow rule matches it (`dontAsk`), and opencode because
  its bash map's default is deny, unless a repository grant allows it. The
  deny is a guard against accidents; the start prune and check's warning
  cover a leftover.
- A `WorktreeCreate` hook, a plain shell line that prints a short reason
  to stderr, no path to stdout, and exits 2. Claude Code then fails every
  worktree it would make, a subagent's `isolation: worktree` included.
  Written only when the start's probed version is 2.1.50 or later.
- `disableAllHooks: false` whenever the file carries a hook, not only
  under the sandbox, so a `true` in the agents' user settings does not
  switch the hook off. In an unsandboxed placement it also turns that
  user's own hooks on.

`maity runner check` reports this configuration for each Claude Code
target, not a live test. It warns about a clone the runner recorded there
that already holds a worktree, and tells a registration the start clears
from one a person must remove, and both from a bare directory, which does
not stop maity's git; it removes nothing. The clone check's refusal names
stopping and starting the placement as the way out, which runs the
existing prune.

**Version floor (round 2 of the review):** Claude Code's documentation
names no version for the `WorktreeCreate` event. The floor 2.1.50 rests
on Claude Code's v2.1.50 release notes, as cited in review A1808; it was
not verified against a live binary. For an older or
unknown version the runner writes no hook (lotse's ruling, no fallback),
and `check` warns that only the denies apply. The denies go in every file:
a deny of a name the binary does not know is taken as harmless. The hook's
effect rests on the documentation and was not confirmed on the hosted
version. Settings that switch hooks off (a managed `disableAllHooks: true`
or `allowManagedHooksOnly`, or the agents' user's `allowManagedHooksOnly`)
leave only the denies, sandboxed or not; `check` warns there too. These
are guards against an agent's mistakes, not a boundary.

**Reason:** while a worktree is in the clone maity runs no git there, so a
running session cannot report or open its pull request, and it cannot
remove the worktree itself. The existing prune clears it only at the next
start. Not making the worktree at all keeps the session working. The bare
deny means the model never tries; the hook is the backstop for every other
way Claude Code makes one, and its failure is documented to fail the
creation.

**Deferred:** an `Agent(isolation:worktree)` deny rule, which would take
the worktree option from subagents and leave subagents themselves
available. Nobody could check the parameter rule on the hosted Claude Code
version, and a binary that cannot read a rule may drop the whole settings
file, the grant included (as with `attribution` before 2.1.281). The
failing hook already makes such a subagent's worktree fail, so the rule is
left out until it is verified.

**Rejected alternatives:**
- A prune at session close. A placed session does not close by itself:
  it waits for events, so the session stays blocked until then, and the
  prune would have to judge a dirty worktree from a clean one.
- The hook alone. The documentation does not say that the hook's message
  reaches the model; without the bare deny the model would keep trying
  `EnterWorktree`, while with it the tool is not offered at all.
- The existing start prune alone. It helps only after a restart; the
  session that made the worktree stays blocked until someone restarts it.

## A quiet placement is diagnosed by the runner, on facts the hub supplies, and the runner reacts by cause

**Id:** e6a12eff-5d04-476e-8239-22970a139c7b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-twmms66p1ww4, 2026-11-20: the owner's direction (chat seq 179583, "look at the cause first"), the plan the lead approved with its rulings of the same day, the owner's decision on foreign agents (req-1kk6pwdxdmg6) and on the runner's log lines (note on the card, 20:42Z); contract in docs/api.md §15.7, §15.8, §15.14 ("The runner's watch"); not built yet
**Revisit when:** the hub builds §15.14's `health` (the grace becomes `hang_after_minutes`) or flapping; the hub gains an actor with a restart right that could resume a session; a recurring `unknown` cause asks for a class of its own

The hub tells the runner, on each placement it reads, what it knows of the
agent behind it: `session` with `started_at`, `not_listening_since`,
`paused` and `dormant`. The runner decides. Past its grace for not
listening, or without a join after a start, it gathers what it sees (the
process, the exit code, what runs below the harness, fixed pane
signatures, the login probe, a refused pickup's code), names one cause,
reports it as `finding` with its own recent log lines (read only by the
runner's owner, the agent's owner and the project's members with trust
`owner` or `admin`, the arbiter's answer to req-jcq33fsvc72a), and reacts by that
cause: one restart that resumes the session, a nudge, a wait for the
limit's reset, or `failed` at once for a login or a refused pickup. A
second failure within its window, counted only for the causes it restarts
for, holds the placement as `failed`/`hung`, which opens the owner's
outage request, so it never loops. Paused and dormant agents are left
alone. For a foreign placement (`session: null`) the runner acts only on
what it sees itself.

Round 2 of the review (PR #2059) added four rules:
- a session with a client attached (tmux's `session_attached`, unknown
  counted as attached) is never ended by the watch; the finding is
  reported instead;
- a pane match alone decides neither `login_invalid` (it needs the login
  probe, and a harness without one never gets it) nor `usage_limit` (it
  needs the harness's limit exit);
- `finding.log` holds only text the runner wrote, with values from the
  agents' side as placeholders, and only lines that start with the
  placement's id;
- an own-check end after a watch nudge counts toward `crash_cap`, not
  `auto_restarts`, so one end is counted once, under the rule that made it.

The reason for the pane rule: text in a pane is the session's to write,
so it may say anything. The causes that stop an agent for a person
(`auth`) or pause it (`rate_limited`) therefore rest on a signal from
outside the pane.

**Reason:** only the runner sees the process, its exit code and the pane,
and it already owns restart, backoff and the caps; its own restarts keep
the generation and resume the session, and need no right. The hub alone
knows the §5.3 episode and whether a session started, which the runner
cannot see: a deaf `maity wait` looks like waiting from the process tree.
So the facts go to where the decision is, on the read the runner already
makes, with no new event and no new right.

**Rejected alternatives:**
- The hub restarts the placement itself by raising `generation`: a new
  generation starts a fresh session, the hub would need an actor with a
  restart right, and it would restart blindly, without the cause, which the
  owner ruled out (a restart does nothing for a failed login).
- Send `member_not_listening` to the runner as an event: the runner
  re-reads its placements on every wake and on its own interval anyway, so
  a field on that read carries the same fact and survives a lost event.
- Keep the finding in `reported.detail` alone: one closed code, no signals
  to learn from. A health view of its own: not built.
- Restart for not listening on a fresh session: the agent's context is the
  work; a fresh start stays a person's reset.
