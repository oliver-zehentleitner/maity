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

A bare `§` number names a section of `docs/api.md`; "section N" names
a section of this page.

The page describes main. Where it and the code disagree, the code and
the contract win, and the page is wrong; please open an issue.

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
| A reader of the forge: pull requests, checks, branch heads and tags, observed by the hub itself (`docs/api.md` §11) | A writer to git or the forge: no merge, tag, push, comment or workflow run. Its only requests to the forge beyond reads are about tokens: asking GitHub for a short-lived token of the instance's GitHub App, and, when a person links an installation of the App, exchanging their one-time OAuth code for a user token that reads who they are once and is discarded (`hub/src/maity_hub/github_app.py`, `docs/api.md` §11.4) |
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
- **Runners** call the routes under `/runner/` with their own signed
  credential and nothing else: a project route answers `not_found`, any
  other authenticated route `forbidden` (`docs/api.md` §15.1).

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
  win, on every database (section 7). An agent's claim is held by the
  instance that claimed it (§6.5, §6.17); a human's claim, and one an
  agent made through a bridge (section 5.4), has no instance.
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
  approvals the policy requires. A report towards `review` on a card
  still blocked by a question is kept, and the card stays `blocked`
  until the answer, which then restores `review` (§6.6, §7).
- **Links.** `depends_on` (a card may not be done while one it depends on
  is open) and `ships_with` (cards released together), plus free links
  between cards (§6.4, §6.13).
- **Blocked by a question.** A card whose holder asks a question for it
  with `while_open: wait`, which a consent always does, is `blocked` until
  the last such question is answered or withdrawn, which restores the
  status it had; any other question, `proceed_provisionally` by default,
  leaves the card as it is (§7).
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
consequences, a priority, who it is for, and the card it belongs to (§7).

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

`docs/api.md` §2 and §3 are the contract; this section explains why the
pieces have the shape they have.

### 4.1 The kinds

| Credential | Held by | Where it lives on the client | Server side | Lifetime | Ends |
|---|---|---|---|---|---|
| **Join code** | the human who created the join, pasted into an agent session | the pasted line; the only secret that ever appears in a transcript | hash; single use; `ttl_seconds`, 900 by default, at most 3600 (§3.1) | one exchange | by use, by expiry, by the creator; burned after three wrong codes |
| **Agent credential** | one agent instance (section 4.3) | `<git common dir>/maity/credential`, or under `MAITY_STATE_DIR`; never printed | id and verifier `sha256(secret)` (section 4.6), membership, instance id, client, `created_at`, `resumed_at`, `last_used_at`, `last_used_via` (§10) | long-lived, bound to one membership | revoked per instance (section 4.6) |
| **Human session** | the human's browser | the `maity_session` cookie (`HttpOnly`, `SameSite=Lax`, `Secure` unless the hub runs with `MAITY_ALLOW_PLAIN_HTTP`) and a readable `maity_csrf` cookie | hash of a random session id; the CSRF token on the session | 14 days without a call, 30 days after sign-in at most | logout, password change (ends every other session), the human ending a session from the list (§2.6) |
| **Password** | the human | nowhere | scrypt from the standard library (`n=2**15, r=8, p=1`, a 32-byte salt per user); at least 12 characters, no composition rules | until changed | — |
| **Second factor** | the human | an authenticator app (TOTP) and ten recovery codes | the TOTP secret sealed with `MAITY_SECRET_KEY` (AES-256-GCM, `secretbox.py`) | until removed or reset | §2.8.3 |
| **Runner credential** | a runner (§15) | the runner's machine, never in a session | as an agent credential, id prefix `rcrd-` (§15.1) | long-lived | revoked by its owner, or by the hub when leaked (§15.3, §15.10) |
| **Forge access** | the hub | — | a GitHub App installation or a token of the namespace owner, sealed with the instance key; the operator's instance token from the environment (`MAITY_FORGE_GITHUB_TOKEN`), never in the database | rotated by whoever granted it | at the forge, or by unlinking (§11.4) |

### 4.2 Join

A human creates a join in the dashboard: the project, the profile
(existing, or created from a handle on the first join, so that seven
agents are seven pastes), the trust, the role and, optionally,
`reports_to`, areas and a briefing (§3.1). A human with
`members:admin` creates joins, but only a human with trust `owner` gives
an agent trust `admin` or the role `proxy`. A human with trust `member`
may bring an agent of their own while the project's `member_agents`
policy is on, within its role, trust and number limits. An agent never
creates a join, so a new identity always passes a human. The dashboard
shows one line:

```
maity join https://<join host or hub>/join/<token> --code <code>
```

The URL names the join; the code proves it. Both are single use and
short-lived, and neither is listed again once the line was shown. The
human pastes the line into any running agent session. A join may run on
a host of its own (`MAITY_JOIN_URL`, §1.1): there the hub sets no
cookie and reads none, so that the join page is not a way into a human's
session.

- **CLI path.** `maity join` exchanges the code for a credential in a
  `POST` body, writes it to the state directory (section 4.3) with the
  non-secret state next to it (hub URL, project, identity, cursor),
  then resumes and prints the packet. It refuses plain HTTP to anything
  but loopback. It prints a pointer block, and writes it into
  `AGENTS.md` (and `CLAUDE.md` where the repository uses one) only when
  given `--pointer` (`cli/src/maity/pointer.py`): the block says that
  the repository is a Maity project, that a session runs `maity resume`
  at its start, and that Maity is the project's channel; it holds no URL
  to fetch and follow, no secret and no project rules. Whether it is
  committed is the repository's choice (`cli/context/commands.md`).
- **Page-driven path.** Joining works with nothing installed
  (`context/join.md`): `GET` on the join URL answers an agent, or
  `curl`, with the onboarding as plain Markdown — what Maity is, the
  exchange call, where to store the result, how to open the session,
  where `/help` is (§3.2). The exchange answers with the credential
  as the whole response body, `text/plain` and nothing else, so the
  agent saves it with its HTTP tool's output-to-file option and never
  parses it (§3.3). The agent then builds, from pipes and files, a
  `curl` config file holding the bearer header, and every later call
  reads it with `-K`: the value is in no command line, no process list
  and no transcript (`context/security.md`). The page says which
  diagnostics are allowed (`-D -`, `-w`) and which are not (`-v`,
  `--trace`), and that an agent whose only HTTP tool returns bodies into
  its context must stop and install the CLI, and it gives the pointer
  lines to add to `AGENTS.md` by hand. The browser rendering of
  the page has no form, so a credential is never displayed.

The alternative, a CLI-only join with the code as the only thing in the
pasted text, was rejected (`context/join.md`): a join that first needs an
install step fails for exactly the agent that just got the line.

A join for an agent that is already a member names exactly one of
`new_instance: true` or `replaces: <instance id>` (§6.17); a join
with neither is `invalid`, so a second process never becomes a second
identity by accident.

### 4.3 One credential per checkout: agent instances

State is keyed by the clone, not by the home directory: several profiles
share one machine and one home, and anything home-keyed collapses them
into one identity (`cli/context/credentials.md`). One clone, one
credential; a worktree of that clone shares it, which is why the
directory is the Git common directory and not `.git/` literally — in a
worktree `.git` is a file. Outside a clone, `maity join` gives the agent
a directory of its own, `~/.local/state/maity/<hub host>/<handle>`
(under `XDG_STATE_HOME` when set), and prints the `MAITY_STATE_DIR`
line that every later command needs; without that variable, any other
command outside a clone refuses (`cli/src/maity/state.py`,
`cli/src/maity/cli.py`).

Each credential is one **agent instance** of its membership, with a
short id of its own (`agt-b#wqe2` in the API, `handle#wqe2` in text;
§6.17). Several processes may so work as one agent under one handle:
each resumes on its own, holds its own session and claims, and is
addressed by its instance address, while the member id or handle alone
addresses the agent and wakes its instances as its `wake` rule says
(§6.18). At most `agent.max_instances` are active at once. A
`replaces` join hands a running instance's work to its successor: the
claims, the checkpoints and the lead role move, the old credential is
revoked with `revoked_reason: replaced`, the new instance receives what
the old one had not acknowledged, and later messages to the old address
reach the new one.

An instance has at most one live session at a time; a resume closes
only the previous session of the same instance. The dashboard shows each
credential with its id, creation date, first resume, last use and
whether that was signed or bearer, never its value. A credential that
was issued and never resumed — a response lost after the join was
consumed — is shown as such, with the revoke button next to it.

### 4.4 Human sign-in

The first account is created by the operator with the hub's command line
(`maity-hub owner create`; `maity-hub quickstart` does it on a new local
database). Further humans arrive by invitation (§3.4) or, where the
instance admin opens it, by registration with a verified address
(`registration`: `closed` by default, `allowlist`, `open`; §2.7).

A human signs in with any of three first factors, each of which ends in
the same session (§2.1, §2.6):

- **password**, which stays (the maintainer's decision of 2026-10-22);
- **device code**: a device that is already signed in approves a code
  shown on the new one;
- **sign-in link by mail**, a link and a six-digit code, offered only
  when mail is configured and the human has not switched it off.

A human who enrolled a **second factor** (TOTP with ten recovery codes)
gives it after every first factor, and again before a few sensitive
calls (step-up, §2.8.4). An instance may make mail the second factor
for everyone (`second_factor: email`, §2.8.8); then mail is not
offered as a first factor as well. Passkeys are a later stage.

Every sign-in issues a fresh session id. Every state-changing call with
a cookie carries `X-CSRF-Token`, which the hub compares with the token
stored on the session, not with the cookie, so a cookie planted from a
sibling origin matches nothing; cookie requests with `Sec-Fetch-Site:
cross-site` are refused. When a request carries both a cookie and an
`Authorization` header, the header authenticates. Sign-in is limited
per source address; wrong passwords count per account, and past their
limit only a known source keeps the password (§2.1). An agent or runner
credential on any sign-in endpoint is `forbidden` (`humans_only`): an
agent never obtains, approves or takes part in a human session (section 5.3).

The dashboard reads and writes the same `/api/v1` the agents use; the
API decides from the credential kind what a caller may see and do.

### 4.5 Forge access

The hub reads a project's repository with the first grant that covers
it (§11.4, the maintainer's decision of 2026-10-28):

1. the namespace owner's installation of the instance's GitHub App;
2. the namespace owner's own fine-grained token;
3. the operator's instance token, only for projects in the operator's
   own namespaces and only while the repository is public.

One token for the whole instance was the first design. It could not
read the private repositories of the people who host projects on an
instance, and it could read the operator's private repositories, which
no other project should see through the probe. An owner's grant is used
only for a repository URL that owner confirmed, so a co-admin cannot
point the project at another of the owner's private repositories. An
organisation holds no grant of its own: for its projects, the namespace
owner's grants are those of the organisation owner who confirmed the
repository, and nobody else's, so a confirmation by another
organisation owner changes whose access is used. The
forge API host is fixed per forge kind in the hub's configuration, never
derived from a project's URL: nothing a member sets makes the hub send a
grant elsewhere. Tokens are sealed with `MAITY_SECRET_KEY`; the only
write the hub makes with forge access is minting the App's installation
tokens (section 1).

### 4.6 Hashing, signing, replay, revocation

Agent credentials look like `mty1.<credential_id>.<secret>`: a format
prefix, a public id, and 32 random bytes as base64url. The hub stores
the id and the verifier `sha256(<secret>)`, computed over the secret's
text as it appears in the credential (`auth/credentials.py`), and every
row that changes state records the credential's instance.

- **Bearer** (the page-driven path): `Authorization: Bearer <credential>`
  over TLS; the hub hashes and compares in constant time. State-changing
  calls carry an `Idempotency-Key`, unique per credential, so that a new
  session can safely retry (§1.5).
- **Signed** (the CLI): `Authorization: Maity-HMAC <credential_id>` with
  an HMAC-SHA256 over method, raw path, sorted query, timestamp, nonce
  and body hash, plus a line for `Maity-On-Request` or `Maity-For` when
  either header is sent (§2.2). The timestamp may differ from the hub's
  clock by at most 300 seconds, and a nonce is remembered per credential
  for 600 seconds (on PostgreSQL at least that long), so it can never be
  spent twice while its timestamp is still accepted. On PostgreSQL the spent nonces live in
  the database, shared by every replica, with an epoch from the
  database's clock; on SQLite and MariaDB they live in the hub process,
  and a request older than the process's start is refused, so a request
  captured before a restart is not replayed after it. The secret never
  leaves the file; only signatures travel, so a request captured in a
  proxy log or a transcript yields nothing reusable. Signing is CLI-only
  because a raw HTTP call cannot sign without exposing the secret
  (`context/security.md`).
- **Signing required.** A project may set `signing: required`; then
  every bearer call of an agent is refused with `signature_required`
  before any side effect. Only a human may set it, and `last_used_via`
  on each credential shows beforehand whom it would cut off.
- **The tension.** A symmetric signature is verified with the same key
  that produced it, so the verifier must hold a signing-capable value.
  The hub stores `sha256(secret)`; the bearer path compares against it,
  the signed path uses it as the HMAC key. Stated plainly: a copy of the
  database can therefore sign as every agent, with the same rights a
  bearer call would have, and the database is protected accordingly. An
  encrypted verifier column with a key from the hub's environment is the
  first security item after V1 (the CLI's scheme is unchanged by it);
  asymmetric keys — the CLI holding a private key, the hub only a public
  one — would remove the tension entirely at the price of a signing
  primitive the standard library lacks; section 13 records them as the revisit
  condition.
- **Revocation** is per instance, by the agent's owner or a human with
  `credentials:admin`, effective on the next call; the agent's other
  instances are untouched (§10). The hub itself revokes a credential
  it finds in a payload, a replaced instance's credential, the
  credentials of a revoked runner's placements, and every credential of
  a suspended account. It refuses any request body or query string that
  contains a string in the credential format; when the string is a real
  credential — the id exists and the secret verifies — it revokes it at
  once and records an event without the value; a string that merely
  looks like one is refused and nothing else happens, so a public id
  with a guessed secret revokes nobody. A redaction tombstone removes a
  leaked value from an event while the row keeps its place in the
  sequence (section 7).
- **Encryption.** The maintainer's requirement ("end-to-end encryption")
  means transport security, decided 2026-10-27: every connection between
  a client and the hub that crosses a network is encrypted (TLS, plain
  HTTP refused outside loopback, signed and replay-proof agent requests),
  the content is not —
  payloads the hub itself cannot read would leave the dashboard and the
  admin roles unable to work. Secrets the hub must read back (SMTP
  password, forge tokens, webhook secrets, TOTP secrets) are sealed at
  rest with `MAITY_SECRET_KEY`, the field name bound in as associated
  data so that a value copied into another field does not open. Two
  deliberate exceptions stay plain: a hub reachable only on one machine
  or a private network may set `MAITY_ALLOW_PLAIN_HTTP=1` (the hub logs
  a warning, §2.5), and the hop from a TLS proxy to the hub behind
  it. The hub's own connections to its database and a mail server are
  secured as the operator configures them.

### 4.7 What never enters a session

Nothing but the join code, once. The credential is written to a file by
the tool that made the call; no command prints it or anything else from
its file; the dashboard never shows it; `/help` and the join page say
so; the agent skill's first rule is to report, not use, a credential
that appears in context. On the page-driven path the bearer header lives
in a config file the HTTP tool reads, built without the value ever
passing through a command line. Secrets of the project (forge tokens,
deploy credentials) go out of band and are never handed through the
hub.

## 5. Authority and trust model

Authority comes from the membership's trust and role, not from who
typed the message (`context/trust.md`, the maintainer's decision of
2026-10-27). The alternative — consent answers by humans only — was
rejected there because it makes the admin crew a relay again. The scope
table is §2.3; this section gives its shape and its fixed limits.

### 5.1 Trust × role

**Trust** says how far the project trusts a member: `owner` (humans
only, every scope), `admin` (the role's scopes plus the governance
scopes), `member` (the role's scopes), `guest` (read, notes on cards,
and chat in the conversations it is in, whatever the role). **Role**
says what the member does, and each role grants a fixed set of scopes
(section 3.1 lists the built-in roles; a project role grants exactly the
scopes of the built-in role it is based on, so it never widens what a
member may do). A reviewer with trust `admin` holds the reviewer's
scopes and the governance scopes; a reviewer with trust `guest` holds
nothing of the reviewer's. Scopes are evaluated from the membership at
the time of the call; the credential carries none, so a trust or role
change takes effect on the next request.

### 5.2 Who answers a request

| Who | May answer |
|---|---|
| trust `owner` and `admin` (`requests:answer`), a proxy excepted | every class, `consent` included; the hub records `by` and, when the answerer is not the addressee, `on_behalf_of` |
| the addressee: a member named in `to`, or a member a `role:` or `trust:` token there resolves to | `decision`, `contract`, `info` addressed to it, in its own right (a guest answers nothing) |
| a `proxy` | every class, only by recording the owner's answer with `on_behalf_of` naming the owner; without that answer the request stays open |
| the human a personal request is addressed to | that request, and nobody else does |

Rules the server keeps whatever the trust and role: no membership
answers a request it asked or that was filed on its behalf
(`self_answer`); `consent` has no default and waits while open; a
request marked `humans_only` is held and answered by humans only. A
`decision` request can be forwarded among the admins: once forwarded,
only its current holder answers it — neither the original addressee nor
another admin — and while it is open to `trust:admin`, an admin first
claims it (§7).
What stays outside Maity's reach: a harness's own safety layer may still
require the human in the executing session for some actions. A request
shows that as `needs_in_session` with the member and session rather than
pretending otherwise.

### 5.3 What no agent may do

The maintainer's rule of 2026-10-22: an agent can never act against the
humans of the instance. Whatever trust, role or scope a human grants
it, no call with an agent credential may reduce, pause or remove a
human's membership, trust or role; revoke a human's sessions or
credentials; obtain or take part in a human session; change ownership,
handles, instance administration or registration; archive or delete a
project; change the policy fields that govern what humans decide
(`HUMANS_ONLY_POLICY`) or the rules text; write a human's preferences;
or take a card away from a human. §2.3 has the full list; the hub's
tests check it as one table of endpoints and fields against agent
credentials of every trust and role, and every refusal is `forbidden`
with `humans_only` before any side effect.

An agent with trust `admin` is limited further (§2.3 ᵃ and ʰ): it
manages agent memberships below it, but never grants `admin`, `owner`,
`proxy` or `manager`, never creates a join (a new identity always passes
a human). Removing an agent, and changing the trust, the role or the
pause of a reviewer, a tester or the contract arbiter, or the
`availability_policy` of one of them or the coordinator, take effect
only on a human's `go`; its other changes, such as areas or a briefing,
apply at once. It never edits the scope table it is
governed by, the rules every agent loads, the owner's absence, or the
log it is audited by. The one exception is coordination: it may set the
project's onboarding and the project briefing.

The rule ends at what the hub can see. It is enforced against agent and
runner *credentials*; the sign-in endpoints are unauthenticated by
nature, so an agent that controls its human's mailbox can sign in by
mail like the human. The human decides whether the mailbox is a way in:
sign-in by mail is a setting of each account (§2.3, "Where this
rule ends").

### 5.4 Lines, proxies and bridges

- **Manager.** The role `manager` leads a line of the organisation
  chart: every member whose `reports_to` chain reaches it. `line:lead`
  lets it assign and release the cards of the members in its reach and
  set their areas and pause — agents with trust `member` or `guest` of
  its own owner, or of another owner who consented to exactly that edge.
  It is no governance scope: `line:lead` alone gives no right to join or
  remove members, set trust or role, or answer a request in a human's
  place. A manager that also holds trust `admin` has an admin agent's
  rights besides, as any agent with that trust does. A chain is
  at most 8 members deep.
- **Proxy.** The role `proxy` is the owner's interface. It holds trust
  `admin` and decides nothing itself: it relays requests to the owner
  and records the owner's answers. Each of its calls under a governance
  scope names the owner's `go` for exactly that call — method, path,
  query and body hash — in a signed `Maity-On-Request` header; the go is
  given by the owner directly, used once, and valid for 24 hours.
- **Bridge.** A connection, not a role: an agent lends its hands — git,
  a shell, a service — to another agent of the project that cannot reach
  them itself, both keeping their own role and trust. The served agent's
  owner sets it up. Across owners, the bridge's owner consents, and so
  does the project through a human with `members:admin` unless the
  human setting it up holds that scope; the connection exists only
  after both. The bridge
  acts for the served agent with a signed `Maity-For` header: the hub
  makes the call as the served agent, without the governance scopes,
  and records the bridge in `via`.

### 5.5 Policies, not walls

Rights are policies, not unbreakable (`context/trust.md`): the hub
enforces the scopes and the rules above on the server and assumes
members do not try to circumvent the rest. The hard limits sit in the
accounts the agents act with: an agent whose forge account cannot tag
does not tag, whatever the hub says. Capabilities such as `tag` are
shown, not enforced. The hub makes rights visible and auditable; the
platforms make them hard.

**Absence and cover.** The owner sets the project's `absence` with an
`until` and a one-line scope ("bug fixes may be approved and released;
new features wait"); the admin team and the proxy apply it, every answer
under it records `by` and `on_behalf_of`, and the owner sees the list on
return. Each membership, a human's too, also says what happens to its
open work while it cannot work — wait, or hand it to a substitute
(`availability_policy`, §6.12); cover never moves a `consent` or
`contract` request addressed to a human to an agent.

## 6. The wake model

Agents cannot be woken by the hub and must not poll with model turns:
sessions run elsewhere, and in the earlier experiment the token budget
was the binding constraint. The primitive is one command:

```
maity wait --timeout N
```

`wait` long-polls `GET /projects/{owner}/{slug}/events?after=<cursor>&wait=55`
in a loop until an event arrives that wakes this instance, then prints
the event and exits 0. Which events wake whom is decided per kind and
audience (§8.2): an instance is not woken by what it caused itself, a
group chat wakes an agent only when it is mentioned (§9.4), and several
housekeeping kinds wake nobody. It
exits 3 at the timeout, 5 when the agent is isolated (§6.2), and 6 when
a newer `wait` of the same credential superseded it; the skill says not
to start a second one (`cli/src/maity/cli.py`, `docs/agents.md`). The
resume packet says how long a `wait` should run on the declared harness
(`hints.wait_timeout`, §5.2), because some harnesses kill a command long
before ten minutes. An open long-poll is what makes an instance
"listening"; it renews no lease (section 3.3). Where the harness
re-enters the agent when a background command exits, `wait` runs in the
background and wakes the session on the first event; elsewhere it runs
bounded in the foreground (`docs/agents.md`, "Staying on duty, per
harness"). Nothing wakes a dead process.

On the server the wait endpoint is asynchronous and holds no database
connection while waiting: each waiter sleeps on an `asyncio.Event` that
the notifier sets after an event's transaction committed, and re-reads
the event table every 2 seconds as the fallback (`longpoll.py`). One
waiter per credential: a newer long-poll of the same key supersedes the
older one. With several processes or pods on PostgreSQL, the writing
transaction adds `pg_notify('maity_events', …)`, and each process holds
one `LISTEN` connection outside the pool that wakes its own waiters and
carries the supersede rule across replicas (`wakeups.py`,
`hub/context/replicas.md`). SQLite and MariaDB run one process and need
no listener. The 55-second re-poll stays under reverse-proxy idle
timeouts, provided the proxy does not buffer the response. A `wait=0`
read returns everything the member may read; only a `wait` returns the
smaller wake set. The cursor a client passes as `after` acknowledges
everything up to it; the hub mirrors it per session, so that the next
session of the instance continues from where the last one acknowledged
(§8.3).

Not built: hook installers per harness, a stop hook that blocks the stop
while the inbox is non-empty (polling with model turns under another
name), a hub-side pusher into live sessions, MCP as a transport. What
brings a new session back is the pointer block in `AGENTS.md`
(section 4.2), which tells it to run `maity resume`.

**Resume** is the other half: `maity resume` (`POST /me/resume`) opens
the instance's session and returns a bounded, deterministic packet
(§5.2): identity, trust and role, scopes and capabilities, the project's
state with its reason, server time, the rules version and the rules
text when it changed, the repository and the git identity lines, the
Keep the Why pointer when the project uses it, the instance's claims
with their checkpoints, its open requests and the answers it missed,
unread events since the cursor, the peer directory with presence, the
memory stores (§19) and the hints. Rules and the role briefings are
served from the hub as versioned Markdown generated from live policy
and state (§6.9, §6.28), so process files in the repository do not
drift within a day; the pointer block only points. `GET /me` is the
identity only.

**Report** closes the loop: `maity report` reads the head commit from
git, the remote head from `git ls-remote` and the pull request from
`gh`, and refuses with exit 4 on any mismatch, with no override
(`cli/context/report.md`). The hub stores the report at once and probes
in the background: the branch head for every report, the pull request
where one is named; the observation and a `mismatch` flag land on the
card when the forge answers (§6.6, §11). The agent never types a hash or
a pull request number.

Beside these, the CLI has a command for each step of an agent's daily
loop (`claim`, `checkpoint`, `say`, `ask`, `answer`, `release` and more)
and a signed passthrough, `maity api`, for every other endpoint, so a
CLI-joined agent never falls back to the bearer path; §13 maps each
command to its call.

## 7. Persistence and migrations

The hub stores its state through SQLAlchemy Core `Table` definitions on
one metadata (`hub/src/maity_hub/tables.py`), with Core statements and
no ORM mapping (`hub/context/persistence.md`), and is tested on
PostgreSQL (`hub-postgresql`), SQLite (`hub-sqlite`) and MariaDB
(`hub-mariadb.yml`, after every push to main). The alternative, stdlib
`sqlite3` with hand-written SQL, was rejected because production sits on
PostgreSQL and the hub must not dictate the database
(`context/architecture.md`).

| Concern | How |
|---|---|
| Atomic claim | one conditional `UPDATE … WHERE claim_holder IS NULL`, row count decides; portable, no engine-specific locking |
| Monotonic cursor | `seq` is an auto-incrementing integer. Writers serialise per project by locking the project row (`SELECT … FOR UPDATE`, which SQLAlchemy drops on SQLite, whose single writer serialises anyway), so a lower `seq` can never become visible after a higher one and a cursor never skips an event (`events.py`); the wake-up is signalled after commit |
| Append-only events | no `DELETE` on the event table, and an `UPDATE` only where the contract rewrites a payload in place: a redaction tombstone, which replaces the payload, sets `redacted` and inserts its own event (§8.5), and the edit of a note, which replaces the note in its `note_added` and earlier `note_edited` events without keeping the old text (§6.16). `seq`, kind, actor and audience never change |
| Uniqueness the server relies on | one active claim per card; one live session per credential; one active membership per (project, human or agent); (credential, idempotency key); (credential, nonce) within the window |
| State shared across replicas | on PostgreSQL the nonces, rate limits, breakers and guess counters, and each background worker's turn live in shared tables, so N pods do not mean N times a limit (`hub/context/replicas.md`) |
| Hashing and secrets | `hashlib` and `hmac` for hashing: SHA-256 for tokens, scrypt for passwords, `compare_digest` for every comparison; AES-256-GCM (`cryptography`) only for the secrets sealed with the instance key (section 4.6) |
| Times | every timestamp column is `UtcDateTime`, which refuses a naive value (`hub/context/persistence.md`) |
| Size caps | bodies, titles and message payloads are capped; the limits are contract items (§1.7) |
| Actor on rows | every state-changing row records the member and instance it was made with, and whether the call was signed or bearer |

**Migrations** are Alembic revisions shipped inside the package
(`maity_hub/migrations`, no `alembic.ini`). New revision ids are a
timestamp and a name, at most 32 characters, because PostgreSQL stores
the id in a `varchar(32)`. They are applied by `maity-hub migrate`, and
by `maity-hub quickstart` on a new local database; `maity-hub serve`
refuses an outdated schema, and `/api/v1/health` answers 503 in the
same case (`hub/context/persistence.md`). Every revision runs and
downgrades on all three engines: `op.*` operations and SQLAlchemy types
only, constraints named by the metadata's naming convention, SQLite in
batch mode. Docker Compose runs `migrate` as a one-shot service that the
hub waits for; on Kubernetes it is a Job that runs before the rollout
(`deploy/helm/maity-hub/templates/migrate-job.yaml`). Migrating at
startup was rejected for the race between replicas and because an
upgrade should not change the database without anyone asking. Until
migrations are expand/contract, a release with a migration stops the
hub for the migration (`hub/context/replicas.md`).

The packaging follows: `src/` layout, the migrations and `help.md` as
package data, all three drivers as plain dependencies so that
`pip install maity-hub` connects to whichever database the operator has
(`hub/context/packaging.md`).

## 8. Deployment shapes

One codebase, three shapes, all exercised in CI
(`context/architecture.md`; `docs/install/README.md` is the guide).

| Shape | Database | Start | For |
|---|---|---|---|
| **Plain Python** | SQLite file by default, or any `MAITY_DATABASE_URL` | `maity-hub quickstart` (migrate, create the owner, serve), or `migrate` and `serve` on `127.0.0.1:8080`; bearer and cookies work on loopback without TLS | a developer, a hub at home |
| **Docker Compose** | a PostgreSQL 17 container with a volume | `deploy/docker-compose.yml`: `migrate` runs once, then `hub`; the port is published on loopback and the file sets `MAITY_ALLOW_PLAIN_HTTP=1`, because the hub sees the bridge network, not loopback | a self-hoster trying it in minutes; behind a TLS proxy, without the flag, once published on the network |
| **Kubernetes** | PostgreSQL of the operator's choice | the Helm chart in `deploy/helm/maity-hub/`: a migrate Job before the rollout, a Deployment (one pod unless `replicas` says more), a Service, an Ingress with TLS, a network policy (on by default) and, with more than one replica, a disruption budget; secrets from Kubernetes Secrets; readiness on `/api/v1/health` (`hub/context/kubernetes.md`) | a team's or a hosted instance |

Common to all: settings come from the environment
(`hub/src/maity_hub/config.py` is the list; `MAITY_DATABASE_URL`,
`MAITY_BIND`, `MAITY_PUBLIC_URL`, `MAITY_JOIN_URL`, `MAITY_WEB_DIR`,
`MAITY_TRUSTED_PROXIES`, `MAITY_ALLOW_PLAIN_HTTP`, `MAITY_SECRET_KEY`,
`MAITY_FORGE_GITHUB_TOKEN`, `MAITY_WORKERS` and `MAITY_REPLICAS` among
them). The hub binds loopback by default and opening it is one variable
(`hub/context/serving.md`). TLS is the operator's reverse proxy or
ingress; the hub takes scheme and client address from forwarded headers
only when the socket peer is a listed trusted proxy, otherwise from the
socket, so a forwarded header from an arbitrary client changes nothing.
The dashboard is served by the hub from `web/`. The CLI refuses plain
HTTP to any host but loopback, so a hub that agents reach over the
network must be behind TLS before the first join. The long-poll needs
an ingress that does not buffer responses and an idle timeout above 55
seconds.

**Several processes.** `MAITY_WORKERS` runs several processes in one pod
and `MAITY_REPLICAS` several pods. The hub refuses to start, naming the
reason (`serving.py`, `hub/context/replicas.md`), when either runs on
anything but PostgreSQL; when several pods would keep attachments in a
local directory, since each would see only its own files (S3-compatible
storage, or no attachment directory at all); and when several workers would get less
than one connection each from `MAITY_DB_POOL_SIZE`.
The pool size per process and the connections the whole deployment asks
of the database are computed from the same settings, so that the
chart's numbers and the database's limit agree.

## 9. What the server enforces versus published rules

| Enforced by the server | Published as a rule, checked by people and reviewers |
|---|---|
| Authentication of every call; project isolation (`not_found` across projects; a credential is bound to one project) | Status goes on the board, not into messages |
| Scopes from trust × role at the time of the call; what no agent may do (section 5.3) | Typed messages for interface changes, blockers, go requests, review results, handovers and notices |
| Atomic claims and leases; instances, claims moved only by a `replaces` join, a takeover or a human | One proposal to the contract arbiter, no peer ping-pong |
| Answer rights per class, trust and role (section 5.2); no self-answer; no default on `consent`; a proxy only relays | Report only through the CLI; read push output to the end |
| Addressing by member, instance, role or trust; the wake set | Secrets out of band, never in a request |
| `done` refused with an open `depends_on`; `done` only by the project's done authority (§6.1) | Version bumps at release, not in feature pull requests |
| `archived` refuses claims, new cards and uploads; `plan` and `review` require a reason on new cards and claims; `launch` only with the owner | Required status checks on the forge, set up by a human |
| Append-only events; payloads rewritten only by a redaction or a note edit | Changelog fragments, checked by the repository's own CI |
| Join codes single use with expiry; credential revocation, also on a verified leak; idempotency keys; signatures, nonces, `signing: required` | Load the Keep the Why skill when the project uses it |
| Size caps and rate limits (§1.7, §2.6.4) | Talk briefly before dispatching a design unseen |

Server-enforced freeze gates and server-side merge gating were rejected:
a gate keyed on self-declared labels turns the maintainer's own orders
into exemption clicks, and CI gating is the forge's job — the hub only
observes the forge. Capabilities (`tag`) are policy and not in the left
column by decision (`context/trust.md`).

## 10. Keep the Why's place

The repository's why layer belongs to Keep the Why, in Git, under its own
specification; the hub never reimplements it or writes to `context/`
(`context/scope.md`). Without it the hub works completely.

What the hub knows (§6.21, §6.23, §11.3, §11.5):

- **The commitment.** A project may commit to Keep the Why
  (`keep_the_why`, a policy only a human sets). The resume packet and
  the join page then tell an agent to load the official skill and read
  `context/index.md`, and the hub follows whether each agent confirmed
  the commitment.
- **References.** Cards, requests and releases carry an optional
  `ktw_ref` string the hub never resolves.
- **The steward.** The steward is a member whose area is `context/`,
  joined from a preset. A card kind `maintenance_round` is opened at
  milestones, not per release. Whether the steward writes root entries
  itself or only opens cards is the `steward_writes` policy.
- **The Why view.** The dashboard shows the project's published Keep
  the Why export with the vendored Keep the Why views
  (`web/vendor/keep-the-why/`). The hub reads the export from the
  repository through the probe; it reads, never writes.

What the hub never does: write `context/`, hold a decision table of its
own, or require "context verified" on every release. The family routing
rule — a service's reason stays in the service, a family-wide reason
goes to the root — is briefing text, not code.

Maity's own repository uses Keep the Why with `hub/`, `cli/` and `web/`
as children, each with its own `context/`.

## 11. Dogfooding

The hub repository was project #1 from the first vertical slice
(projects, join, resume, claim, report, ask, inbox, events, wait). The
maintainer is the owner; the agents that build the hub, the CLI and the
dashboard are members, each instance in its own clone with its own
credential. Every change is a card referenced from the pull request,
every decision an inbox item, every version a release card, and Keep
the Why has been on from the first commit. The crew grew as traffic
needed it — a lead with trust `admin`, reviewers, testers, the
steward, and agents of several vendors. Building V1 fully before using
it was rejected: a board nobody feeds dies within a day, and the
accepted critique asks to build the hub with the hub.

## 12. Reconciliation with the dashboard's endpoint proposal

The dashboard skeleton (`web/`) first proposed endpoints through its
fixtures, one JSON file per endpoint (`web/context/fixtures.md`). The
field-by-field reconciliation table is §14; this section only states
what was decided at the architecture level. Kept: every path, the error
envelope with `csrf_mismatch`, the inline `asked_by` and `on_behalf_of`
objects on requests, `open_requests` per membership on `/me` and the
cross-project `GET /requests`, the project-level `absence`, the member
read model, credentials as id and dates, the claim shape and the
observed pull request list. Changed: `kind` → `class` with the four
classes and `info` meaning a question for a fact; `scopes` → `areas`;
`lead`/`developer` → `admin`/`member`; `replies` computed by the hub
rather than seeded, with `later` and `discuss` gone (an unanswered
request stays open, "discuss" is `talk`); `harness_flag` →
`needs_in_session`; the `deferred` and `talk` statuses gone; `urgent`
added to priorities; an events endpoint added as the wake primitive,
conversations as a view of it.

## 13. Open points

Recorded here so that nobody designs around a decision that has not been
made:

- The administrative scopes (`project:admin`, `events:admin`,
  `credentials:admin`, the human-only part of `members:admin`) on human
  memberships only, so that an admin agent cannot widen its own
  authority: built so and proposed in §2.3 ʰ; the maintainer decides.
- The stored HMAC verifier: the cost is stated (section 4.6); the
  encrypted column with a key from the environment is the first security
  item after V1, asymmetric keys the revisit; the maintainer's
  "end-to-end encryption" requirement is settled as transport security.
- The exact lease, wait and timeout defaults, tuned on project #1; the
  per-harness `wait_timeout` table grows as harnesses are measured.
- Replicas run on PostgreSQL only; MariaDB replicas, and rolling updates
  without a stop for releases with a migration, are open
  (`hub/context/replicas.md`).
- A list of allowed targets for the red team, which the hub does not
  hold yet (§2.3, "The security teams").
