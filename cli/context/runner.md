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
- A `TMPDIR` under `/var/lib/maity-runner` instead of `/tmp` in
  `ReadWritePaths`: tools that hardcode `/tmp` would fail, and in the
  `agent_user` layout the agents' user cannot write there.

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

## The command allowlists are not a boundary until agents run as their own user

**Id:** 2bdc5809-b08b-4fa2-97bc-004d37c4cddb
**Type:** constraint
**Status:** superseded
**Superseded by:** b2cbf1a7-e25c-4803-8bc4-845c488512fc
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
the check at every start. The mode is set because agy 1.5.7 made `auto`
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
needs it. opencode's `grep` and `glob` are off: opencode checks them
against the pattern typed, not the path searched. maity and the runner
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
writes the index, a fetch `FETCH_HEAD`, both refs, objects and logs). That a call with something in front of
`maity` stays inside Claude Code's sandbox was checked with one version,
2.1.318 (`capabilities.CHECKED`); with another version the runner still
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
`maity runner stub`). The join runs the host's `maity` too, so the
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
  applied that nothing enforces (§15.3 refuses such placements too).
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
**Status:** active
**Evidence:** confirmed
**Source:** CLI hardening task, the boundary and the clone root chosen by the coordinator, 2026-11-04; a prefixed `maity` call (a command, a variable, `PYTHONPATH`, PATH before it) checked with Claude Code 2.1.318 and git 2.47.3 on the maintainer's laptop, 2026-11-04 (`claude -p` in a temporary clone with the runner's settings, no hub; markers in a `denyWrite` directory): refused by the runner's permission rules, kept in the sandbox with permissions open, and `excludedCommands` matched the plain command only; a placement refused at its next start over `.git/config.worktree`, 2026-11-10, and the lead's choice to accept the sandbox's placeholders while empty, with the runner deleting nothing in the clone, 2026-11-10; Claude Code 2.1.321's sandbox (bubblewrap) leaving them in a scratch clone, 2026-11-10 (`ls -la .git` of a plain clone of the same repository before, of the clone after a session that wrote none of them); the `.git/glab-cli`, `.git/modules` and `.git/worktrees` guards read in the list of protected paths of Claude Code 2.1.321's binary and seen empty after every session start with 2.1.323 on the runner's host (tsk-ydxv7x37fg08, 2026-11-13)
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
were removed, not never set. That holds for each way git finds a
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
file or directory: a link, a FIFO, a socket or a device anywhere in
`.git` is refused, under any name, and so is a directory in `.git` that
cannot be listed, since unlisted it would look empty. Any of them with
something in it is refused as before. This
holds for every maity user, not only the runner. Empty, they change
nothing git does: an empty `config.worktree` is not even read without
an `extensions.worktreeConfig` the configuration check refuses, an
empty `alternates` names no object store, and an empty `remotes/` names
no remote, and empty `glab-cli/`, `modules/` and `worktrees/` hold no
glab configuration, no submodule and no linked worktree.

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
- Passing maity's own environment on to git: a variable set on the
  command line that starts maity names programs for git as well as the
  configuration does.
- Trusting a missing `MAITY_PLACEMENT`: removing it is all an agent
  needs to reach git without the check.
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
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3qb19f0r56zf (the runner test of 2026-11-11: after its first `maity resume`, a placed agent ran `maity` in pipes and chains, read "this clone has not joined a project", took the hub for broken and stopped without `maity wait`; its session transcript)
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-11
**See:** runner.md#a-placed-claude-code-agents-maity-line-is-one-plain-call-held-to-that-by-a-hook — 63492c65-e6bf-4fd8-9a73-5a599f11707e — as of 2026-11-13
**Revisit when:** Claude Code matches `excludedCommands` per part of a compound command, or the credential becomes readable inside the sandbox

Claude Code's sandbox hides `.git/maity`, and only a command that matches
`excludedCommands` (`maity *`) runs outside it. A pipe or a chain that
does not start with `maity` does not match, so its `maity` runs inside
and finds no credential; a line that starts with `maity` and holds more
than the call is refused before it runs (63492c65). The start prompt of
a Claude Code placement says to run every `maity` command alone. When `MAITY_PLACEMENT`
is set and no credential is readable, `maity` says that instead of "has not
joined a project".

**Reason:** the old message sent the agent to `maity join`, which it cannot
do, and hid that the cause was the shape of its own command.

**Rejected alternatives:**
- Making the credential readable inside the sandbox: repository code an
  allowed build or test command runs could then read it (ea36c196).
- Rewriting the agent's command in a hook: hooks are switched off for
  placements (`--setting-sources user`), and the harness owns the command.

## A placed Claude Code agent's `maity` line is one plain call, held to that by a hook

**Id:** 63492c65-e6bf-4fd8-9a73-5a599f11707e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-bg81webs911m (the lead's order for a PreToolUse hook on a `maity` line, before the other reads of the card), 2026-11-13; Claude Code's hooks documentation (code.claude.com/docs/en/hooks), read 2026-11-13: command hooks run unsandboxed, exit 2 refuses a PreToolUse call, `onFailure: "block"` (2.1.295 and later) refuses it when the hook fails or times out; Claude Code 2.1.325 on the agents' machine, 2026-11-13 (`claude -p` with `--setting-sources user`, the hook in a `--settings` file, `dontAsk`, no sandbox, no hub): the hook refused `maity --version > out1.txt` before it ran and passed `maity --version`, and a hook at a missing path refused `echo`; the first review round of #1752 (the version the failure policy needs), 2026-11-13. The grammar, the version gate and the rejected alternatives below are the author's, not yet fully reviewed
**See:** runner.md#a-placed-claude-code-agent-runs-maity-alone — 996b6f48-a8d7-4b81-b977-33cef46bc4cc — as of 2026-11-13
**See:** runner.md#claude-codes-sandbox-runs-strict-or-not-at-all — 3c074f5a-6245-4fd9-82a2-09b543738394 — as of 2026-11-13
**Revisit when:** Claude Code can exclude a single call from its sandbox rather than a pattern over the command line; `maity` runs inside the sandbox and needs no exclusion; hooks stop loading from a `--settings` file under `--setting-sources user`; the runner stops accepting Claude Code versions older than 2.1.295; opencode is offered, or its scanner is checked against a redirect or a substitution on a `maity` line

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
run for a placed Claude Code agent. Before looking for `maity`, every
leading character that is not a letter or a digit is skipped, so a line
counts however the harness trims it; a line that starts with a variable
or another command is left to the permission rules.

The hook is the runner's own interpreter and module (`-I -m
maity.runner.plaincall`; on an ssh host `maity runner plaincall`, as for
the loop), outside the clone and not the agent's to change. It has no
matcher, so it sees every tool, and checks any tool input with a
`command`. A hook that fails, cannot start or times out refuses the call
(`onFailure: "block"`), and unreadable input is refused too. The session's
settings set `disableAllHooks: false` over the agents' user settings.
Because the hook's refusal on failure needs `onFailure` (Claude Code
2.1.295), the runner switches Claude Code's sandbox on only from that
version (`capabilities.sandbox_version_ok`); an unknown or unreadable
version counts as older, and so does a prerelease of 2.1.295 (SemVer
sorts `2.1.295-rc.1` before `2.1.295`; build metadata does not count). With `require_sandbox` that is an error in
`maity runner check` and a refused start (`harness_refused`); without
it the session runs unsandboxed (`sandbox_unavailable`), with no
exclusion for the hook to guard, as on a host without the sandbox's
tools. The hook's shell form ends in `|| exit 2`, so a hook that cannot
start or fails refuses the call on any version; only a timeout needs
`onFailure`.
opencode, which runs without a sandbox and gets no hook, denies
`maity *<c>*` for each of `;&|<>$`, a backtick and a newline, after its
allows; whether its scanner hands a redirect to the rule with the
command is not checked.

**Reason:** only `maity` itself needs to run outside the sandbox. A line
that holds more than maity's call is held to the rules every other
command is, and the check does not rely on the shell to tell the parts
apart. A grammar of what may appear rather than a list of operators: a
spelling nobody listed (`${X@P}`, `$'…'`) falls outside it.

**Rejected alternatives:**
- A narrower `excludedCommands` pattern: the exclusion is a pattern
  over the line, and nothing in it says what may not follow `maity`.
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
runner still starts. Codex is refused for a repository whose grant has
`allow` or `pull_requests`. Codex cannot honour a command allowlist, and
its `maity` runs inside its sandbox, where `maity gh` reaches neither the
login nor the forge's API.

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
path that leaves the clone. It opens the clone's root, then each
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

## Under a placement maity writes a file only inside the clone, and reads its records from the runner's directory

**Id:** 818828af-24cb-4b2a-be54-1bff2211ccb0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-bg81webs911m (the rule, and the lead's order for a first pull request with `files get` and the recorded git only), 2026-11-13; the shapes and the rejected alternatives below are the author's, not yet reviewed
**See:** runner.md#placed-agents-open-their-pull-requests-through-maity-gh-pinned-to-the-clones-repository — 9f43804d-cfdc-4496-b07b-b01e65fc6410 — as of 2026-11-13
**See:** runner.md#maity-takes-the-clones-git-only-as-the-directory-the-runner-recorded — e44249f8-15d0-4104-8940-5ff48decd412 — as of 2026-11-13
**Revisit when:** the other paths maity reads or writes for the agent (`files put`, `--attach`, the `--*-file` options, `api --json`, `--action-body`) go through the same walk; a harness runs `maity` inside its sandbox; the runner stops setting `MAITY_GIT_PRIVATE`; someone needs `--force` under a placement

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
file goes to `./maity-files/` as before, created 0700 through the same
walk. Where a name cannot be opened through a directory's descriptor
(Windows), only `-o -` is taken. Outside a placement nothing changes.

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
- On Windows, checking the path by name: it is racy, and `-o -` remains
  (the body file's choice).
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

Not built yet (tsk-29nmydbzrg5z): this records the contract's decision;
the runner and the dashboard follow in their own pull requests.

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
- **"Update now" is read, not pushed.** The hub stores the owner's
  request on the runner, and the runner reads `GET /runner` after every
  wake of its event wait. Every event belongs to a project, and a runner
  without an attached project would never hear one; the wait's own
  fallback brings the read within a minute anyway. The hub drops a
  request only when the report that ends the attempt names it, its
  `requested_at` exactly as the runner read it, as a removal by hand is
  closed (161d5507). Rejected: dropping it once a report shows a check at
  or after it, which compares the runner's clock with the hub's, and the
  signing window allows minutes of skew: a check decided before the
  request could erase it (v5vp's review).
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
