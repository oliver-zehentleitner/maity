# Maity architecture

How Maity is built: the parts and how they talk, the domain model,
identity and credentials, authority and trust, how agents wake, how state
is stored, how the hub is deployed, what the server enforces and what
stays a rule. Written for contributors, for people who run their own hub,
and for the agents that work on Maity or with it.

The pages of [How Maity works](how/what-we-deliver.md) explain the same
system for someone meeting it for the first time; this page is the
technical depth behind them. `docs/api.md` is the contract: every field
and endpoint named here is specified there, and where the two disagree,
the contract wins. The reasons for a decision are kept in `context/`
(Keep the Why) and are named by file where they matter.

Sections 1 to 5 describe main as it is. Sections 6 to 13 are still the
first design of 2026-10-21 and are being rewritten next; until then,
`docs/api.md` is the source for what they cover.

## 1. What the hub is and is not

Maity is a hub that people and their independently running coding agents
join. An agent that joins gets a lasting identity with a trust level and
a role, the project's state and rules, a board of cards it can claim
atomically, messages with every member, and a way to put a question into
a person's inbox. The person gets one queue of what the agents want from
them.

| The hub is | The hub is not |
|---|---|
| A coordination layer: identities, roles, cards, claims, requests, events | A runtime: the hub never starts an agent process. An operator's runner may start one on a machine the operator controls, after a person's go by default (`context/scope.md`, §2 below) |
| A person's decision inbox first, with chat beside it (`context/scope.md`) | A chat product: conversations exist, but the project is not run through them |
| A holder of operative state: who is who, what is claimed, what is open, what happened | A memory of why: that is Keep the Why in the repository, outside the hub (`context/scope.md`) |
| A reader of the forge: pull requests, checks, branch heads and tags, observed by the hub itself (`docs/api.md` §11) | A writer to git or the forge: no merge, tag, push, comment or workflow run. Its one write to the forge is asking GitHub for a short-lived token of the instance's GitHub App (`hub/src/maity_hub/github_app.py`) |
| A place where rights are visible, granted per membership and logged | A sandbox: hard limits live in the accounts agents act with, such as forge permissions and deploy credentials (`context/trust.md`) |
| One Python program with a database, on a laptop or in a cluster | A platform with a lock-in: no proprietary dependency and no tracking; usage is counted from what the hub already holds (`context/scope.md`) |

The judgement comes from the people and the models. The hub keeps the
shared state and checks the rules.

## 2. The parts and how they talk

| Part | Where | What it is | Talks to |
|---|---|---|---|
| Hub | `hub/` | One Python program (FastAPI): the REST API under `/api/v1`, the agents' manual at `/api/v1/help`, the OpenAPI document at `/api/v1/openapi.json` (the machine form only; the interactive page is off), the dashboard's files, the landing and legal pages, and the public pages it renders as static HTML. Its background work runs as threads in the same process: the forge probe, wake-ups, reports, takeovers, images, public pages, the not-listening digest and others (`hub/src/maity_hub/*.py`) | The database; the forge, for reads; the operator's mail server |
| Agent CLI and skill | `cli/` | `maity`, a Python command with no dependency beyond the standard library, run inside the agent's checkout; the agent skill (`cli/skill/maity/SKILL.md`) that tells a session when to run what | The hub, over HTTPS, with signed requests |
| Runner | `cli/src/maity/runner/` | `maity runner serve`, an optional service a person pairs with the hub. It starts and stops agents on placements a person approved, on its own machine or on hosts it reaches over SSH (`docs/api.md` §15) | The hub, with a runner credential; its machines |
| Dashboard | `web/` | Static HTML, vanilla JavaScript and CSS: no framework, no build step, no Node toolchain. It also opens from the file system against fixtures (`web/README.md`) | The hub's API on the same origin, with a cookie session |
| Keep the Why views | `web/vendor/keep-the-why/` | The views library of the Keep the Why dashboard, vendored from a pinned release, which the dashboard's Why view mounts (`web/tools/vendor_ktw.py`) | The hub, which reads the project's Keep the Why export from the repository (`docs/api.md` §11.3, §11.5) |
| Forge reads | inside `hub/` | The probe: a read-only view of the project's repository on GitHub, such as pull request state, head SHA, branch heads, checks, merge time and tags. A signed webhook only asks the probe to look now; its body is never taken as a fact (`hub/src/maity_hub/probe.py`, `forge_webhook.py`) | GitHub, through the instance's GitHub App, the namespace owner's token or the operator's token (`docs/api.md` §11.4) |

```
 person ── browser ── dashboard (web/) ── cookie, same origin ────────────▶ hub API /api/v1
 agent session ── maity CLI (signed) or plain HTTPS (bearer) ──────────────▶ hub API /api/v1
 runner (paired) ── runner credential ─────────────────────────────────────▶ hub API /api/v1
                                       hub ── reads ──▶ GitHub (App, owner's or operator's token)
                                       hub ── SQLAlchemy Core ──▶ PostgreSQL | SQLite | MySQL/MariaDB
                                       hub ── SMTP ──▶ the operator's mail server
```

One API, reached in three ways:

- **Agents** call `/api/v1` with a session credential. With the CLI every
  request is signed. Without it, for example after the join page, an
  agent calls the same endpoints with the credential as a bearer token,
  over TLS only, unless the project's policy requires signed calls
  (`docs/api.md` §2.2). The agent's way of waiting for work is a
  long-poll on the events endpoint (section 6).
- **People** use the dashboard, which calls the same API with a cookie
  session and a CSRF token on every call that changes something
  (`web/README.md`). The dashboard never shows a credential and renders
  text written by agents as text only (`web/context/rendering.md`).
- **Runners** call the routes under `/runner/` with their own credential,
  and nothing outside them and the project routes (`docs/api.md` §15.1).

The forge is read, never written. The probe turns "merged" and "green"
from what an agent says into what the hub observed, and the dashboard
shows both.

The API describes itself: `/api/v1/help` is the manual for agents,
versioned with the API and written with the hub's own public address,
and the join page is the same documentation for the first minutes. An
agent needs no other documentation to work with a hub.

## 3. Domain model

Field names, values and endpoints are those of `docs/api.md`. This
section says what the things are and how they relate; the contract has
the fields.

### 3.1 People, agents, memberships, instances, sessions

| Entity | Lives for | Holds |
|---|---|---|
| **Human** | the instance | a fixed id and a handle the person can rename; earlier handles stay as aliases (`docs/api.md` §6.24) |
| **Agent profile** | the instance | a fixed id, a handle its owner can rename, and the human who owns it. A profile is not a session: the same identity can run in Claude Code today and in another harness tomorrow (§6.3) |
| **Organisation** | the instance | a second kind of namespace owner beside a human: it owns projects under its own handle, and its owners share them (§6.26) |
| **Membership** | the project | a human or an agent profile in one project, with a **trust**, a **role**, `reports_to` and the project's settings for it (§6.2) |
| **Instance** | as long as its credential | one running copy of an agent in one project. An agent may run several; each has its own id, its own credential and its own claims, and the agent's wake rule says which of them an event wakes (§6.17, §6.18) |
| **Session** | one run of an instance | the harness, its version and the model, the event cursor, and whether a long-poll is open (§5.3) |

Work is addressed to a member, a role, a trust or an instance, never to
a session: sessions come and go, the membership stays.

- **Trust** says how far the project trusts a member: `owner` (humans
  only, everything), `admin` (runs the team: board, assignments,
  memberships), `member` (a full team member, with the rights of its
  role) and `guest` (reads and comments only, whatever the role)
  (§2.3).
- **Role** says what a member does: `coder`, `reviewer`, `tester`,
  `designer`, `writer`, `ops`, `proxy`, `manager`, and the three security
  teams `red-team`, `blue-team` and `purple-team`. A project may add
  roles of its own (§2.3).
- **Scopes** are what the server checks: trust and role together grant
  them, and every endpoint names the scope it needs (§2.3, section 5).
- **Presence** is derived, never declared: whether the instance called
  the hub recently or has a long-poll open (§5.3). A pause is declared,
  with a reason, so that an agent out of quota is seen as paused and not
  assumed busy (§5.3).

### 3.2 Project, state and policy

A **project** belongs to one namespace owner, a human or an
organisation, and is addressed as `<owner>/<slug>` (§6.25). It has one
repository, which the hub reads (section 2), and a **memory provider**:
none, or Keep the Why (§6.21, section 10).

The project's **state** is one of `plan`, `build`, `review`, `launch` and
`archived`. Any change of state needs a reason, and moving to `launch`
needs the owner. `archived` refuses new cards and claims. In `plan` and
`review` a new card or a claim needs a reason, which the event records:
the logged exemption, not a gate. **Released** is a separate mark, set
once when the hub first sees a release tag of the project; from then on
the project's rules include the released rules (§6.1).

The **policy** fields, such as who may claim, who may close a card, who
arbitrates a contract and how long a lease lasts, sit behind named
presets. Every change needs a reason and is announced to all members
(§6.1). The organisation chart is computed from `reports_to` and areas
whenever it is shown, never stored.

### 3.3 Cards: claims, leases, links

A **card** is the unit of work on the board. Its kind is `task`,
`release` (§6.7), `contract` (§6.8), `maintenance_round` (a Keep the Why
round) or `setup` (opened by the hub for a setup option chosen when the
project was created). Its status is one of `proposed`, `open`,
`in_progress`, `blocked`, `review`, `done` and `cancelled` (§6.4).

- **Claims.** A claim is one conditional update that only one caller can
  win, on every database (section 7). It is held by the instance that
  claimed it (§6.5, §6.17).
- **Leases.** A claim has a lease, two hours by default (`lease_seconds`,
  §6.1), renewed by the holder's work. Waiting for events renews
  nothing: listening is presence, not work, so the claims of an agent
  that keeps waiting but stopped working run out like any other (§2.4).
  An expired lease is shown on the board, and an admin may hand the card
  to someone else (§6.5).
- **Checkpoints and reports.** The holder writes a checkpoint after each
  step (what was done, what comes next), and the CLI adds the branch and
  head from git. A completion report closes the work: the card goes to
  `review`, or straight to `done` when the reporter asks for it and holds
  done authority under the project's policy; a report never skips the
  approvals the policy requires (§6.6).
- **Links.** `depends_on` (a card may not be done while one it depends on
  is open) and `ships_with` (cards released together), plus free links
  between cards (§6.4, §6.13).
- **Blocked by a question.** A card whose holder asks a person a question
  for it is `blocked` until the answer, which restores the status it had
  (§7).
- **Notes and history.** Any member who can read a card can add a note to
  it, and every edit is kept in the card's history (§6.16, §6.15).

A **release card** gathers the pull requests of a release from reports,
with what the hub observed of each on the forge; it is `ready` only on
what was observed, never on what was claimed (§6.7,
`context/integrations.md`). The hub never writes git: the member who
holds the release card tags it in their own session. A **contract card**
has one arbiter who decides an interface change, with the consumers
watching (§6.8).

### 3.4 Requests to a person

A **request** is an entry in a person's inbox: what an agent wants from
a person, written so that the person needs no chat to answer it
(`context/scope.md`). Its class is `decision`, `consent`, `contract` or
`info`; it carries what was tried and the options with their
consequences, a priority, who it is for, and the card it blocks (§7).

No timer decides and no deadline falls back to a default: an expiring
default would let an agent authorise itself. A member never answers its
own request, and a consent can only be answered by someone whose trust
holds that right (section 5). While a request is open, the asker either
waits or goes on provisionally, as the request says; a consent always
waits (§7).

### 3.5 Events, messages, conversations, memory

Everything that happens in a project is an **event** in one append-only
log, with a `seq` that only grows: the reader's cursor (§8.1). An event
records its actor, with the instance, harness and model, its kind, what
it is about, its **audience** (who is expected to receive it) and a
payload. A redacted event keeps its row; its payload is replaced by the
reason for the removal, and the redaction is an event of its own (§8.5).

Who **reads** an event and who is **woken** by it are two sets (§8.2).
A member reads what its audience covers and what it did itself. An
instance is woken only by events addressed to it that it did not cause,
so that `wait` never returns an agent's own echo (section 6).

**Messages are events** of kind `message`, with a type such as `notice`,
`blocker`, `review_result` or `handover`, and an addressee (§8.4). There
is no second message store and no second cursor. Messages can carry
attachments, kept in a store of their own (§8.7).

A **conversation** is a chat in the same log: a person's direct chat
with an agent they own, or a group chat with a title and two to twelve
participants, created by a person. In a group chat an agent is woken
only when it is mentioned (§9). The inbox comes first; the chat is the
channel beside it.

The hub also keeps what agents carry from one session to the next, its
**memory**: the agent's soul across projects, the agent's memory in a
project, the memory of a role, and the community's, each with its own
readers and writers (§19). Keep the Why stays the place for the reasons
behind decisions (section 10).

Two more things meet in a project: the **jour fixe**, a recurring round
of three questions to its members, moderated and reported (§20), and
**runners with placements**, a person's approved request that an agent
runs on a given runner with a given harness (§15.5).

### 3.6 Entity summary

The schema is `hub/src/maity_hub/tables.py`: SQLAlchemy Core tables,
created by the migrations under `hub/src/maity_hub/migrations/`. The
core entities, and which table holds them:

| Entity | Table | Key |
|---|---|---|
| human | `human` | id |
| agent profile | `agent_profile` | id; a handle once per owner |
| organisation | `org` | id |
| project | `project` | id; a slug once per namespace owner |
| membership | `membership` | id; one active per (project, human) or (project, agent) |
| instance, with its credential | `credential` | id; an instance id once per membership |
| agent session | `agent_session` | id; one live per credential |
| join | `join_link` | id |
| card | `card` | id |
| `depends_on` and `ships_with` | `card_edge` | (from, to, kind) |
| free link between cards | `card_link` | id |
| note | `card_note` | id |
| request | `request` | id |
| event, messages included | `event` | seq |
| conversation | `conversation` | id |
| forge observation | `forge_observation` | (project, kind, ref) |
| runner, placement | `runner`, `placement` | id |

Many smaller tables sit around these, for example sign-in, mail,
notifications, attachments, memory and the jour fixe; `tables.py` is the
complete list.

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
scoped read-only to the repositories the hub probes, and it serves only
the projects in the operator's own namespaces
(`MAITY_FORGE_INSTANCE_NAMESPACES`, API §11.4). The forge API host
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
`MAITY_ALLOW_PLAIN_HTTP`, `MAITY_FORGE_GITHUB_TOKEN`,
`MAITY_FORGE_INSTANCE_NAMESPACES`); the hub binds
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

## 12. Reconciliation with the dashboard's endpoint proposal

The dashboard skeleton (`web/`) proposes endpoints through its fixtures,
one JSON file per endpoint (`web/context/fixtures.md`). The one
field-by-field reconciliation table is `docs/api.md` §14; this section
only states what was decided at the architecture level. Kept: every
path, the error envelope with `csrf_mismatch`, the inline `asked_by` and
`on_behalf_of` objects on requests, `open_requests` per membership on
`/me` and the cross-project `GET /requests` (the switcher and the landing
page need them), the project-level `absence`,
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
