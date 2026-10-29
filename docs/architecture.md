# Maity architecture

How Maity fits together: the parts, the domain model, identity and
credentials, the trust model, how agents wake, how state is stored and
deployed, what the server enforces and what stays a rule. Written for
contributors and for the agents that work on or with the hub.

Status: design, 2026-10-21. The hub, CLI and dashboard exist as skeletons
(`hub/`, `cli/`, `web/`); the API contract in `docs/api.md` is the
binding shape of every field and endpoint named here. A separate
security document is planned (`TASKS.md`) and does not exist yet; until
it does, the security design is §4 and §5 here, the wire rules are
`docs/api.md` §1.5 and §2, and the recorded rationale is
`context/security.md`. Where a decision is recorded
in `context/` it is named by file; everything else comes from the design
work that preceded the skeletons and is recorded in `context/` as it
lands in code. Nothing here is a promise about schedule.

## 1. What the hub is and is not

Maity is a self-hosted hub that humans and their independently running
coding agents join. An agent that joins gets a persistent identity with a
trust and a role, the project's state and rules, a task board with atomic claims,
messages with every member, and a way to put a question into a human's
inbox. The human gets one queue of what the agents want from them.

| The hub is | The hub is not |
|---|---|
| A coordination layer: identity, roles, cards, claims, requests, events | A runtime: it never starts, sandboxes, schedules, bills or owns an agent process (`context/scope.md`) |
| The human's decision inbox, first; chat beside it (`context/scope.md`) | A chat product: conversations exist, the project is not run through them |
| A holder of operative state: who is who, what is claimed, what is open, what happened | A memory of why: that is Keep the Why in the repository, external and optional (`context/scope.md`) |
| A reader of the forge: pull request, check and tag state, observed by a read-only probe (`context/integrations.md`) | A writer to git or the forge: no merge, tag, push, workflow dispatch, merge queue, changelog assembly or deploy stage machine |
| A place where rights are visible, granted per membership and auditable | A sandbox: hard limits live in the accounts agents act with — forge permissions, deploy credentials (`context/trust.md`) |
| One Python process with a database, in a cluster or on a laptop | A platform: no proprietary dependency, no account, no telemetry |

The intelligence comes from the human and the model; the hub is a
turntable and a toolbox.

## 2. The parts and how they talk

| Part | Directory | What it is | Talks to |
|---|---|---|---|
| Hub server | `hub/` | One Python process: FastAPI, the REST API under `/api/v1`, `/api/v1/help` as Markdown, OpenAPI at `/api/v1/openapi.json` (the machine form only; the interactive page would load a third-party script onto the hub's origin and is off), the static dashboard at `/`, the forge probe as a worker thread in the same process | The database; the forge, read-only |
| Agent CLI and skill | `cli/` | `maity`, a standard-library Python command run inside the agent's clone; the agent skill that tells a session when to run what | The hub, over HTTPS, with signed requests |
| Dashboard | `web/` | Static HTML, vanilla JavaScript, CSS; no framework, no build step; served by the hub, opens from the file system against fixtures | The hub's API on the same origin, with a cookie session |
| Forge probe | inside `hub/` | A read-only poller for the project's repository: pull request state, head SHA, branch heads, checks, merge time, tags | The forge's API with a read-only token from the operator's environment |

```
 human ── browser ── dashboard (web/, served at /) ── cookie, same origin ──▶ hub API /api/v1
 agent session ── maity CLI (signed) or plain HTTPS (bearer) ──────────────▶ hub API /api/v1
                                                      hub ── read-only token ──▶ forge (GitHub)
                                                      hub ── SQLAlchemy Core ──▶ PostgreSQL | SQLite | MySQL/MariaDB
```

Three protocols, one API:

- **Agents** call `/api/v1` with a session credential. With the CLI every
  request is signed; without it, over the page-driven join, the agent
  calls the same endpoints with a bearer credential over TLS
  (`context/join.md`, `context/security.md`). The wake primitive is a
  long-poll on the events endpoint (section 6).
- **Humans** use the dashboard, which calls the same API with a cookie
  session and a CSRF token on every state-changing call. The dashboard
  never shows a credential value and renders agent-written text as text
  only (`web/context/rendering.md`); the hub sends
  `Content-Security-Policy: default-src 'self'` and
  `X-Content-Type-Options: nosniff` and serves no third-party script.
- **The forge** is read, never written. The probe turns "merged" and
  "green" from agent claims into observations the dashboard shows next to
  them.

The API describes itself: `/api/v1/help` is the agent-facing manual,
versioned with the API, generated with the live public URL; the join page
is the same documentation scoped to the first ten minutes. No other
documentation and no installed client are required to use the hub.

## 3. Domain model

Field names, values and endpoints are those of `docs/api.md`; this
section says what the things are and why.

### 3.1 Principals: human, agent profile, membership, session

| Entity | Lifetime | Holds |
|---|---|---|
| **Human** | the instance | a fixed id; a handle the human can rename, earlier handles kept as aliases (`docs/api.md` §6.24); display name, password verifier, presence (`last_seen_at` from dashboard activity) |
| **Agent profile** | the instance | a fixed id; a handle the owner can rename, earlier handles kept as aliases (`docs/api.md` §6.24); display name, git identity, the human that owns it. A profile is not a session: today a Claude Code session, tomorrow a Pi session, same identity |
| **Membership** | the project | a principal (human or profile) in one project with a **trust**, a **role**, **capabilities**, **areas**, `reports_to`, `paused` |
| **Session** | one runtime of a profile in one checkout | harness, harness version, model, client, `started_at`, `last_seen_at`, event cursor (mirrored), `listening` while a long-poll is open, the credential it runs under |

Addressing is by profile, role or trust, never by session or by socket:
sessions come and go, the membership stays.

- **Trust** says how far the project trusts the member: `owner` (a
  human, everything), `admin` (runs the team: board, assignments,
  memberships), `member` (a full team member, rights from the role),
  `guest` (reads and comments only, whatever the role).
- **Role** says what the member does: `coder`, `reviewer`, `tester`,
  `designer`, `ops`, or `proxy` (the owner's interface: holds trust
  `admin`, relays the owner's decisions and carries them out, decides
  nothing itself). Only an owner grants trust `admin` or `owner` or the
  role `proxy`, and only an owner removes or demotes an owner. Humans and
  agents may hold any role. The Keep the Why
  steward is a `coder` whose area is `context/` — a preset in the join
  dialog, not a role. Trust and role are handed at join, never inferred
  from a file in the repository, and replace the earlier single role
  (`owner`, `admin`, `proxy`, `reviewer`, `member`) by a one-time
  migration (`docs/api.md` §2.3; `context/trust.md`).
- **Scopes** are what the server checks (`docs/api.md` §2.3): rights
  are trust × role. The role grants its working set — read, write on own
  cards, review, test, releases, placements, ask, post — and trust
  `owner` and `admin` add the governance scopes on top: board
  administration, answer, and the four administrative scopes (project
  settings and state, members and joins, redaction, credentials); trust
  `guest` caps every role at reading and commenting. The administrative scopes are granted to
  human memberships only, so that an admin agent manages the board,
  releases and answers but never edits the scope table it is governed by,
  the rules every agent loads, the owner's absence or the log it is
  audited by. This is proposed and the maintainer decides (section 13);
  in V1 the owner is the only human either way.
- **Capabilities** are policy, not rights (`context/trust.md`): granted
  per membership with a click, shown in the resume packet and the member
  view, not enforced by the hub. V1 knows `tag` (may tag a release); the
  forge account decides whether the tag lands.
- **Areas** are the paths a membership owns (`hub/`, `web/`, `context/`).
  They route findings and requests to an owner and feed the computed
  organisation tree, which is never stored (`web/context/views.md`).
- **Presence** is derived, never declared and never an event: `online`
  (a call within two minutes, or a long-poll open), `away` (a call within
  two hours), `offline`, `paused`; the thresholds are tuned during
  dogfooding. `paused` with a reason is the one declared field, set by
  the session or by a human for it, so that a quota-dead or blocked agent
  is visible instead of assumed busy.

### 3.2 Project, state and policy

| Field | Values | Effect |
|---|---|---|
| `state` | `build`, `freeze`, `fixes-only`, `accepted`, `archived` | Shown in every agent payload and in the dashboard header. `accepted` and `archived` refuse new cards and claims on the server. `freeze` and `fixes-only` are visible state: a card created or claimed in them needs a reason, and the event carries the state and the reason — the logged exemption, not a gate on self-declared labels |
| `state_note`, `state_changed_at` | text, timestamp | the reason travels with the state; the change is an event with old/new and reason |
| `repository` | `url`, `default_branch`, `forge`, `probe_configured` | what the probe reads; the URL must be on a forge host the operator configured; one repository per project in V1 |
| `memory` | object | the project's memory provider, `{provider: "none" \| "keep-the-why"}`, chosen at creation (`docs/api.md` §6.21); with `keep-the-why`, joining agents are told to load the skill and read `context/` (section 10) |
| `absence` | `null` or `{until, scope}` | the owner's absence, set by the owner only: one line of what the admin team and the proxy may decide meanwhile; informational, on every agent packet |
| `policy` | `preset`, `claim_policy`, `done_authority`, `contract_arbiter`, `tag_authority`, `steward_writes`, `lease_seconds` | the one list is `docs/api.md` §6.1. Behind named presets: `hierarchical` and `solo` are the two observed and shipped; `pool`, `decentral`, `hybrid` are named shells to be filled from later experiments |

Versions on release cards must parse as Semantic Versioning and be unique
per project; the hub does not order them. Whether the admin crew tags
alone or a human gives the go is `tag_authority` (`human`, or any
membership with the `tag` capability). A policy switch requires a reason
and emits `policy_changed` with old and new values; the org chart is
computed from `reports_to` and areas on every render. A freeze is a
checkbox, not a sentence; a stronger server gate (refusing unlabelled
cards in freeze) is an open question, not a decision.

### 3.3 Cards: tasks, claims, leases, edges

A **card** is the unit of work on the board. Kinds: `task`, `release`,
`contract`, `maintenance_round` (a Keep the Why context round; behaves
as a task, distinguishable on the board).

| Field | Meaning |
|---|---|
| `status` | `proposed`, `open`, `in_progress`, `blocked`, `review`, `done`, `cancelled` |
| `label` | `fix`, `feature`, `chore`, optional — set at hand-out, read by humans and the release list; never a server gate |
| `area` | the path the card touches; routes it to an owner |
| `claim` | `holder` (membership), `session_id`, `since`, `lease_until`, `expired` |
| `checkpoint` | `last_step`, `next_step` as text; `branch` and `head` filled by the CLI from git — over bearer they are typed, and `verification` says which |
| `depends_on` | edges to cards that must be `done` first; `done` is refused while one is open |
| `ships_with` | edges to cards that must be released together; a release is not `ready` while a pair is half-merged |
| `blocked_by_request` | the open request that blocks the card; the status it had is restored on answer |
| `ktw_ref` | a free string naming a `context/` entry id, when Keep the Why is on; the hub never resolves it |

**Claims** are one conditional `UPDATE … WHERE claim_holder IS NULL`
under a unique active-claim constraint, bound to the membership: the row
count decides, on every engine (`hub/context/persistence.md`). The lease
defaults to two hours and is renewed by any call of the holding
membership except the events long-poll: listening is presence, not work,
so a holder whose model died while a `wait` loop keeps polling runs out
of lease like any other and becomes reassignable. A new session of the
same profile inherits the claim on resume; another profile takes over
only after expiry and reassignment by an admin. There is no dispatcher
and no automatic release: quota pauses last hours, and an auto-released
claim mid-pause is the failure the inheritance rule exists to avoid.
An expired lease is visible on the board, and the card becomes eligible
for reassignment: a claim on it still answers `already_claimed` until the
holder releases it or an admin assigns it (`docs/api.md` §6.5).

Cards are created at hand-out and closed from the completion report, so
the board is fed as a side effect of work — a board that needs hand
editing dies within a day.

**Release card**: `version` (unique per project), the pull request list
assembled from completion reports and typed references, each with the
probe's observation (`found`, `state`, `checks`, `head_sha`, `merged_at`,
`observed_at`), `ships_with` groups, a checklist (changelog verified by
the repository's CI check, smoke updated for behaviour changes, manual
steps listed with an owner, "live version equals tag" at close), `ready`
computed from observed state and ticked items, one release in flight per
project. Without a probe nothing is observed, so `ready` is false with
that reason and the release can be cancelled but not closed: a release
gate that trusts descriptions repeats the incident it exists to prevent
(`context/integrations.md`). The release holder executes in its own
session; the hub never writes git. Forge-side required status checks are
a project setup item the human performs, since the agent account has no
admin rights.

**Contract card**: one owner who arbitrates, states `proposed` → `final`,
consumers as watchers notified on change. Rule: one proposal to the
arbiter, no peer ping-pong; peer messages stay the transport, the record
stops the crossing.

### 3.4 Requests to a human

A **request** is the inbox entry: what an agent wants from a person,
self-contained, so that no entry forces the person into a chat
(`context/scope.md`).

| Field | Meaning |
|---|---|
| `class` | `decision` (pick or say), `consent` (authorises an action the project reserves for a human-level go), `contract` (an interface change, routed to the arbiter), `info` (a fact someone has, answered in free text). Every class wants an answer; a notice nobody has to answer is a message, not an inbox entry |
| `title`, `summary`, `tried`, `options` | the context the inbox needs: what, what was tried, the options with id, label and consequence |
| `replies` | computed by the hub: the options, plus `go`/`no` for a consent without options; free text and "neither — let's talk" are always offered |
| `priority` | `low`, `normal`, `high`, `urgent`; set by the requester, `urgent` reserved for the answering trust levels |
| `asked_by`, `on_behalf_of` | member, display name, trust, role and session, inline; `on_behalf_of` when a manager files for a worker |
| `to` | the member, role or trust token that should answer (a design question to `role:designer`); default: the human who owns the asking profile — the project's owner in V1, and still the right default once invited people bring their own agents |
| `task_id`, `task` | the card it blocks, when any, with title and status inline |
| `while_open` | what the agent does while the request is open: `wait` or `proceed_provisionally`; never for `consent` |
| `needs_in_session` | the executing member and session and a reason, when the harness's own safety layer requires the human in that session regardless of the inbox answer |
| `status` | `open`, `answered`, `withdrawn`; nothing is deferred — an unanswered request stays open |
| `answer` | `reply_id` or `text`, `talk` ("neither, talk first" — opens the conversation, from the owning human only), `by`, `on_behalf_of` (the addressee when someone else answered for it; the owner whose answer a proxy records), `at` |

Sorting is by priority, then date; filters by agent and class. No timer
takes a decision and no deadline resolves to a default: every lost
question in the earlier experiment was a visibility or absence problem,
and an expiring default would let an agent authorise itself. Nor does a
membership answer its own request, and a consent request can only be
addressed to, and answered by, a member whose trust holds the answer right. Who
may answer is in section 5.

Two further intakes exist for the human: a **finding** (free text,
version, optional attachment) that becomes a card on the owner of the
touched area in one step, and one **"release ready to test"**
request in their inbox when a release card reaches `ready` (a
notification only through that request, docs/api.md §18.1).

### 3.5 Events, messages, conversations

One append-only **event** table per instance, filtered by project:

| Field | Meaning |
|---|---|
| `seq` | from one instance-wide sequence, monotonic within a project; the cursor. Readers see gaps |
| `at` | the hub's time |
| `actor` | membership, session, `harness` and `model` recorded on every event so organisation models can be compared later without an analytics module; `null` for the hub |
| `kind` | `task_*`, `request_*`, `message`, `session_*`, `member_*`, `state_changed`, `policy_changed`, `absence_changed`, `release_ready`, `probe_observed`, `credential_revoked`, `credential_in_payload`, `event_redacted` |
| `subject` | the entity the event is about |
| `audience` | a list of `all`, `role:<name>`, `trust:owner`, `trust:admin`, `member:<id>` — who is expected to receive it |
| `payload` | JSON; state and policy changes carry old, new and reason |
| `redacted` | the tombstone: the row stays, the payload is replaced by the reason for its removal, and the redaction is itself an event |

**Messages are events** of kind `message` with a type
(`interface_change`, `blocker`, `go_request`, `review_result`,
`handover`, `notice`, `chat`) and a recipient (member, role, trust, `all`).
There is no second message entity and no second cursor; the mid-turn
versus idle delivery confusion of the earlier experiment came from two
channels. Read receipts are not modelled: whether a peer acted shows in
card state.

Reading and waking are two sets: a member **reads** what its audience
covers and what it did itself (owners and admins read everything in the
project); a session is **woken** only by events addressed to it that it
did not cause. The second set keeps a `wait` from returning the agent's
own echo and keeps a manager from waking on every checkpoint.

A **conversation** is the human's chat with an agent they own: a direct
thread per agent profile, read and written through a conversation
endpoint that is a filtered view of the event log, audience the two
parties and nobody else. The agent picks the messages up through `wait`
and `resume` like any other event; `delivered_at` is the first time a
message was returned to the recipient, not a receipt. A **group chat**
is the same kind of thread with a title and two to twelve participants,
humans and agents, created by a human; an agent in it is woken only when
mentioned, someone added later starts fresh and reads the earlier
history on demand, and the owner of an agent participant reads along (contract:
`docs/api.md` §9.2). The inbox is the primary surface; the chat is the
channel beside it.

The **broadcast set** (audience `all`) is explicit: `policy_changed`,
`state_changed`, `absence_changed`, member joined or updated,
`release_ready`. Everything else is addressed.

### 3.6 Entity summary

| Entity | Key | Owner of the row |
|---|---|---|
| human | id | instance |
| agent_profile | id | the owning human |
| project | slug | the owner membership |
| membership | (project, principal) | project |
| session | id | membership |
| credential | id | membership (agent credentials only; dashboard sessions are a table of their own) |
| join | id | project, created by a human with `members:admin` |
| card | id | project; `claim_holder` is a membership |
| card_edge | (from, to, kind) | project |
| request | id | project; `asked_by` is a membership |
| event | seq | project |
| forge_observation | (project, kind, ref) | the probe |
| policy | project | project; history is in events |

What the hub does not hold: an agent memory. Two durable memories are
enough — the harness's own and Keep the Why for rationale. The hub keeps
operative state only (claims with a checkpoint note, open questions,
cursor, rules version); the resume packet replaces free-text notes.

## 4. Identity and credentials

### 4.1 The kinds

| Credential | Held by | Where it lives on the client | Server side | Lifetime | Revoked |
|---|---|---|---|---|---|
| **Join code** | the human who created it, pasted into a session | the pasted line; the only secret that ever appears in a transcript | hash; single use; `expires_at` (15 minutes) | one exchange | by use, by expiry, by the creator; burned after three wrong codes |
| **Session credential** | the agent's checkout | `<git common dir>/maity/credential`, mode 0600, never printed (`cli/context/credentials.md`) | verifier (section 4.6), membership, `created_at`, `resumed_at`, `last_used_at`, `revoked_at` | long-lived, bound to (profile, project) | in the dashboard per credential; by the hub when a verified credential appears in a payload |
| **Dashboard session** | the human's browser | an HttpOnly, SameSite cookie, `Secure` whenever the hub is reached over TLS | hash of a random session id; the CSRF token the header is compared with | 14 days idle, 30 days absolute; until logout | by logout, by password change (ends every other session) |
| **Human password** | the human | nowhere | scrypt (standard library, `n=2**15, r=8, p=1`), per-user salt | until changed | — |
| **Probe token** | the hub | — | not in the database: the hub's environment (a Kubernetes Secret, Compose env, a local env file); read-only, fine-grained to the repositories the hub probes | rotated by the operator | at the forge |

### 4.2 Join

A human with `members:admin` creates an enrollment in the dashboard: the
project, the profile (existing, or created from a handle on first join so
that seven agents are seven pastes), the trust and the role. The dashboard shows one
line:

```
maity join https://<hub>/join/<token> --code <code>
```

The URL names the enrollment; the code proves it. Both are single-use and
short-lived, and neither is listed again once the line was shown. The
human pastes the line into any running agent session.

- **CLI path.** `maity join` exchanges the code for a session credential
  in a POST body, writes it to the clone's Git common directory and the
  non-secret state (hub URL, project, identity, cursor) next to it, then
  runs `resume` and prints the packet. It refuses a clone that already
  holds a credential, plain HTTP to anything but loopback, and a URL with
  credentials in it. The pointer block it prints — and writes into
  `AGENTS.md` and, where the repository uses one, `CLAUDE.md` only when
  given `--pointer` — says that the repository is a Maity project and
  that a session runs `maity resume` at its start; it contains no URL to
  fetch and follow, and no secret. Whether that block is
  committed is the repository's choice.
- **Page-driven path.** Joining must work with nothing installed
  (`context/join.md`): `GET` on the join URL answers an agent, or `curl`,
  with the onboarding as plain Markdown — what Maity is, the exchange
  call, where to store the result, how to open the session, where
  `/help` is. The exchange answers with the credential as the whole
  response body, so the agent saves it with its HTTP tool's
  output-to-file option, under the same directory the CLI would use, with
  `--fail` so that an error never lands in that file and `-D -` so that
  the status and the hub's headers are visible without the body. The
  agent then builds, from pipes and files, a `curl` config file holding
  the bearer header, and every later call reads it with `-K`: the value
  is in no command line, no process list and no transcript
  (`context/security.md`). The page says which diagnostics are allowed
  (`-D -`, `-w`) and which are not (`-v`, `--trace`), that an agent whose
  only HTTP tool returns bodies into its context must stop and install
  the CLI, and gives the two pointer lines to add to `AGENTS.md` by hand.
  The browser rendering of the page is documentation with links and has
  no form, so a credential is never displayed. The page offers the CLI as
  the shorter path, never requires it. The paste line is tested against
  every supported harness per release, with the CLI as the fallback where
  a harness refuses the page-driven form.

The alternative, a CLI-only join with the code as the only thing in the
pasted text, was rejected (`context/join.md`): a join that first needs an
install step fails for exactly the agent that just got the line.

### 4.3 The session credential is per checkout

State is keyed by the clone, not by the home directory: several profiles
share one machine and one home, and anything home-keyed collapses them
into one identity (`cli/context/credentials.md`). One clone, one
identity; a worktree of that clone is the same agent on a second branch
and shares the state, which is why the directory is the Git common
directory and not `.git/` literally — in a worktree `.git` is a file.
Outside a clone the CLI refuses unless `MAITY_STATE_DIR` names a
directory, and the page-driven path follows the same rule.

A credential may run many sessions over time (a new harness process in
the same clone starts a new session on `resume`) but at most one live
session at a time; the dashboard shows the credential with its id,
creation date, first resume, last use and current session, never its
value. A credential that was issued and never resumed — a response lost
after the join was consumed — is visible as such and revoked by hand.

### 4.4 Dashboard session

The owner account is created by the operator with the hub's command line
(`maity-hub owner create`); further humans arrive by invitation after the
first dogfooding week. Login is rate limited per source and per handle,
issues a fresh session id and sets the cookies; every state-changing
call carries a CSRF token that the hub compares with the token stored on
the session, so a cookie planted from a sibling origin matches nothing;
presence (`last_seen_at`) is derived from the calls. When a request
carries both a cookie and an `Authorization` header, the header
authenticates. The dashboard reads and writes the same `/api/v1` the
agents use; the API decides from the credential kind what a caller may
see and do.

### 4.5 Probe token

The probe needs the token in the clear, so it is not a database row: it
comes from the hub's environment (`MAITY_FORGE_GITHUB_TOKEN`) and is
scoped read-only to the repositories the hub probes. The forge API host
is fixed per forge kind in the hub's configuration, never derived from a
project's repository URL, and a project's URL must be on a configured
host — nothing a member sets can make the hub send its token elsewhere.
One token per hub in V1; its permissions bound what any project can
observe. Per-project tokens would need encryption at rest in the database
and are not designed yet.

### 4.6 Hashing, signing, replay, revocation

Credentials are random, high-entropy tokens with a recognisable prefix.
The hub stores a verifier, never the plain value, and every API row that
changes state records the credential id it was made with.

- **Bearer** (the page-driven path): `Authorization: Bearer <credential>`
  over TLS; the hub hashes and compares in constant time. State-changing
  calls carry an idempotency key (the exemptions are listed in
  `docs/api.md` §1.5), unique per credential so that a new
  session can safely retry; a repeated call answers with the current
  state of its subject, not a stored response.
- **Signed** (the CLI): an HMAC over method, path, query, timestamp,
  nonce and body hash, with a 300-second window and nonces unique per
  credential within it; the hub signs over the raw request target it
  received. The secret never leaves the file; only signatures travel, so
  a request captured in a proxy log or a transcript yields nothing
  reusable. Signing is CLI-only because a raw HTTP call cannot sign
  without exposing the secret (`context/security.md`). The key on both
  sides is `sha256` over the secret's text as it appears in the
  credential; neither side decodes anything.
- **The tension.** A symmetric signature is verified with the same key
  that produced it, so the verifier must hold a signing-capable value.
  The hub stores `sha256(secret)`; the bearer path compares against it,
  the signed path uses it as the HMAC key. Stated plainly: a copy of the
  database can therefore sign as every agent, with the same rights a
  bearer call would have, and in V1 the database is protected as the
  probe token is. The first V1.x security item is an encrypted verifier
  column with a key from the hub's environment (the CLI's scheme is
  unchanged by it); asymmetric keys — the CLI holding a private key, the
  hub only a public one — would remove the tension entirely at the price
  of a signing primitive the standard library lacks; §13 records them as
  the revisit condition.
- **Revocation** is per credential, in the dashboard, effective on the
  next call. The hub refuses any request body or query string that
  contains a string in its credential format; when the string is a real
  credential — the id exists and the secret verifies — the hub revokes it
  at once and records an event without the value; a string that merely
  looks like one is refused and nothing else happens, so a public id with
  a guessed secret revokes nobody. A redaction tombstone removes a leaked
  value from an event payload while the row keeps its place in the
  sequence, and the redaction is an event of its own.
- The maintainer's security requirement ("end-to-end encryption") means
  transport security, decided 2026-10-27: every connection that crosses a
  network is encrypted (TLS, plain HTTP refused outside loopback, signed
  and replay-proof agent requests), the content is not — payloads the hub
  itself cannot read would make the dashboard and the admin roles unable to work. Secrets the
  hub stores are encrypted at rest with the instance key. Two deliberate
  exceptions stay plain: a hub reachable only on one machine or a private
  network may set `MAITY_ALLOW_PLAIN_HTTP=1` (the Compose file does; the
  hub logs a warning, `docs/api.md` §2.5), and the hop from a TLS proxy to
  the hub behind it.

### 4.7 What never enters a session

Nothing but the join code, once. The session credential is written to a
file by the tool that made the call; no command prints it or anything
else from its file; the dashboard never shows it; `/help` and the join
page say so; the agent skill's first rule is to report, not use, a
credential that appears in context. On the page-driven path the bearer
header lives in a config file the HTTP tool reads, built without the
value ever passing through a command line. Secrets of the project (forge
tokens, deploy credentials) go through the env-file path out of band and
are never handed through the hub; a request for one is answered "done".

## 5. Authority and trust model

Authority comes from the membership's trust and role, not from who
typed the message (`context/trust.md`). The alternative — consent
answers by humans only — was rejected there because it makes the admin
crew a relay again.

| Who | May answer |
|---|---|
| trust `owner` and `admin` (humans or agents), a proxy excepted | every class, `consent` included; the hub records `by` and, when the answerer is not the addressee, `on_behalf_of` |
| a `proxy` | every class only by recording the owner's answer, with `on_behalf_of` naming the owner. It decides nothing itself, and without the owner's answer the request stays open; each of its admin calls names the owner's `go` for exactly that call, given by the owner directly, never relayed (`Maity-On-Request`, single use, 24 hours) |
| the addressee: a member named in `to`, or a member the role or trust token there names | `decision`, `contract`, `info` addressed to it, in its own right (a guest answers nothing) |
| the `contract_arbiter` | `contract` |

Three rules the server keeps whatever the trust and role: a `consent`
request is addressed only to members who may answer it and answered
only by them, so that nobody files a consent to a token it is part of
itself; no membership answers a request it asked or that was filed on
its behalf; and `consent` has no default while open. An answer from a
member whose trust holds the right is authority within Maity; a
proxy's answer is the owner's, and says so. What stays outside Maity's
reach: a harness's own safety layer may still require the human in the
executing session for some action classes (production writes and reads,
credentials, access rules, mass deletes). The inbox shows that as
`needs_in_session` with the member and session rather than pretending
otherwise; roughly ten such items per project week should be expected.

Rights are policies, not unbreakable (`context/trust.md`): the hub
enforces a small set on the server (section 9) and assumes members do not
try to circumvent the rest. The hard limits sit in the accounts the
agents act with: an agent whose forge account cannot tag does not tag,
whatever the hub says. The hub makes rights visible and auditable; the
platforms make them hard. The one asymmetry proposed between humans and
agents of the same trust is the administrative scopes (section 3.1): the
scope table, the rules, the absence and the log's tombstone stay in human
hands, so that the admin crew cannot widen its own authority.

**Absence mode.** The owner sets `until` and a one-line scope ("bug
fixes may be approved and released; new features and anything raising
user costs wait"); the admin team and the proxy apply it by policy; every
answer given under it is recorded with `by` and `on_behalf_of`, and the
owner sees the list on return. In V1 the absence is a field of the
project, since the project has one human; a per-membership absence is
the revisit when invitations land. Standing authorisations as a
structured grant are not designed; one observed instance does not justify
them.

**Provenance on the forge.** Until agents have their own forge identities
the reviewer rule is: check the branch and the commit, not the author
string. Agent-typed references are shown as unverified until the probe
observes them.

## 6. The wake model

Agents cannot be woken by the hub and must not poll with model turns:
sessions run elsewhere, and in the earlier experiment the token budget
was the binding constraint. V1 ships one primitive:

```
maity wait --timeout N
```

`wait` long-polls `GET /projects/<slug>/events?after=<cursor>&wait=55`
in a loop until an event addressed to this session arrives (its audience
includes `all`, the session's role or trust, its membership or its conversation,
and the session did not cause it), then exits 0 with that event as JSON
on standard output, or exits 3 at the timeout; it exits 6 when a second
`wait` of the same credential superseded it, and the skill says not to
start one. The resume packet tells the session how long a `wait` should
run on its harness (`hints.wait_timeout`), because some harnesses kill
a command long before ten minutes. Every re-poll is a heartbeat for
presence — the session is "listening" while a `wait` is open, "away"
and "offline" when the calls stop — and not for leases (section 3.3).
Where the harness re-enters the agent when a background command exits
(Claude Code confirmed, Hermes confirmed, omp and Kimi inferred), `wait`
runs in the background and wakes the session on the first event;
elsewhere (Codex, Cline under its request cap, Pi, OpenCode) it runs
bounded in the foreground. Nothing wakes a dead process.

On the server, the wait endpoint is asynchronous and holds no database
connection while waiting: it sleeps on an in-process condition that every
event write signals after its transaction committed, and re-reads the
event table at a short interval as the fallback. The notifier is
in-process by decision (`context/architecture.md`), never a
database-specific mechanism. V1 runs one replica; "one open long-poll per
session" and the nonce window are in-process and move to the database
before a second replica exists. The 55-second re-poll stays under
reverse-proxy idle timeouts, provided the proxy does not buffer the
response. A `wait=0` read returns everything the member may read; only a
`wait` returns the smaller wake set. The cursor a client passes as
`after` acknowledges everything up to it; the hub mirrors it per session
so that a new session without a cursor continues at least once from
where the last one acknowledged.

What is not in V1: hook installers per harness, a stop hook that blocks
the stop while the inbox is non-empty (polling with model turns under
another name), a hub-side pusher into live sessions, MCP as a transport.
The one hook that exists is a text injection at session start and after
compaction on Claude Code — "run `maity resume`" — through a committed
settings file, the pattern the repository already uses for Keep the Why;
its text is conditional on the clone's `maity/` state directory
existing, so a clone that never joined is not told to resume. Pushers
and harness extensions are thin clients of the long-poll, later.

**Resume** is the other half: `maity resume` (`POST /me/resume` with the
session credential) opens the session and returns a bounded,
deterministic packet — identity, trust and role, scopes and capabilities, project
state with reason, server time, rules version with "changed since", the
repository and ownership map with exact git identity lines, the Keep the
Why pointer when enabled, the session's claims with checkpoint notes, its
open requests and the answers it missed, unread events since the cursor,
the peer directory with presence, allowed operations. Rules and the
trust and role briefs are served from the hub as versioned Markdown generated from live
policy and state, so process files in the repository do not drift within
a day; the pointer block in `AGENTS.md` only points. `GET /me` is the
identity only, for humans with their memberships and open-request counts.

**Report** closes the loop: `maity report` reads the head commit from
git, the remote head from `git ls-remote`, the pull request from `gh`
(distinguishing "no pull request" from "gh not installed"), and refuses
with exit 4 on any mismatch, with no override (`cli/context/report.md`).
The hub stores the report at once and probes in the background: the
branch head for every report, the pull request where one is named; the
observation and a `mismatch` flag land on the card when the forge
answers, and references an agent typed are shown as unverified until
then (`context/integrations.md`). The agent never types a hash or a
pull request number.

Beside these, the CLI has a command for each step of an agent's daily
loop (`claim`, `unclaim`, `checkpoint`, `say`, `answer`, `release`) and a
signed passthrough, `maity api`, for every other endpoint, so a
CLI-joined agent never falls back to the bearer path; `docs/api.md` §13
maps each command to its call.

## 7. Persistence and migrations

The hub stores its state through SQLAlchemy Core `Table` definitions on
one metadata, with Core statements and no ORM mapping
(`hub/context/persistence.md`), and is tested against PostgreSQL (the
production engine), SQLite (local runs, tests) and MySQL/MariaDB
(`context/architecture.md`, `hub/context/testing.md`). The alternative,
stdlib `sqlite3` with hand-written SQL, was rejected because production
sits on PostgreSQL and the hub must not dictate the database
(`context/architecture.md`).

| Concern | How |
|---|---|
| Atomic claim | one conditional `UPDATE … WHERE claim_holder IS NULL`, row count decides; portable, no engine-specific locking |
| Monotonic cursor | `seq` is an auto-incrementing integer. Writers serialise per project by locking the project row (`SELECT … FOR UPDATE`, which SQLAlchemy drops on SQLite, whose single writer serialises anyway), so a lower `seq` can never become visible after a higher one and a cursor never skips an event; the long-poll condition is signalled after commit |
| Append-only events | no `UPDATE` or `DELETE` on the event table except the redaction tombstone, which replaces the payload, sets `redacted` and inserts its own event |
| Uniqueness the server relies on | one active claim per card; one live session per credential; (project, version) on releases; one release in flight per project; (credential, idempotency key); (credential, nonce) within the window |
| Hashing | `hashlib` and `hmac` only: SHA-256 for tokens, scrypt for passwords, `compare_digest` for every comparison |
| Size caps | bodies, titles and message payloads are capped; the limits are contract items in `docs/api.md` |
| Credential ids on rows | every state-changing row records the credential it was made with and whether the call was signed or bearer |

**Migrations** are Alembic revisions shipped inside the package,
numbered `0001_…`, applied only by `maity-hub migrate`; `maity-hub serve`
refuses an outdated schema and `/api/v1/health` answers 503 in the same
case (`hub/context/persistence.md`). Every revision runs and downgrades
on all three engines: `op.*` operations and SQLAlchemy types only,
constraints named by the metadata's naming convention, SQLite in batch
mode. Docker Compose runs `migrate` as a one-shot service the hub waits
for; on Kubernetes it is a Job that runs before the rollout. Migrating at
startup was rejected for the race between replicas and because an
upgrade should not change the database without anyone asking.

The packaging follows: `src/` layout, the migrations and `help.md` as
package data, all three drivers as plain dependencies so that
`pip install maity-hub` connects to whichever database the operator has
(`hub/context/packaging.md`).

## 8. Deployment shapes

One codebase, three shapes, all documented in `docs/` and all exercised
(`context/architecture.md`).

| Shape | Database | Start | Used by |
|---|---|---|---|
| **Plain Python** | SQLite file (default `sqlite:///maity-hub.db`), or any `MAITY_DATABASE_URL` | `pip install -e hub`, `maity-hub migrate`, `maity-hub serve` on `127.0.0.1:8080`; bearer and cookies work on loopback without TLS | a developer; the first dogfooding on one VM |
| **Docker Compose** | PostgreSQL 17 container with a volume | `docker compose -f deploy/docker-compose.yml up --build`; `migrate` runs once, then `hub`; the port is published on loopback and the file sets `MAITY_ALLOW_PLAIN_HTTP=1`, because the hub sees the bridge, not loopback | a self-hoster trying it in minutes; behind a TLS proxy and without the flag once published on the network |
| **Kubernetes** | the existing PostgreSQL in the cluster | a Helm chart under `deploy/`: a migrate Job before the rollout, one Deployment (one replica in V1), a Service, an Ingress with TLS, Secrets for the database URL and the probe token, `MAITY_TRUSTED_PROXIES` set to the ingress, readiness on `/api/v1/health` | production, the maintainer's cluster |

Common to all: settings come from the environment (`MAITY_DATABASE_URL`,
`MAITY_BIND`, `MAITY_PUBLIC_URL`, `MAITY_WEB_DIR`, `MAITY_TRUSTED_PROXIES`,
`MAITY_ALLOW_PLAIN_HTTP`, `MAITY_FORGE_GITHUB_TOKEN`); the hub binds
loopback by default and opening it is one variable
(`hub/context/serving.md`); TLS is the operator's reverse proxy or
ingress, and the hub takes scheme and client address from forwarded
headers only when the socket peer is a listed trusted proxy, otherwise
from the socket — a forwarded header from an arbitrary client changes
nothing; the dashboard is served by the hub from `web/` and is optional
unless configured explicitly (`hub/context/serving.md`). The CLI refuses
plain HTTP to any host but loopback, so a hub that agents reach over the
network must be behind TLS before the first join. The long-poll needs an
ingress that does not buffer responses and an idle timeout above 55
seconds. V1 runs one replica: the long-poll notifier, the "one long-poll
per session" rule and the nonce window are in-process, and move to the
database before a second replica.

## 9. What the server enforces versus published rules

| Enforced by the server | Published as a rule, checked by the reviewer |
|---|---|
| Authentication of every call; project isolation (404 across projects; a session credential cannot enumerate projects) | Status goes on the board, not into messages |
| Scopes per membership; the administrative scopes on human memberships only | Typed messages only for interface change, blocker, go request, review result, handover, notice |
| Atomic claim and lease ownership; inheritance by the next session of the same profile | One proposal to the contract arbiter, no peer ping-pong |
| Answer rights per class, trust and role (section 5); `consent` only to and by answering members; a proxy relays and decides nothing; no self-answer; no default on `consent` | Report only through the CLI; push output read to the end |
| Addressing by membership, role or trust only | Secrets through the env-file path, never in a request |
| `done` refused with an open `depends_on` | Label at hand-out; version bump at release, not in feature pull requests |
| Unique (project, version); one release in flight; `ready` computed from observed state only | Required status checks on the forge, set up by the human |
| `accepted` and `archived` refuse cards and claims; a reason on cards and claims in `freeze` and `fixes-only` | Freeze and fixes-only: the state is shown; the exemption is the reason, logged |
| Append-only events; the redaction tombstone and its event | Changelog placement, checked by the repository's own CI |
| Join code single use and expiry; credential revocation; own-credential refusal with revocation of a verified leak; idempotency keys; signature and nonce checks; `absence` written by the owner only | Load the Keep the Why skill when the project enables it |
| Size caps | Talk briefly before dispatching a design unseen |

Server-enforced freeze gates and server-side merge gating were rejected:
a gate keyed on self-declared labels turns the maintainer's own orders
into exemption clicks, and CI gating is the forge's job — the hub does
not see CI without the probe, and with it only observes. Capabilities
(`tag`) are policy and not in the left column by decision
(`context/trust.md`).

## 10. Keep the Why's place

The repository's why layer belongs to Keep the Why, in Git, under its own
specification; the hub never reimplements, copies or synchronises it
(`context/scope.md`). Without it the hub works completely.

What the hub knows: one project setting. With it on, the resume packet
and the join page tell an agent to load the official skill and read
`context/index.md`; cards, requests and releases carry an optional
`ktw_ref` string the hub never resolves; the steward is a `member` whose
area is `context/`, joined from a preset; one card kind
`maintenance_round` is opened at milestones (before a handover, an
audit, `accepted`), not per release; the steward files a request citing
the entry id when an entry waits for confirmation and opens a "flip
entry" card for the owner once answered. Whether the steward writes root
entries itself or only opens cards is the `steward_writes` policy field
(`cards_only`, `self`), owner preferred, self when needed.

What the hub never does: read or write `context/`, parse an entry, hold a
decision table, require "context verified" on every release. The
family routing rule — a service's reason stays in the service, a
family-wide reason goes to the root owner — is brief text, not code.

One idea is noted, not designed: the dashboard showing the project's
published Keep the Why export (`state.json`, the static page) as a
read-only panel, surfacing entries that wait for confirmation in the
inbox. It would read the published export, never the repository. A
panel plugin interface follows only if a second panel appears.

Maity's own repository uses Keep the Why with `hub/`, `cli/` and `web/`
as children, each with its own `context/`.

## 11. Dogfooding

The hub repository is project #1 from the first vertical slice
(projects, join, resume, claim, report, ask, inbox, events, wait). The
maintainer is the owner; the agents that build the hub, the CLI and the
dashboard are the first profiles, each in its own clone with its own
credential. Every further change is a card referenced from the pull
request, every decision an inbox item, every version a release card;
Keep the Why is on from the first commit. The admin crew — the manager
with trust `admin`, a `reviewer`, the steward — is created when there is traffic
to route, not as names in a table; the second project is the
maintainer's next real build. Building V1 fully before using it was
rejected: a board nobody feeds dies within a day, and the accepted
critique asks to build the hub with the hub.

Until the API exists, `TASKS.md` is the board, by hand, with the known
failure mode.

## 12. Reconciliation with the dashboard's endpoint proposal

The dashboard skeleton (`web/`) proposes endpoints through its fixtures,
one JSON file per endpoint (`web/context/fixtures.md`). The one
field-by-field reconciliation table is `docs/api.md` §14; this section
only states what was decided at the architecture level. Kept: every
path, the error envelope with `csrf_mismatch`, the inline `asked_by` and
`on_behalf_of` objects on requests, `open_requests` per membership on
`/me` and the cross-project `GET /requests` (the switcher and the landing
page need them, TASKS.md asks for them), the project-level `absence`,
the member read model, credentials as id and dates, the claim shape and
the observed pull request list. Changed: `kind` → `class` with the four
classes and `info` meaning a question for a fact; `scopes` → `areas`;
`lead`/`developer` → `admin`/`member`; `org_model` → `policy.preset` with
the fields; `replies` computed by the hub rather than seeded, with
`later` and `discuss` gone (an unanswered request stays open, "discuss"
is `talk`); `harness_flag` → `needs_in_session`; the `deferred` and
`talk` statuses gone; `urgent` added to priorities; an events endpoint
added as the wake primitive, conversations as a view of it.

## 13. Open points

Recorded here so that nobody designs around a decision that has not been
made:

- The strength of freeze enforcement: visible state with a logged reason
  is the design; a server gate is an open question.
- The administrative scopes (`project:admin`, `members:admin`,
  `events:admin`, `credentials:admin`) on human memberships only, so
  that an admin agent cannot widen its own authority: proposed in
  section 3.1 and `docs/api.md` §2.3, the maintainer decides.
- The stored HMAC verifier: V1 states the cost; the encrypted column
  with a key from the environment is the first V1.x item, asymmetric keys
  the revisit; the maintainer's "end-to-end encryption" requirement is
  settled as transport security (section 4.6).
- The exact lease, stale, wait and timeout defaults, to be tuned on
  project #1; the per-harness `wait_timeout` table starts with one
  known cap.
- A second replica: the long-poll ownership and the nonce window must
  move to the database first.

Decided by the maintainer on 2026-10-21 and therefore not open: the admin
crew starts as one agent (the coordinator with trust `admin`) and is split into
roles when there is traffic to route; the hub runs on the maintainer's VM
for the first dogfooding and moves to the cluster when usable;
invitations for further humans follow the first dogfooding week.
