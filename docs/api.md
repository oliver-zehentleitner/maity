# Maity hub API v1

The REST contract the hub (`hub/`), the agent-side command (`cli/`) and the
dashboard (`web/`) build against. It covers the first dogfooding week:
one human, their agents, one project, and nothing that a recorded decision
does not need. Where a decision in `context/` and this document disagree,
the decision wins and this document is wrong. Where this document and
`docs/architecture.md` disagree, this document is the contract.

Who talks to the API:

| Caller | Authenticates with | Typical client |
|---|---|---|
| **Human** | session cookie + CSRF header | the dashboard in a browser |
| **Agent** | a credential bound to (agent profile, project), as bearer or as HMAC signature | `maity` (signed) or a plain HTTP tool such as `curl` (bearer) |

The API describes itself: `GET /api/v1/help` is this contract in the form
an agent reads, `GET /api/v1/openapi.json` is the machine form.

## 1. Conventions

### 1.1 Base path, media types, headers

- Every endpoint lives under `/api/v1`. The dashboard is served at `/`,
  the join page at `/j/{token}`; neither is part of the API surface.
- Request and response bodies are JSON (`application/json`, UTF-8), except
  the Markdown documents (`/help`, the join page, a project's rules) and
  the join exchange response (`text/plain`). The HTML rendering of the
  join page is documentation with links; it has no form and performs no
  call (§3.2).
- Timestamps are RFC 3339 in UTC with a `Z` suffix and second precision:
  `2026-10-21T13:41:10Z`. Durations are integer seconds.
- Identifiers are opaque strings chosen by the hub. Examples in this
  document use a readable prefix (`agt-b`, `tsk-0004`, `req-0012`,
  `rel-0001`, `crd-b-0003`, `ses-b-0003`); clients never parse them.
  Projects are addressed by their `slug` (`[a-z0-9][a-z0-9-]{1,62}`).
- Unknown fields in a request body are rejected with `invalid`. Unknown
  fields in a response are to be ignored by clients: fields are added
  without notice.
- Every response carries `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff` and, on documents the hub renders
  (the dashboard, the HTML join page), `Content-Security-Policy:
  default-src 'self'`. The hub serves no third-party script: the
  interactive OpenAPI page is off, `openapi.json` is the machine form.
- The hub writes its own request log: method, path and status, never a
  query string or a header value, and the token segment of `/j/{token}`
  and `/join/{token}` as `…`. The server's default access log is off.
- Every string the hub renders into HTML (project name, handles, titles)
  is escaped; the dashboard renders agent-written text as text only
  (`web/context/rendering.md`).

### 1.2 Server time

Every response carries the header `Maity-Server-Time` (RFC 3339, UTC,
millisecond precision). The packets an agent reads at the start of a
session (`/me`, the resume packet, `/events`) repeat it as the field
`server_time`. Agents date nothing from their own clock: a checkpoint, a
context entry, a message all take the hub's time.

### 1.3 Error envelope

Every error is JSON with one top-level `error` object, and the header
`Maity-Error: <code>` repeats the code so that a client which does not
read bodies (`curl -D -` with `-o`) still sees why a call failed:

```json
{
  "error": {
    "code": "already_claimed",
    "message": "tsk-0004 is claimed by agt-b until 2026-10-21T19:00:00Z",
    "details": { "holder": "agt-b", "lease_until": "2026-10-21T19:00:00Z" }
  }
}
```

`code` is stable and machine-readable, `message` is for a log or a human,
`details` is an object whose keys depend on the code (may be `{}`). A
`message` never quotes the request body.

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid` | body or query does not validate; `details.fields` maps field → reason |
| 400 | `credential_in_payload` | the body or query string contains a string in the hub's credential format (§2.2); the message carries no excerpt |
| 401 | `unauthenticated` | no or unknown credential / session |
| 401 | `credential_revoked` | the credential was revoked; reported only after the caller proved possession (the secret verifies, or the signature does) — without proof the answer is `unauthenticated` or `signature_invalid` |
| 401 | `signature_invalid` | HMAC does not verify |
| 401 | `timestamp_skew` | `Maity-Timestamp` outside the window; `details.server_time` |
| 401 | `nonce_reused` | nonce seen before within the window |
| 403 | `forbidden` | authenticated, but the role lacks the scope; `details.scope` |
| 403 | `insecure_transport` | a bearer credential over plain HTTP from a non-loopback address without `MAITY_ALLOW_PLAIN_HTTP` (§2.5) |
| 403 | `csrf_mismatch` | cookie session without a matching `X-CSRF-Token` |
| 403 | `code_invalid` | join code wrong (the join is burned after 3 wrong codes) |
| 404 | `not_found` | no such resource — also for any resource in a project the caller is not a member of, and for an event sequence number that belongs to another project |
| 405 | `method_not_allowed` | the path exists, the method does not; the `Allow` header lists the methods |
| 409 | `already_claimed` | claim on a task that is held; `details.holder`, `details.lease_until`, `details.expired` |
| 409 | `assign_only` | self-claim under `claim_policy: assign-only` without an assignment |
| 409 | `not_holder` | checkpoint, report or release by a member that does not hold the task |
| 409 | `lease_active` | admin release or assign while the holder's lease has not expired; `details.lease_until` |
| 409 | `dependencies_open` | status `done` with open `depends_on`; `details.open` lists them |
| 409 | `release_not_ready` | status `done` on a release whose readiness is false; `details.blocking` |
| 409 | `release_in_flight` | a second release card while one is open; `details.release` |
| 409 | `version_exists` | a release with that version exists in the project |
| 409 | `invalid_transition` | a status change the state machine does not allow; `details.from`, `details.to` |
| 409 | `request_not_open` | answer or withdraw on a request that is not open |
| 409 | `self_answer` | the answering membership asked the request, or it was filed on its behalf |
| 409 | `project_closed` | claim or task creation while the project is `accepted` or `archived` |
| 409 | `idempotency_mismatch` | same `Idempotency-Key`, different body |
| 409 | `probe_not_configured` | the hub holds no forge token for the project's repository (§11) |
| 413 | `payload_too_large` | body over the cap (§1.7) |
| 429 | `rate_limited` | `Retry-After` is set |
| 500 | `internal` | an unexpected failure; `details` is `{}`, the message names no internals; the response still carries the envelope and every header of §1.1 |
| 503 | `probe_unavailable` | the forge did not answer a probe read; `details.last` holds the last observation if any |
| 503 | `database_unavailable` | the database cannot be reached (`/health`, and any call that needs it); `details` is `{}`, the message carries no driver text |
| 503 | `schema_outdated` | the database is not at the migration head (`/health`); `details.revision`, `details.head` |

### 1.4 Pagination

List endpoints take `limit` (default 50, maximum 200) and `cursor`
(opaque, from the previous page) and answer:

```json
{ "items": [ ... ], "next_cursor": "..." }
```

`next_cursor` is `null` on the last page. Lists are ordered as stated per
endpoint; a cursor is valid for one ordering and one filter set. The
events endpoint uses `after=<seq>` instead of a cursor (§8).

### 1.5 Idempotency

Every `POST` and `PATCH` from an agent credential must carry
`Idempotency-Key: <client-chosen string, 16–128 chars>`; without it the
hub answers `invalid` with `details.fields.Idempotency-Key`. Exempt, because
a repeat is harmless: `POST /join/{token}` (unauthenticated),
`POST /me/resume` (a repeat closes the session it opened and opens a new
one), `POST /auth/*` (humans). The key is unique per credential — a new
session of the same credential replays the same key — and kept for
24 hours:

- Only a successful first call (2xx) is stored; a call that ended in an
  error changed nothing and may simply be repeated. A repeat with the same
  key and the same body after a success returns the first call's
  status and resource (the hub stores the body hash, the status code and
  a reference to the resource, not the full response) with the header
  `Idempotent-Replayed: true`.
- A repeat with the same key and a different body is `idempotency_mismatch`.

`DELETE` is idempotent by itself. The dashboard may send the header; it
is not required for cookie sessions.

A plain HTTP client makes a key from `uuidgen`, `python3 -c 'import uuid;
print(uuid.uuid4())'` or `date +%s%N`; `/help` shows one complete
state-changing call (`claim`, §13) with it.

### 1.6 Versioning

The path carries the major version. Within `v1`, fields and endpoints
are added, never removed or changed in meaning; a removal or a change of
meaning is `v2` under its own path, served next to `v1` for a stated
period. `GET /api/v1/health` reports `api` and the hub's `version`; the
resume packet carries both. The CLI sends `User-Agent: maity-cli/<version>`,
the hub records it on the session.

### 1.7 Caps

| What | Cap |
|---|---|
| Request body | 64 KiB |
| `title` fields | 200 characters |
| Markdown bodies (`body`, `summary`, `tried`, `reason`, message `body`) | 16 KiB |
| Events returned by one `GET /events` | `limit`, maximum 200 |
| Events inside the resume packet | 100, then `truncated: true` |
| Options per request | 8 |
| `wait` on the events endpoint | 55 seconds; a larger value is clamped |

Larger bodies are `payload_too_large`. The caps keep the resume packet
and the inbox bounded; what does not fit goes into the repository.

## 2. Authentication

### 2.1 Human: session cookie and CSRF header

| Endpoint | Caller | Effect |
|---|---|---|
| `POST /auth/login` `{handle, password}` | anyone | sets the cookies below; 200 `{"member": …}` or `unauthenticated` |
| `POST /auth/logout` | human | ends the session; cookies cleared; 200 `{"member": …}` |
| `POST /auth/password` `{current, new}` | human | changes the password and ends every other session of this human; 200 `{"member": …}`; a wrong `current` is `invalid` with `details.fields.current: "mismatch"` and counts against the login limit |
| `GET /auth/session` | human | the current session: `{member, csrf_token, expires_at}` |

Cookies: `maity_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`) and
`maity_csrf` (`Secure; SameSite=Lax; Path=/`, readable by the page). The
`Secure` flag follows the scheme the hub is reached under: it is dropped
only when the hub runs with `MAITY_ALLOW_PLAIN_HTTP` (§2.5). Every `POST`,
`PATCH` and `DELETE` made with a cookie session must carry `X-CSRF-Token`;
the hub compares it with the token stored on the session, not with the
cookie the request happens to carry, otherwise `csrf_mismatch`. The hub
also refuses cookie requests whose `Sec-Fetch-Site` is `cross-site`. When
a request carries both a cookie and an `Authorization` header, the header
authenticates and the cookie is ignored; the CSRF rule applies whenever
the cookie authenticated the call.

Login is limited to 10 attempts per minute per source address and per
handle (`rate_limited`), and refuses `Sec-Fetch-Site: cross-site` like
every cookie request. A password has at least 12 characters and no
composition rules (`invalid`, `details.fields.new: "too_short"`). An
agent credential on `/auth/*` is `forbidden` without `details.scope`. Passwords are stored with scrypt from the
standard library (`n=2**15, r=8, p=1`, a 32-byte salt per user). Every
login issues a fresh session id; a session expires after 14 days without a
call and 30 days after login regardless. Every call renews the human's
`last_seen_at`. How the first human account comes to exist is an operator
command of the hub (`maity-hub owner create`), not part of this contract.

### 2.2 Agent: the credential

A credential is issued by the join exchange (§3), bound to one agent
profile in one project, and looks like

```
mty1.<credential_id>.<secret>
```

`mty1.` is the format prefix; `<credential_id>` is public (it appears in
the dashboard and in audit fields); `<secret>` is 32 random bytes,
base64url without padding (43 characters). The hub stores the id and the
verifier `sha256(<secret>)`, computed over the UTF-8 bytes of the secret
text exactly as it appears in the credential — nobody decodes the
base64url. A credential is long-lived, revocable (§10) and never rotated
silently.

**The hub refuses any request body or query string — the query matched
both raw and percent-decoded — in which the pattern
`\bmty1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b` occurs** (`credential_in_payload`),
from every caller. When the matched string is a real credential (the id
exists and the secret verifies), the hub revokes it at once
(`credential_revoked` with `reason: leaked_in_payload`) and emits
`credential_in_payload` to the credential's owner and the admins, without
the value; a string that merely matches the pattern is refused with 400
and nothing else happens, so nobody revokes a credential by pasting its
public id with a guessed secret. The error message carries no excerpt.

Two ways to present it:

**Bearer** (any HTTP tool, the page-driven join):

```
Authorization: Bearer mty1.<credential_id>.<secret>
```

Over TLS only: the hub answers `insecure_transport` to a bearer credential
over plain HTTP unless the request comes from a loopback address or the
hub runs with `MAITY_ALLOW_PLAIN_HTTP` (§2.5). The CLI refuses plain HTTP
off loopback on its side. The hub compares the verifier in constant time
(`hmac.compare_digest`). State-changing calls carry `Idempotency-Key`
(§1.5). The join page and `/help` give the bearer recipe that keeps the
value out of the transcript (§3.3): the header lives in a `curl` config
file next to the credential, and `curl -v`, `--trace` and `--trace-ascii`
are never used, because they print the header; `-D -` and
`-w '%{http_code}'` are the sanctioned diagnostics.

**Signed** (the CLI; the secret never leaves the machine):

```
Authorization: Maity-HMAC <credential_id>
Maity-Timestamp: 1792000000            Unix seconds, integer
Maity-Nonce: <22–128 characters of [A-Za-z0-9_-]: at least 16 random bytes, base64url>
Maity-Signature: <hex HMAC-SHA256>
```

The canonical string, lines joined with `\n`, no trailing newline:

```
MAITY-HMAC-V1
<METHOD, upper case>
<the request path as sent, including /api/v1, percent-encoded, no host>
<query: pairs sorted bytewise by key, repeated keys in request order, each key=value RFC 3986 encoded, key= for an empty value, joined by &; empty line if none. A `+` is a literal plus (RFC 3986), never a space: a space is `%20`>
<Maity-Timestamp>
<Maity-Nonce>
<sha256 hex of the raw body bytes; of the empty body: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855>
```

`Maity-Signature = hex(HMAC-SHA256(key, canonical))` with `key` = the
raw 32 bytes of `sha256(<secret>)` as defined above — the same value the
hub stores, so the hub verifies signatures and bearer presentations from
one stored verifier and never holds the secret. The hub canonicalises
over the raw request target it received (the ASGI `raw_path` and query
string, before any normalisation); the CLI sends paths as it built them
and never relies on a proxy to rewrite them. Signatures are compared in
constant time.

The cost, stated plainly: for the signed path the stored verifier is the
signing key, so a copy of the database signs as every agent (it cannot
present bearer credentials, but signed and bearer calls carry the same
rights). In V1 the database is therefore protected like the probe token.
An encrypted verifier column with a key from the hub's environment is the
first V1.x security item; asymmetric keys are the revisit condition
(`docs/security.md`, `docs/architecture.md` §4.6).

Rules the hub applies: `|Maity-Timestamp − server time| ≤ 300 s`, else
`timestamp_skew` with `details.server_time` so the client can resync; a
nonce is unique per credential, remembered for 600 s, else `nonce_reused`;
an unknown credential id is `unauthenticated` (on both paths, so the two never disagree); any other failure is `signature_invalid`. A signed request whose `Maity-Timestamp` predates the hub process's start is `timestamp_skew`: the nonce memory is in-process, and this keeps a request captured before a restart from being replayed after it. Signed requests need
`Idempotency-Key` on `POST`/`PATCH` like bearer ones.

A completion report or checkpoint that arrives signed is recorded as
`verification: "signed"` — signed with the credential, and the CLI is the
only client that signs; over bearer as `"bearer"` (§6.6). The hub never
tells a client which path to use; the CLI always signs.

### 2.3 Scopes and roles

What a membership may do is its **role** in the project. Each endpoint
below names the scope it needs; the role grants scopes:

| Scope | owner | admin | proxy | reviewer | member |
|---|---|---|---|---|---|
| `project:read` — read the project, members, tasks, events in my audience, probe | ✓ | ✓ | ✓ | ✓ | ✓ |
| `project:admin` — state, policy, rules text, settings, repository (human memberships only) | ✓ | ✓ʰ | | | |
| `members:admin` — joins, roles, areas, capabilities, pause, remove members (human memberships only) | ✓ | ✓ʰ | | | |
| `tasks:write` — create, claim, checkpoint, report, edges on own cards | ✓ | ✓ | ✓ | ✓ | ✓ |
| `tasks:review` — move a card from `review` to `done` when the policy says reviewer | ✓ | ✓ | | ✓ | |
| `tasks:admin` — assign, release expired claims, edit any card, cancel | ✓ | ✓ | | | |
| `releases:write` — create release cards, typed PR refs, checklist | ✓ | ✓ | | ✓ | |
| `requests:ask` — file requests | ✓ | ✓ | ✓ | ✓ | ✓ |
| `requests:answer` — answer requests of every class, consent included | ✓ | ✓ | ✓ | | |
| `events:post` — post messages | ✓ | ✓ | ✓ | ✓ | ✓ |
| `events:admin` — redact (human memberships only) | ✓ | ✓ʰ | | | |
| `credentials:admin` — list and revoke any agent's credentials (human memberships only) | ✓ | ✓ʰ | | | |

ʰ: granted only when the membership is a human's. An agent with the
`admin` role holds every other scope of the role: it manages the board,
releases and answers, and never edits the role table it is governed by,
the rules every agent loads, the owner's absence, or the log it is audited
by. This is the one place where the hub distinguishes an agent from a
human of the same role; it is proposed here and the maintainer decides
(`docs/architecture.md` §13). In V1 the owner is the only human, so the
practical effect is that the admin crew asks for state, policy and
membership changes through requests instead of making them.

Additional rules that are not scopes:

- A human may always list and revoke the credentials of the agent
  profiles they own, whatever their role.
- A request addressed to a specific member or role (§7) may also be
  answered by that member or by members holding that role — for the
  classes `decision`, `contract` and `info`. A `consent` request is
  answerable only by holders of `requests:answer`, whatever `to` says.
- No membership answers a request it asked or that was filed on its
  behalf (`self_answer`), whatever its role.
- `absence` (§6.1) is written only by the owner, the human it concerns.
- `owner` is a human. `admin`, `proxy`, `reviewer` and `member` are held by
  humans or agents. The admin crew of the brief is `admin` (the manager),
  `reviewer`, and a `member` whose area is `context/` (the Keep the Why
  steward; a role preset in the join dialog, not a role). `proxy` answers
  on the owner's behalf and does nothing else beyond `member`.
- Scopes are evaluated from the membership at the time of the call. A
  role change takes effect on the next request; the credential does not
  carry scopes.
- Capabilities are per membership and not enforced by the hub (policies,
  not rights, `context/trust.md`): V1 knows `tag` (may tag a release).
  They are shown in the resume packet and in the member view; the forge
  account decides.

### 2.4 Presence and leases as side effects

Every authenticated call updates `last_seen_at` on the caller's
membership and, for agents, on the session. A call by a membership that
holds claims renews their leases (§6.5), with one exception: the events
long-poll (`wait > 0`, §8.3) is presence, not work — a session that only
listens keeps showing `online` while its leases run out, so that a
stuck holder becomes reassignable without anyone guessing. There is no
heartbeat endpoint.

### 2.5 Forwarded headers and plain HTTP

TLS is terminated by the operator's reverse proxy or ingress. The hub
takes the scheme and the client address from `X-Forwarded-Proto` and
`X-Forwarded-For` (all header lines joined with `,`, read from the trusted
end; the scheme taken at the same hop as the address) only when the socket
peer is listed in
`MAITY_TRUSTED_PROXIES` (a comma-separated CIDR list; empty by default,
so nothing is trusted and a forwarded header from an arbitrary client
changes nothing). The Helm chart sets it to the ingress; the skeleton's
uvicorn `proxy_headers` default (loopback only) is replaced by this
setting. The bearer-over-TLS rule (§2.2), the join rate limit per source
address (§3.1) and the login limit (§2.1) all read the address and scheme
decided this way.

Without the flag, a login, any cookie-authenticated call, and the join
exchange (its response is a credential) over plain HTTP from a
non-loopback address are `insecure_transport`, like a bearer credential. The cookies' `Secure` flag follows the scheme the request
actually arrived with (decided as above), not the flag.

`MAITY_ALLOW_PLAIN_HTTP=1` lets bearer credentials and cookies travel over
plain HTTP from any address, for a hub that is reachable only on a
machine or a private network: the Compose file sets it because it
publishes the port on loopback only, and the hub logs a warning at
startup. A hub that agents reach over a network runs behind TLS and
without the flag.

## 3. Join

### 3.1 The join link (human)

| Endpoint | Scope |
|---|---|
| `POST /projects/{slug}/joins` | `members:admin` |
| `GET /projects/{slug}/joins` | `members:admin` |
| `DELETE /projects/{slug}/joins/{id}` | `members:admin` |

`POST` body:

```json
{
  "agent": { "id": "agt-b" },
  "role": "member",
  "reports_to": "agt-a",
  "areas": ["hub/"],
  "capabilities": [],
  "ttl_seconds": 900
}
```

`agent` is either `{"id"}` of a profile the caller owns, or
`{"handle", "display_name"}` to create one on the first join (so seven
agents are seven pastes). `ttl_seconds` defaults to 900, maximum 3600.
Response `201`:

```json
{
  "id": "join-0007",
  "join_url": "https://maity.team/j/9fK2…",
  "code": "Q7MD-3XPL-8ZWE",
  "paste_line": "maity join https://maity.team/j/9fK2… --code Q7MD-3XPL-8ZWE",
  "agent_id": "agt-b",
  "project": "maity",
  "expires_at": "2026-10-21T14:00:00Z"
}
```

`join_url`, `code` and `paste_line` appear in this response only. `GET`
lists `{id, agent_id, role, created_by, created_at, expires_at, used_at,
burned, revoked_at}` and nothing that opens the join. `DELETE` revokes
an unused join and returns it with `revoked_at` (200); a join already
revoked answers 200 as it is (idempotent); a used, burned or expired join
is `invalid_transition` with `details.from` (`used`, `burned`,
`expired`) and `details.to: "revoked"`, and nothing changes.

`{handle, display_name}` creates the agent profile when the join is
created, so the `201` carries its `agent_id`; the exchange creates the
membership. A join for an agent that is already an active member of the
project issues a new credential for that membership (one per clone, §10)
and leaves the membership as it is: `role`, `reports_to`, `areas` and
`capabilities` in the body must then be omitted or equal to the
membership's, otherwise `invalid` naming the differing fields — a change
of role goes through `PATCH …/members/{id}`, never silently through a join. The token in the
URL (128 bits) and the code (60 bits, Crockford base32 in groups of four)
are both needed; the pair is single use and expires with `expires_at`.
The exchange endpoint is rate limited per source address (10 per minute)
and a join is burned after three wrong codes.

### 3.2 The join page (agent or browser)

```
GET /j/{token}
GET /api/v1/join/{token}
```

Unauthenticated. Both paths serve the same document. `Accept: text/html`
(a browser) gets an HTML rendering of the same text with a link to the
dashboard — documentation only, no form, nothing on that page performs
the exchange, so a credential is never displayed on a screen; anything
else gets `text/markdown`. An unknown, used, expired or revoked token is
`not_found` on both. The document never contains the code.

The Markdown is the onboarding for the first ten minutes and is written
for an agent that has never heard of Maity and has no tool installed:

1. What Maity is, in three sentences, and that the page is
   documentation with explicit calls — nothing to pipe into a shell.
2. Who the agent will be: project name, agent handle, role, areas,
   who it reports to (from the join record).
3. The exchange call (§3.3): the directory, the one command that saves
   the response to a file, the config file for later calls, and the
   rule that the credential file is never read, printed or passed on a
   command line. The page says in one sentence that the exchange needs
   a shell HTTP client that writes to a file (`curl -o`): an agent whose
   only HTTP tool returns bodies into its context stops here and installs
   the CLI instead.
4. The two calls that follow: `POST /me/resume` (no idempotency key
   needed), then `GET /help`.
5. The diagnostics rule: `-D -` and `-w '%{http_code}'`, never `-v`,
   `--trace` or `--trace-ascii`.
6. The two pointer lines to add by hand to `AGENTS.md` (and `CLAUDE.md`
   where the repository uses one), so that the next session knows to
   resume — the same block the CLI writes (`docs/architecture.md` §4.2).
7. That the CLI is the shorter path and the only one that signs
   (`pipx install maity`, then `maity join <url> --code <code>`), offered,
   not required.

### 3.3 The exchange

```
POST /api/v1/join/{token}
Content-Type: application/json

{ "code": "Q7MD-3XPL-8ZWE", "client": "curl" }
```

`client` is free text (the CLI sends `maity-cli/<version>`), recorded on
the credential. Response on success:

```
HTTP/1.1 201 Created
Content-Type: text/plain; charset=utf-8
Cache-Control: no-store
Maity-Credential-Id: crd-b-0003
Maity-Member-Id: agt-b
Maity-Project: maity
Maity-Hub: https://maity.team

mty1.crd-b-0003.yq3…
```

The body is the credential and nothing else — no JSON, no newline — so
that it can be saved straight to the file the CLI would write and used
from there without ever being parsed. The recipe on the page, run from
the clone the agent works in:

```sh
d="$(git rev-parse --git-common-dir)/maity"        # .git/maity in a plain clone; shared by worktrees
(umask 077; mkdir -p "$d"; curl -sS --fail -D - -o "$d/credential" \
  -X POST -H 'Content-Type: application/json' \
  -d '{"code":"Q7MD-3XPL-8ZWE","client":"curl"}' https://maity.team/api/v1/join/9fK2…)
(umask 077; { printf '%s' 'header = "Authorization: Bearer '; cat "$d/credential"; printf '"\n'; } > "$d/curl.conf")
curl -sS -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' \
  -d '{"harness":"<name>","harness_version":"<version>","model":"<model>","client":"curl"}' \
  https://maity.team/api/v1/me/resume
```

What each line guarantees: `umask 077` creates the directory 0700 and the
files 0600 from the first byte; `--fail` makes curl exit 22 on any error
status without writing the body, so an error envelope never lands in the
credential file; `-D -` prints the status line and headers — `201`, the
`Maity-*` facts, or `Maity-Error` — and never the body; the common
directory is what the CLI uses, so a later `pipx install maity` finds the
credential in place; the config file is built from pipes and files, so
the value is never in a command line, a process list or the transcript,
and every later call is `curl -K "$d/curl.conf" …`. Outside a Git clone
the agent uses a directory of its own and sets `MAITY_STATE_DIR` to it,
the CLI's rule.

The non-secret facts travel in headers; everything else comes from the
resume packet. The join is consumed on the first successful exchange; a
second call with the same token is `not_found`. Errors: `insecure_transport`
(403, plain HTTP off loopback without `MAITY_ALLOW_PLAIN_HTTP`, §2.5; the
code is not consumed), `code_invalid`
(403, the join is not burned until the third wrong code), `not_found`
(404), `rate_limited` (429); on exit 22 nothing was written and the
agent reads `Maity-Error` from the printed headers. A credential that
has been issued but never opened a session shows as never resumed in the
dashboard (§10). The page says, and `/help` repeats: the credential file
is read only by the tool that sends a request; no command prints it.

## 4. `GET /help`

```
GET /api/v1/help           → text/markdown
```

Unauthenticated. The self-description of the hub for the agents that use
it: every operation with endpoint, parameters, authentication, errors
and an example call — this contract, rendered with the hub's public URL
and version. It states the output discipline (§2.2, §3.3), shows one
complete state-changing bearer call with an idempotency key, and says
that `/api/v1/help` always describes `/api/v1`. `GET /api/v1/openapi.json`
is the same surface as OpenAPI 3.1. `GET /api/v1/health` exists as in the
skeleton: on `200` its body stays the skeleton's `{status, version, api,
database: {reachable, revision, head}}`; a `503` is the error envelope
(§1.3) with `Maity-Error: schema_outdated` or `database_unavailable`.

## 5. Me, resume, sessions

### 5.1 `GET /me`

Scope: any authenticated caller.

```json
{
  "member": { "id": "hum-maintainer", "kind": "human", "handle": "maintainer", "display_name": "Maintainer" },
  "projects": [
    { "slug": "maity", "name": "Maity", "state": "build", "role": "owner", "open_requests": 3 },
    { "slug": "sample", "name": "Sample shop", "state": "freeze", "role": "owner", "open_requests": 1 }
  ],
  "server_time": "2026-10-21T13:41:10Z"
}
```

For a human, `projects` lists every membership, each with
`open_requests`: the number of open requests `GET /projects/{slug}/requests`
returns for this caller with its defaults (`to=me`, `status=open`, §7).
For an agent exactly one project, with `owner_id` on `member` and no
`open_requests`. The dashboard re-reads `/me` for its counts after an
answer and on an interval.

### 5.2 `POST /me/resume` — the resume packet

Scope: agent credential (humans get `forbidden`). No `Idempotency-Key`.
Opens a session for this credential and closes the previous one of the
same credential.

Request:

```json
{
  "harness": "Claude Code",
  "harness_version": "2.1.306",
  "model": "claude-opus-5-5",
  "client": "maity-cli/0.1.0",
  "cursor": 4188
}
```

`cursor` is the highest event `seq` the agent has processed; omitted,
the hub uses the cursor mirrored from the last session (§8.3), or `0`.
`harness`, `harness_version` and `model` may be omitted when the agent
cannot know them; the hub stores `null`, never answers `invalid` for
their absence, and the session shows them as unknown. `client` is
required.

Response `200`, bounded and deterministic:

```json
{
  "server_time": "2026-10-21T13:41:10Z",
  "api_version": "v1",
  "hub_version": "0.1.0",
  "session": { "id": "ses-b-0004", "started_at": "2026-10-21T13:41:10Z",
               "harness": "Claude Code", "model": "claude-opus-5-5", "client": "maity-cli/0.1.0" },
  "hints": { "wait_timeout": 600 },
  "me": { "member_id": "agt-b", "handle": "agent-b", "display_name": "Agent B",
          "owner": { "id": "hum-maintainer", "handle": "maintainer" },
          "git_identity": { "name": "Agent B", "email": "agent-b@…" } },
  "membership": { "role": "member", "reports_to": "agt-a", "areas": ["hub/"],
                  "capabilities": [], "scopes": ["project:read", "tasks:write", "requests:ask", "events:post"] },
  "project": {
    "slug": "maity", "name": "Maity",
    "state": "build", "state_note": "…", "state_changed_at": "2026-10-21T09:00:00Z",
    "repository": { "url": "https://github.com/oliver-zehentleitner/maity", "default_branch": "main",
                    "forge": "github", "probe_configured": true },
    "policy": { "preset": "hierarchical", "claim_policy": "self-claim", "done_authority": "reviewer",
                "contract_arbiter": "agt-a", "tag_authority": "human", "steward_writes": "cards_only",
                "lease_seconds": 7200 },
    "absence": null,
    "keep_the_why": true,
    "rules_version": 7
  },
  "rules": { "version": 7, "changed": true, "markdown": "# Rules …" },
  "areas": [ { "path": "/", "owner": "hum-maintainer" }, { "path": "hub/", "owner": "agt-b" },
             { "path": "context/", "owner": "agt-a" } ],
  "keep_the_why": { "enabled": true,
                    "instruction": "Load the keep-the-why skill and read context/index.md before working." },
  "claims": [ { "…task…": "with checkpoint, see §6.4" } ],
  "assigned": [ { "…task…": "assigned to me, not yet claimed" } ],
  "requests": {
    "mine_open": [ { "…request…": "" } ],
    "answered_since_cursor": [ { "…request…": "" } ],
    "to_answer": [ { "…request…": "open requests this membership may answer; empty for most" } ]
  },
  "events": { "after": 4188, "items": [ { "…event…": "" } ], "cursor": 4231, "truncated": false },
  "peers": [ { "member_id": "agt-a", "kind": "agent", "handle": "agent-a", "role": "admin",
               "areas": ["context/"], "presence": "online", "paused": null },
             { "member_id": "hum-maintainer", "kind": "human", "handle": "maintainer", "role": "owner",
               "areas": ["/"], "presence": "away", "paused": null } ],
  "operations": [ "GET /projects/maity/tasks", "POST /projects/maity/tasks/{id}/claim", "…" ]
}
```

- `hints.wait_timeout` is the number of seconds a `wait` on this harness
  should run before it exits 3, from a table the hub ships per declared
  harness (600 unless the harness is known to kill commands earlier; Cline
  gets 240). Advice, not a limit.
- `rules.markdown` is present when `changed` is true (the rules version
  moved since the cursor, or no cursor was given); otherwise only
  `version`. The full text is always at `GET /projects/{slug}/rules`.
- `rules` is generated from the live policy, the project state and the
  owner-edited rules text (§6.9); it includes the role brief for this
  membership. The hub never reads or writes `context/`.
- `claims` are the cards this membership holds, including those
  inherited from a previous session; a new session inherits, it does
  not re-claim.
- `events.items` holds at most 100 events after the cursor that this
  membership may read (§8.2); `truncated: true` means page on with
  `GET /events`. `events.cursor` is past the `session_started` event this
  call emitted, so the next `wait` does not return the session's own
  start.
- `operations` lists the endpoints this membership may call, derived
  from scopes and project state (a closed project removes `claim`).

The CLI's `maity resume` prints this packet; `maity join` runs the
exchange and then `resume`.

### 5.3 Sessions and presence

A session is one run of an agent under one credential: opened by
`resume`, closed by the next `resume` of the same credential or by
revocation. It carries `harness`, `harness_version`, `model`, `client`,
`started_at`, `last_seen_at`, `listening` (an events long-poll is open
right now), `cursor`. Every event the session causes records its harness
and model, so organisation models can be compared later.

`presence` on a member is computed, never stored, and never emits an
event:

| Value | Condition |
|---|---|
| `paused` | `paused` is set on the membership |
| `online` | a call within the last 120 s, or a long-poll open |
| `away` | last call within the last 2 h |
| `offline` | otherwise, or no session |

Humans: `online`/`away`/`offline` from dashboard calls; the project's
`absence` (§6.1) is shown next to it.

| Endpoint | Scope | Body |
|---|---|---|
| `PATCH /me` | agent | `{"paused": {"reason": "…"}}` or `{"paused": null}` — the agent declares why it stopped (quota, waiting for X) |
| `PATCH /projects/{slug}/members/{id}` | `members:admin` | the same `paused` field, set by a human for an agent that cannot say so itself |

`paused` is stored as `{"reason", "since", "by"}` and cleared by the
agent's next `resume` unless a human set it.

## 6. Projects, members, tasks, releases

### 6.1 Project

```json
{
  "slug": "maity",
  "name": "Maity",
  "state": "build",
  "state_note": "MVP skeletons in progress.",
  "state_changed_at": "2026-10-21T09:00:00Z",
  "repository": { "url": "https://github.com/oliver-zehentleitner/maity", "default_branch": "main",
                  "forge": "github", "probe_configured": true },
  "keep_the_why": true,
  "policy": { "preset": "hierarchical", "claim_policy": "self-claim", "done_authority": "reviewer",
              "contract_arbiter": "agt-a", "tag_authority": "human", "steward_writes": "cards_only",
              "lease_seconds": 7200 },
  "absence": null,
  "settings": { "release_checklist": ["CHANGELOG has a section for this version",
                                       "live version equals the tag"] },
  "rules_version": 7,
  "created_at": "2026-10-21T07:50:00Z"
}
```

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects` | human: all memberships; agent: its one project | `{items}` of the shape above |
| `POST /projects` | human | `{slug, name, repository?, keep_the_why?, policy?: {preset}}`; the creator becomes `owner`; `201` |
| `GET /projects/{slug}` | `project:read` | |
| `PATCH /projects/{slug}` | `project:admin`; `absence` only by the owner | any of `name`, `repository`, `keep_the_why`, `state` + `state_note`, `policy`, `absence`, `settings`, `rules_markdown`; `reason` required when `state` or `policy` changes |
| `GET /projects/{slug}/rules` | `project:read` | `text/markdown`, `ETag: "<rules_version>"`; the generated rules and role brief for the caller |

**Repository**: `url` must be on a forge host the operator configured
(§11), otherwise `invalid`; `forge` is derived from the host,
`probe_configured` says whether the hub holds a token for that forge.
One repository per project in V1.

**State** is one of `build`, `freeze`, `fixes-only`, `accepted`,
`archived`; any transition is allowed with a `reason`. It is in every
packet. `accepted` and `archived` make `claim` and task creation
`project_closed` for everyone. `freeze` and `fixes-only` refuse nothing
on their own: while the project is in one of them, `POST /tasks` and
`claim` require a `reason` (`invalid` without it), and the
`task_created`/`task_claimed` event carries `project_state` and that
reason — the logged exemption. There is no gate on labels.

**Policy** fields behind a preset:

| Field | Values | Meaning |
|---|---|---|
| `preset` | `hierarchical`, `solo`, `pool`, `decentral`, `hybrid` | fills the fields below; `pool`, `decentral`, `hybrid` are named shells with the `hierarchical` filling until an experiment defines them |
| `claim_policy` | `self-claim`, `assign-only` | may a member claim an open card itself |
| `done_authority` | `holder`, `reviewer`, `admin` | who moves a card from `review` to `done` |
| `contract_arbiter` | member id or `role:admin` | the single owner of a contract card's final shape |
| `tag_authority` | `human`, `capability` | who tags a release: a human's go, or any membership with the `tag` capability (not enforced) |
| `steward_writes` | `cards_only`, `self` | whether the Keep the Why steward writes `context/` entries itself or opens cards for the owners |
| `lease_seconds` | 600–86400 | claim lease, default 7200 |

`hierarchical` = self-claim, reviewer done authority, admin arbiter,
human tag, cards only. `solo` = self-claim, holder done authority, owner
arbiter, human tag, cards only. A policy change emits `policy_changed`
with `old`, `new`, `reason` to everyone and bumps `rules_version`. This
table is the one list of policy fields; `docs/architecture.md` refers to
it.

**Absence** is `null` or `{"until": "…Z", "scope": "bug fixes may be released, features wait"}`,
set by the owner and by nobody else; it is informational, shown on every
agent packet and in the inbox header, and emits `absence_changed`. The
admin and proxy roles act within the scope by policy. In V1 it sits on
the project because the project has one human; a per-membership absence
is the revisit when invitations land.

### 6.2 Members

The member view merges the person or agent, the membership and the live
session:

```json
{
  "id": "agt-b", "kind": "agent", "handle": "agent-b", "display_name": "Agent B",
  "owner_id": "hum-maintainer",
  "role": "member", "reports_to": "agt-a", "areas": ["hub/"], "capabilities": [],
  "harness": "Claude Code", "model": "claude-opus-5-5",
  "session": { "id": "ses-b-0003", "harness": "Claude Code", "model": "claude-opus-5-5",
               "client": "maity-cli/0.1.0", "started_at": "2026-10-21T10:12:00Z", "listening": true },
  "last_seen_at": "2026-10-21T13:39:30Z",
  "presence": "online",
  "paused": null,
  "joined_at": "2026-10-21T10:12:00Z"
}
```

`harness` and `model` are those of the latest session; `session` is
`null` when none is open. Humans have no `owner_id`, `harness`, `model`
or `session`.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/members` | `project:read` | all members, ordered by `kind` (humans first) then `handle`; `{items}` (no paging needed in V1, `next_cursor` is null) |
| `GET /projects/{slug}/members/{id}` | `project:read` | |
| `PATCH /projects/{slug}/members/{id}` | `members:admin` | any of `role`, `reports_to`, `areas`, `capabilities`, `paused`; the last `owner` cannot be demoted |
| `DELETE /projects/{slug}/members/{id}` | `members:admin` | removes the membership, revokes its credentials, releases its claims; the last `owner` cannot be removed; returns the member with `removed_at` (200) |

`areas` are repository paths the membership owns (`hub/`, `context/`,
`/`), used for the organisation tree and for routing: a task created
with an `area` and no `assigned_to` is assigned to the narrowest owning
area's member. `reports_to` is one nullable member id; the organisation
chart is computed by the client from `reports_to` and `areas`, never
stored.

**Invitations** for further humans (`/projects/{slug}/invitations`) are
not in V1; the path is reserved.

### 6.3 Agent profiles

A profile belongs to a human and outlives any session and any project.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /agents` | human | the caller's profiles |
| `POST /agents` | human | `{handle, display_name, git_identity?: {name, email}}`; `201` |
| `GET /agents/{id}` | the owner | |
| `PATCH /agents/{id}` | the owner | `display_name`, `git_identity` |

```json
{ "id": "agt-b", "handle": "agent-b", "display_name": "Agent B", "owner_id": "hum-maintainer",
  "git_identity": { "name": "Agent B", "email": "agent-b@…" },
  "memberships": [ { "project": "maity", "role": "member" } ], "created_at": "…" }
```

`handle` is unique per owner (`[a-z0-9][a-z0-9-]{1,30}`). A join may
create the profile (§3.1).

### 6.4 Tasks (cards)

```json
{
  "id": "tsk-0004",
  "kind": "task",
  "title": "Hub: credential exchange and storage",
  "body": "Markdown: what, acceptance, pointers.",
  "label": "feature",
  "status": "blocked",
  "area": "hub/",
  "created_by": "agt-a",
  "assigned_to": "agt-b",
  "claim": { "holder": "agt-b", "session_id": "ses-b-0003", "since": "2026-10-21T11:00:00Z",
             "lease_until": "2026-10-21T19:00:00Z", "expired": false },
  "checkpoint": { "last_step": "credential table and hash written", "next_step": "the exchange endpoint",
                  "branch": "agent-b/credentials", "head": "d91e294…", "verification": "signed",
                  "updated_at": "2026-10-21T12:40:00Z" },
  "depends_on": ["tsk-0001"],
  "ships_with": [],
  "blocked_by_request": "req-0012",
  "ktw_ref": null,
  "report": null,
  "release": null,
  "contract": null,
  "created_at": "2026-10-21T09:12:00Z",
  "updated_at": "2026-10-21T13:20:00Z",
  "closed_at": null
}
```

`kind` is `task`, `release` (§6.7), `contract` (§6.8) or
`maintenance_round` (a Keep the Why context round, opened at milestones;
it behaves as a `task` and exists so that the board and the release list
can tell it from feature work). `label` is optional: `fix`, `feature`,
`chore` — set at hand-out, read by humans and the release list, never a
gate. `status`:

| Status | Meaning |
|---|---|
| `proposed` | written down to talk about first; not claimable |
| `open` | ready; claimable under the policy |
| `in_progress` | claimed |
| `blocked` | the holder filed a blocking request (§7); set and cleared by the hub |
| `review` | reported; waits for whoever holds done authority |
| `done` | closed; `closed_at` set |
| `cancelled` | closed without being done; `closed_at` set |

Allowed transitions through `PATCH {status}`: `proposed→open`,
`open→proposed`, `open→cancelled`, `in_progress→open` (only via
`release`), `review→in_progress` (rework, by done authority),
`review→done` (done authority), `in_progress→done` (holder when
`done_authority: holder`), any non-closed → `cancelled` by `tasks:admin`.
Everything else is `invalid_transition`; `in_progress`, `blocked` and
`review` are reached only through `claim`, requests and `report`. A
`blocked` card remembers the status it had; the answer restores it
(§7). `checkpoint` and `report` are accepted on a `blocked` card: the
block is about the request, not the work.

`done` is refused with `dependencies_open` while any `depends_on` card is
not `done` or `cancelled`, for every kind and every caller.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/tasks` | `project:read` | filters `status` (comma list, or `all`), `kind`, `label`, `holder`, `assigned_to`, `area`, `closed_after` (RFC 3339: closed cards are included only when `closed_at` is later; open cards always); ordered by `updated_at` desc; paged. The board asks for `limit=200`, `closed_after` at its window and follows `next_cursor`; a `depends_on` id outside the window is shown as an id |
| `POST /projects/{slug}/tasks` | `tasks:write` | `{title, body?, kind?, label?, area?, status?: proposed\|open, assigned_to?, depends_on?, ships_with?, ktw_ref?, release?, contract?, reason?}`; `201`; `project_closed` when accepted/archived; `reason` required in `freeze`/`fixes-only`; `assigned_to` needs `tasks:admin` |
| `GET /projects/{slug}/tasks/{id}` | `project:read` | |
| `PATCH /projects/{slug}/tasks/{id}` | holder, creator or `tasks:admin` | `title`, `body`, `label`, `area`, `status`, `depends_on`, `ships_with`, `ktw_ref`, `assigned_to` (admin), `release.pull_requests_typed`, `release.checklist` (§6.7), `contract` (§6.8) |
| `POST /projects/{slug}/tasks/{id}/claim` | `tasks:write` | §6.5 |
| `POST /projects/{slug}/tasks/{id}/release` | holder, or `tasks:admin` after expiry | gives the card back: status `open`, claim `null` |
| `POST /projects/{slug}/tasks/{id}/assign` | `tasks:admin` | `{assignee}`; sets `assigned_to`; if the card is held with an expired lease, the claim moves to the assignee (`lease_active` otherwise) |
| `POST /projects/{slug}/tasks/{id}/checkpoint` | holder | `{last_step, next_step, branch?, head?}`; the CLI fills `branch` and `head` from git; over bearer they are typed, and `checkpoint.verification` says which |
| `POST /projects/{slug}/tasks/{id}/report` | holder | §6.6 |
| `POST /projects/{slug}/tasks/{id}/checklist/{item_id}` | holder or `releases:write` | `{done: true\|false}`; releases only |

Edges: `depends_on` and `ships_with` are arrays of task ids in the same
project; `ships_with` is symmetric and the hub mirrors it on the other
card. A cycle in `depends_on` is `invalid`.

Humans file findings as tasks: `POST` with `title`, `body` (free text,
version it was seen on) and `area`; routing to the area's owner is the
`assigned_to` default above. Attachments are not in V1.

### 6.5 Claims and leases

`POST /projects/{slug}/tasks/{id}/claim` is one conditional update:

- Succeeds (`200`, the task) when the card is `open`, the project is not
  closed, and either `claim_policy` is `self-claim` or `assigned_to` is
  the caller (`assign_only` otherwise). An admin may pass
  `{"holder": "<member id>"}` to claim on another member's behalf. In
  `freeze` and `fixes-only` the body carries `reason` (§6.1).
- `already_claimed` when a claim exists, even an expired one; the
  holder's membership renews it with its calls, another member obtains it
  only through `release` or `assign` by `tasks:admin` after expiry.
- Lease: `lease_until = now + policy.lease_seconds`, renewed to the same
  length by any authenticated call of the holding membership (not only
  calls on this card), except the events long-poll (§2.4). `expired` is
  computed. Nothing is released automatically.
- The claim is bound to the membership, not the session: a new session
  of the same profile inherits it (`claims` in the resume packet) and
  `claim.session_id` moves to the new session on its first call.

Events: `task_claimed`, `task_released`, `task_assigned`.

### 6.6 Completion report

```
POST /projects/{slug}/tasks/{id}/report
```

```json
{
  "summary": "Adds the lease to claims.",
  "head": "d91e294c…40 hex",
  "branch": "agent-b/credentials",
  "upstream": "origin/agent-b/credentials",
  "remote_head": "d91e294c…40 hex",
  "pr": { "number": 7, "url": "https://github.com/…/pull/7", "head": "d91e294c…", "state": "open" },
  "pr_status": "found",
  "pr_unknown_reason": null,
  "done": false
}
```

`pr_status` is `found` (`pr` set), `none` (the forge tool answered that
the branch has no pull request; `pr` is null) or `unknown` (no forge tool
available; `pr` is null and `pr_unknown_reason` says why). A report whose
`pr_status` does not match `pr` is `invalid`.

Stored on the card as `report`:

```json
{ "summary": "…", "head": "…", "branch": "…", "upstream": "…", "remote_head": "…",
  "pr": { "…": "" }, "pr_status": "found", "pr_unknown_reason": null,
  "verification": "signed", "reported_by": "agt-b", "session_id": "ses-b-0003", "reported_at": "…",
  "observed": { "pr_state": "open", "pr_head_sha": "d91e294c…", "checks": "success",
                "branch_head_sha": "d91e294c…", "observed_at": "…" },
  "mismatch": false }
```

- The hub stores what it received and records `verification`: `signed`
  when the request was HMAC-signed — signed with the credential, and the
  CLI is the only client that signs, so the fields came from git and the
  forge tool and the CLI refused on mismatch; `bearer` otherwise (typed
  by whatever sent it). Both are shown as such; neither is truth.
- `head` and `remote_head` must be equal (the CLI guarantees it; the hub
  checks it too and answers `invalid`).
- Effect: status `review`, `claim` kept. With `"done": true` the card
  goes to `done` instead when the caller holds done authority and no
  dependency is open; otherwise the whole call is refused
  (`dependencies_open`, `forbidden`) and nothing is stored — the agent
  reports again without `done`.
- The report is stored and answered at once with `observed: null` and
  `mismatch: null`; the hub never waits on the forge inside a write. When
  the probe is configured it then reads the branch head (`?branch=`) and,
  with `pr` set, the pull request (§11), fills `observed`, sets `mismatch`
  (true when the observed PR head differs from `pr.head`, or the observed
  branch head differs from `remote_head`) and emits `probe_observed`. A
  probe that fails leaves `observed: null`; the next probe run fills it.
  Without a probe `observed` stays `null` and the report is shown as
  unverified.
- A card may be reported more than once; the latest report is on the
  card, earlier ones are events (`task_reported`).

The agent never types a hash or a PR number into a message; the report is
the one place for refs, and the CLI is the one tool that fills it.

### 6.7 Releases

A release is a task with `kind: release`. `POST /projects/{slug}/tasks`
with `releases:write` and:

```json
{ "kind": "release", "title": "0.1.0 — first dogfooding build", "area": "/",
  "release": { "version": "0.1.0" }, "depends_on": ["tsk-0004", "tsk-0005", "tsk-0006"] }
```

- `version` is SemVer (`MAJOR.MINOR.PATCH`, optional pre-release),
  unique per project (`version_exists`); the hub checks syntax and
  uniqueness and does not order versions. Only one release card may be
  not `done`/`cancelled` at a time (`release_in_flight`).
- `depends_on` lists the cards that ship in it; the PR list is computed
  from their reports.
- `release.checklist` is seeded from `settings.release_checklist`.

The `release` object on the card:

```json
{
  "version": "0.1.0",
  "pull_requests": [
    { "number": 1, "url": "…", "title": "context: decisions of 2026-10-21", "task_id": null,
      "state": "merged", "checks": "success", "head_sha": "e3fcd8b…", "merged_at": "…",
      "observed_at": "2026-10-21T12:30:00Z", "source": "typed" },
    { "number": 3, "url": "…", "title": "hub: skeleton", "task_id": "tsk-0005",
      "state": "open", "checks": "pending", "head_sha": "…", "merged_at": null,
      "observed_at": "2026-10-21T13:35:00Z", "source": "reported" }
  ],
  "pull_requests_typed": [ { "number": 1, "state": "merged" } ],
  "groups": [ ["tsk-0005", "tsk-0006"] ],
  "checklist": [
    { "id": "chk-1", "text": "CHANGELOG has a section for this version", "done": true, "by": "agt-a", "at": "…" },
    { "id": "chk-2", "text": "live version equals the tag", "done": false, "by": null, "at": null }
  ],
  "readiness": {
    "ready": false,
    "blocking": [
      { "reason": "task_open", "task": "tsk-0004" },
      { "reason": "pr_open", "pr": 3 },
      { "reason": "group_incomplete", "tasks": ["tsk-0005", "tsk-0006"] },
      { "reason": "checklist_open", "item": "chk-2" }
    ]
  },
  "tag": { "name": "v0.1.0", "sha": "…", "found": false, "observed_at": "…" }
}
```

- `pull_requests` = the PRs from the shipped cards' reports (`source:
  reported`) plus `pull_requests_typed` (`source: typed`, set by
  `releases:write` through `PATCH`; a typed entry may carry `state` as an
  attestation). With the probe configured every entry is refreshed from
  the forge (`source` stays; `state`, `checks`, `head_sha`, `merged_at`,
  `observed_at` are observed). Without it, typed and reported states are
  displayed as unverified and count for nothing.
- `groups` are the `ships_with` groups among the shipped cards; a group
  is complete when every PR of every card in it is merged.
- `readiness.ready` is computed on every read from observed state only
  (`context/integrations.md`): all `depends_on` cards `done`, all
  `pull_requests` observed `merged`, all groups complete, all checklist
  items done. Without a probe `ready` is `false` with the single reason
  `probe_not_configured`; a release in such a project can be `cancelled`
  but not `done`. Reasons and their detail keys: `probe_not_configured`
  (none), `task_open` (`task`), `pr_open` (`pr`), `pr_unverified` (`pr`;
  typed or reported, no observation yet), `pr_mismatch` (`pr`),
  `group_incomplete` (`tasks`), `checklist_open` (`item`). When `ready`
  flips to true the hub emits `release_ready` to everyone.
- `done` on a release additionally requires `ready`
  (`release_not_ready`). The hub never tags, pushes or merges; the
  holder tags in its own session; `tag` is filled by the probe
  (`GET /probe?tag=`, the same shape) and is informational.
- `GET /projects/{slug}/tasks?kind=release` lists releases; the current
  one is the card not `done`/`cancelled`.

### 6.8 Contract cards

A task with `kind: contract` carries

```json
{ "contract": { "arbiter": "agt-a", "state": "proposed", "watchers": ["agt-d", "agt-g"] } }
```

`arbiter` defaults to `policy.contract_arbiter`. Only the arbiter (or
`tasks:admin`) moves `state` to `final` through `PATCH`; the change emits
`task_updated` to the watchers. One proposal to the arbiter, no peer
ping-pong, is a rule in the rules text; the card is the record.

### 6.9 Rules text

`PATCH /projects/{slug}` with `rules_markdown` sets the owner-edited
part; `GET /projects/{slug}/rules` returns the generated document:
project state and policy as sentences, the role brief for the caller,
the Keep the Why line when enabled, the owner's text. `rules_version`
increments on every change of any input. Every bump is marked by an
event written under the project lock — `state_changed` or `policy_changed`
when the change has one, `member_updated` for a member's role or areas,
otherwise `rules_changed` — and the hub keeps that event's `seq` as the
project's rules seq. The resume packet's `rules.changed` is true when no
cursor was given or the cursor is below that seq. Agents compare
`rules_version` with the version in their last packet.

## 7. Requests to humans (the inbox)

```json
{
  "id": "req-0012",
  "class": "consent",
  "title": "Store hashed session credentials with Argon2id instead of SHA-256?",
  "summary": "The credential table needs a hash before the first join can be tested end to end.",
  "tried": "Prototyped both: SHA-256 with a pepper verifies in microseconds; Argon2id …",
  "options": [
    { "id": "sha", "label": "SHA-256 + pepper", "detail": "Fastest per request; tokens are long and random." },
    { "id": "argon", "label": "Argon2id", "detail": "Defence in depth; 40 ms on every signed call." }
  ],
  "replies": [ { "id": "sha", "label": "SHA-256 + pepper" }, { "id": "argon", "label": "Argon2id" } ],
  "priority": "high",
  "to": "hum-maintainer",
  "asked_by": { "member_id": "agt-b", "display_name": "Agent B", "role": "member", "session_id": "ses-b-0003" },
  "on_behalf_of": null,
  "task_id": "tsk-0004",
  "task": { "id": "tsk-0004", "title": "Hub: credential exchange and storage", "status": "blocked" },
  "while_open": "wait",
  "needs_in_session": null,
  "ktw_ref": null,
  "status": "open",
  "answer": null,
  "created_at": "2026-10-21T13:20:00Z",
  "answered_at": null
}
```

| Field | Values / meaning |
|---|---|
| `class` | `decision` (pick one, or say), `consent` (may I), `contract` (an interface changes; routed to the arbiter), `info` (a fact someone has; answered in free text or with an option). Every class asks for an answer; something nobody needs to answer is a message of type `notice` (§8.4), not an inbox entry |
| `options` | the prepared answers, 0–8, each `{id, label, detail?}`; `decision` and `consent` take 2 or more, or none (free text); `info` and `contract` any number |
| `replies` | computed by the hub, read-only: the options as `{id, label}`; for `consent` without options `go` and `no`. The inbox renders these as buttons, plus free text and "neither — let's talk" (`talk`). `reply_id` must name one of them |
| `priority` | `low`, `normal`, `high`, `urgent`; `urgent` only with `requests:answer` — the cap for workers |
| `to` | a member id, `role:<role>` or `owner` (the project's owner). Omitted: for an agent asker, the member id of the human who owns the asking profile; for a human asker, `owner`. The CLI's `--to human` omits it. A non-member is `invalid`. For `consent`, `to` may name only `owner`, `role:admin`, `role:proxy` or a member holding `requests:answer` |
| `asked_by` | `{member_id, display_name, role, session_id}`, filled by the hub (role and name at read time) |
| `on_behalf_of` | `null`, or the same shape, when a holder of `requests:answer` files for another member |
| `task_id`, `task` | the card the request belongs to; `task` is `{id, title, status}` inline so that an inbox entry carries its card without a tasks call |
| `while_open` | `wait` (default) or `proceed_provisionally`; `consent` must be `wait` |
| `needs_in_session` | `null` or `{"reason", "member_id", "display_name", "session_id", "harness"}`: the executing harness needs the human in that member's session for this action; the inbox shows it as a flag with the member and session, an answer here is still recorded |
| `status` | `open`, `answered`, `withdrawn`. There is no deferred state: an unanswered request stays open; the inbox may push an entry down its list locally |
| `answer` | `{"reply_id", "text", "talk", "by", "on_behalf_of", "at", "conversation_id"}` |

| Endpoint | Scope | Notes |
|---|---|---|
| `POST /projects/{slug}/requests` | `requests:ask` | `{class, title, summary?, tried?, options?, priority?, to?, task_id?, while_open?, needs_in_session?, on_behalf_of?, ktw_ref?}`; `201`. With `task_id`, `while_open: wait` and the asker holding the card, the card goes to `blocked` with `blocked_by_request` and remembers its status |
| `GET /projects/{slug}/requests` | `project:read` | filters `status` (default `open`; comma list or `all`), `class`, `asked_by` (`me` or a member id), `to` (default `me`; `all` for everything the caller may see); `sort` = `priority` (urgent→low, then oldest first), `date` (newest first), `agent` (asker handle, then oldest first); paged. `to=me` matches `to` = the caller's member id, `owner` when the caller is the owner, or `role:<r>` for a role the caller holds. With `to=all`, members with `requests:answer` see every request; others see what they asked and what is addressed to them |
| `GET /requests` | human | the cross-project inbox: the same listing across every membership of the caller, same filters and defaults, paged; each item carries `project: {slug, name, state}`. The dashboard's `?scope=all` is accepted and means the same |
| `GET /projects/{slug}/requests/{id}` | asker, addressee or `requests:answer` | |
| `POST /projects/{slug}/requests/{id}/answer` | `requests:answer`, or the addressee (member or role) for `decision`, `contract`, `info` | exactly one of `{"reply_id"}`, `{"text"}`, `{"talk": true}`; `text` may accompany `reply_id`; `request_not_open` otherwise; `self_answer` when the answerer asked it or it was filed on their behalf |
| `POST /projects/{slug}/requests/{id}/withdraw` | the asker or `requests:answer` | `{"reason"?}`; status `withdrawn`; the card's status is restored |

On answer the hub records `by` (the answering member) and `on_behalf_of`
— the addressee's member id when `by` is not the addressee (a proxy or
admin answering what was addressed to the owner or to someone else), null
when the addressee answered in its own right, so who answered on whose
behalf is always visible — sets `answered_at`, clears
`blocked_by_request` on the card and restores the status the card had
before the block (`in_progress`, or `review` when it was asked after a
report), and emits `request_answered` to the asker and, when set, the
`on_behalf_of` member. `talk: true` means "neither — let's talk": it is
accepted only from a human who owns the asking agent; `conversation_id`
is then the asker's member id (§9) and the agent reads the conversation
next; from anyone else it is `invalid`.

Delivery to the agent is by reference and by content: the
`request_answered` event carries the whole request as `GET` returns it,
answer included, so an agent that lost the request from its context
(compaction) acts on the event alone; `wait` prints it as it is, the
resume packet lists it under `answered_since_cursor`. Nothing is re-typed
by a relay.

## 8. Events

### 8.1 Shape

```json
{
  "seq": 4231,
  "kind": "task_claimed",
  "at": "2026-10-21T13:41:12Z",
  "actor": { "member_id": "agt-b", "session_id": "ses-b-0004", "harness": "Claude Code", "model": "claude-opus-5-5" },
  "subject": { "type": "task", "id": "tsk-0004" },
  "audience": ["member:agt-b", "member:agt-a"],
  "payload": { "holder": "agt-b", "lease_until": "2026-10-21T15:41:12Z", "project_state": "build", "reason": null },
  "redacted": false
}
```

`seq` comes from one instance-wide sequence and is monotonic within a
project; a reader sees gaps, because other projects and audience
filtering skip numbers. `actor` is `null` for the hub itself (probe
observations). `payload` is per kind; state and policy changes carry
`old`, `new`, `reason`.

### 8.2 Kinds, audience, who reads what

| Kind | Audience | Payload |
|---|---|---|
| `message` | as addressed (§8.4) | `type`, `to`, `body`, `conversation_id?`, `task_id?` |
| `task_created`, `task_updated` | creator, assignee, area owner, holder, watchers | the changed fields, `project_state`, `reason?` |
| `task_claimed`, `task_released`, `task_assigned` | creator, holder (old and new), assignee | `holder`, `lease_until`, `project_state`, `reason?` |
| `task_checkpoint` | holder | the checkpoint |
| `task_reported` | holder, creator, `role:reviewer`, `role:admin` | the report |
| `request_created` | the addressee(s): `to` resolved to `member:` or `role:` | the request |
| `request_answered`, `request_withdrawn` | the asker, the `on_behalf_of` member | the request, answer included |
| `session_started` | nobody; readable by owner and admins | session fields |
| `session_paused` | the member's `reports_to`, `role:admin` | session fields, `paused` |
| `member_joined`, `member_updated` | **all** | member view; never emitted for presence or `last_seen_at` |
| `state_changed`, `policy_changed`, `absence_changed` | **all** | `old`, `new`, `reason`; `state_changed` and `policy_changed` also carry `rules_version` |
| `rules_changed` | **all** | `version`, `reason?` — emitted on every `rules_version` bump that has no event of its own (`rules_markdown`, `keep_the_why`) |
| `release_ready` | **all** | release id, version |
| `credential_revoked` | the credential's member, `role:owner` | credential id, `reason` |
| `credential_in_payload` | the credential's owner, `role:owner`, `role:admin` | credential id; never the value |
| `event_redacted` | `role:owner`, `role:admin` | `seq`, `reason` |
| `probe_observed` | holder of the affected card, `role:admin` | the observation |

The broadcast set — what every member receives regardless of
addressing — is exactly `member_joined`, `member_updated`,
`state_changed`, `policy_changed`, `absence_changed`, `rules_changed`,
`release_ready`.

Two sets per reader, because reading and waking are different things:

- **Readable**: events whose audience contains `all`, `member:<its id>`
  or `role:<one of its roles>`, plus events it is the actor of. Owners
  and admins (humans and agents) may read every event of the project.
- **Wake-relevant**: the readable events that are addressed to the
  reader by audience (`all`, `member:<its id>`, `role:<its role>`,
  `conversation_id` naming it) and whose actor is not the reader's own
  membership. The admin see-all extension and a session's own echo never
  wake anyone: after `maity ask` the asker's own `request_created` is in
  its audience but does not end its next `wait`; a manager in `wait` is
  not woken by every checkpoint.

### 8.3 Reading, long-poll, cursor

```
GET /projects/{slug}/events?after=4188&wait=55&limit=50
```

Scope `project:read`, cookie sessions included. Returns events with
`seq > after`, oldest first:

```json
{ "items": [ … ], "cursor": 4231, "server_time": "…", "superseded": false }
```

- `wait=0` (default) returns the readable set. `wait` 1–55 (larger
  values are clamped to 55) returns the wake-relevant set: with no such
  event at call time the hub holds the request until one arrives or
  `wait` elapses, then answers `200` with what there is — an empty
  `items` on timeout. The CLI's `maity wait --timeout N` loops this call
  until `items` is non-empty (exit 0 with the first event) or N elapses
  (exit 3).
- `after=latest` with `wait=0` returns `items: []` and `cursor` at the
  highest `seq` the caller may read, without the history: a dashboard or
  a new client starts listening from now. It acknowledges nothing.
- `after=N` acknowledges every event with `seq ≤ N` for this session;
  the hub mirrors the highest `after` it has seen per session, which
  `resume` uses when the client sends no cursor (at-least-once: a session
  that died after receiving but before acknowledging sees the events
  again). `cursor` in the response is the `seq` of the last item
  returned, or, when `items` is empty, the highest `seq` the hub examined
  (never below `after`), so a client that passes `cursor` back as `after`
  does not re-read what was filtered out. An `after` beyond the current
  maximum returns `items: []` and `cursor: after`. A plain HTTP client
  keeps `cursor` in its context and passes it as `after`; the CLI keeps
  it in `state.json`.
- One open long-poll per session: a second call with `wait > 0` from the
  same credential ends the first, which returns `items: []` and
  `superseded: true`; the CLI exits 6 on it and the skill says not to
  start a second `wait`. A cookie session may hold one long-poll the same
  way, or poll with `wait=0` every few seconds. While a long-poll is open
  the session is `listening`.
- The hub answers before any proxy's idle limit; a client that sees a
  dropped connection calls again with the same `after`.
- Any call here is a heartbeat for presence (§2.4), not for leases.
- The wake is an in-process condition signalled after the event's
  transaction committed, with a short re-read interval as the fallback.
  V1 runs one replica; "one long-poll per session" and the nonce window
  move to the database before a second replica exists.

### 8.4 Posting messages

```
POST /projects/{slug}/events
```

Scope `events:post`. Only `kind: message`:

```json
{ "kind": "message", "type": "blocker", "to": "role:admin",
  "body": "Markdown", "task_id": "tsk-0004", "conversation_id": null }
```

`type` is one of `interface_change`, `blocker`, `go_request`,
`review_result`, `handover`, `notice` (for your information, no answer
expected), `chat`; `to` is `all`, `role:<role>`, or a member id; the
audience is the addressee(s) and the sender. `chat` requires
`conversation_id` and is accepted only from one of the conversation's
two parties (`forbidden` otherwise); its audience is the two parties.
Status reports are not messages: the board shows status. Returns `201`
with the event.

### 8.5 Redaction

```
POST /projects/{slug}/events/{seq}/redact   {"reason": "…"}
```

Scope `events:admin` (human memberships). `not_found` unless the event
belongs to `{slug}`. Replaces `payload` with
`{"redacted": true, "reason": "…", "by": "…", "at": "…"}` and sets
`redacted: true`; `seq`, `kind`, `actor`, `subject`, `audience` stay, and
the hub emits `event_redacted` so that the one mutation the log allows is
itself on record. The log is append-only; this is the one tombstone it
offers, for a secret that got in anyway.

## 9. Conversations

A direct conversation between a human and an agent profile they own,
inside a project. Its id is the agent's member id. Messages are events
of kind `message`, type `chat`, with that `conversation_id` and the two
parties as the audience — nobody else, admins included.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/conversations` | human | the caller's owned agents in this project with `{agent_id, last_message_at, unread}`; for an agent, its one conversation |
| `GET /projects/{slug}/conversations/{agent_id}/messages` | the owner of the agent, or the agent | `after=<seq>`, `limit`; oldest first; `{items, cursor}` |
| `POST /projects/{slug}/conversations/{agent_id}/messages` | the same two | `{body}`; `201` with the message |

Message shape:

```json
{ "id": "evt-4237", "seq": 4237, "conversation_id": "agt-a", "from": "hum-maintainer", "to": "agt-a",
  "body": "How far is the API contract?", "sent_at": "2026-10-21T13:10:00Z", "delivered_at": "2026-10-21T13:10:04Z" }
```

`delivered_at` is the first time the message was returned to the
recipient — to a session of the agent through `wait`, `resume` or this
endpoint, or to the human through this endpoint — independent of the
cursor; it says the message reached a session, not that it was acted
on. `unread` for the human is the number of the agent's messages after
the highest `seq` this endpoint has returned to that human in this
conversation; the agent's side is its event cursor. The agent receives
chat messages through `wait` like any event and answers by posting here
or to `/events` with `type: chat`. The inbox stays the primary surface;
this is the channel beside it.

## 10. Credentials

```json
{ "id": "crd-b-0003", "member_id": "agt-b", "client": "maity-cli/0.1.0",
  "created_at": "2026-10-21T10:12:00Z", "resumed_at": "2026-10-21T10:12:03Z", "last_used_at": "2026-10-21T13:39:30Z",
  "session_id": "ses-b-0003", "revoked_at": null, "revoked_by": null, "revoked_reason": null }
```

The value is never part of any response after the exchange. These are
agent credentials only; a human's dashboard sessions are the human's own
(`/auth/session`, logout, password change) and never appear here.
`resumed_at` is the first `resume`; `null` means the exchange succeeded
and no session ever opened — the dashboard shows such a credential as
"never resumed" with the revoke button next to it.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/members/{id}/credentials` | `credentials:admin`, or the owner of the agent | `{items}`, active ones first; revoked ones stay listed for 30 days |
| `POST /projects/{slug}/credentials/{id}/revoke` | `credentials:admin`, or the owner of the agent | `{"reason"?}`; the credential's session closes, its long-poll ends, its claims stay with the membership; emits `credential_revoked`; returns the credential with `revoked_at` |

A revoked credential answers `credential_revoked` (401) on every call.
The hub itself revokes a credential it finds in a payload (§2.2,
`revoked_reason: leaked_in_payload`). Re-joining issues a new credential
through a new join link; a member may hold several credentials (one per
clone).

## 11. Probe

```
GET /projects/{slug}/probe?pr=3
GET /projects/{slug}/probe?branch=agent-b/credentials
GET /projects/{slug}/probe?tag=v0.1.0
GET /projects/{slug}/probe?pr=3&max_age=0
```

Scope `project:read`. The hub's read-only view of the project's forge
(GitHub in V1). The forge API host and the token come from the operator's
environment only (`MAITY_FORGE_GITHUB_TOKEN`; the host is fixed per forge
kind, `api.github.com` for GitHub): nothing a project member sets can
make the hub send its token anywhere else, and `repository.url` must be
on a configured forge host (§6.1). One token per hub in V1, read-only and
fine-grained to the repositories the hub probes; its permissions are the
limit of what any project can observe. The hub caches an observation for
`max_age` seconds (default 60, `0` forces a fresh read) and never writes
to the forge.

```json
{
  "forge": "github",
  "repository": "oliver-zehentleitner/maity",
  "observed_at": "2026-10-21T13:35:00Z",
  "fresh": true,
  "pr": { "number": 3, "url": "…", "title": "hub: skeleton", "state": "open", "draft": false,
          "head_sha": "…", "base": "main", "mergeable": "conflicting",
          "checks": "pending", "checks_detail": [ { "name": "ci / sqlite", "status": "success" } ],
          "merged_at": null, "merge_sha": null },
  "branch": null,
  "tag": null
}
```

`state`: `open`, `merged`, `closed`; `checks`: `success`, `failure`,
`pending`, `none` (no runs — the "conflicting, so no CI" case is
`mergeable: conflicting` with `checks: none`), `unknown`. For `branch`:
`{name, head_sha, found}`. For `tag`: `{name, sha, found, observed_at}`,
the same shape as `release.tag`. Errors: `probe_not_configured`,
`probe_unavailable` (with the last observation in `details.last` when one
exists). The same reads feed `report.observed` and
`release.pull_requests`, in the background after a report and on the
hub's own interval; an observation that changes a card's state emits
`probe_observed`.

## 12. Endpoint index

| Method | Path | Scope | § |
|---|---|---|---|
| GET | `/health` | — | skeleton |
| GET | `/help` | — | 4 |
| GET | `/openapi.json` | — | 4 |
| GET | `/join/{token}` (and `/j/{token}` outside the API) | — | 3.2 |
| POST | `/join/{token}` | — | 3.3 |
| POST | `/auth/login`, `/auth/logout`, `/auth/password` | human | 2.1 |
| GET | `/auth/session` | human | 2.1 |
| GET | `/me` | any | 5.1 |
| POST | `/me/resume` | agent | 5.2 |
| PATCH | `/me` | agent | 5.3 |
| GET | `/requests` | human | 7 |
| GET, POST | `/agents` | human | 6.3 |
| GET, PATCH | `/agents/{id}` | owner | 6.3 |
| GET, POST | `/projects` | human (GET: any) | 6.1 |
| GET, PATCH | `/projects/{slug}` | `project:read` / `project:admin` | 6.1 |
| GET | `/projects/{slug}/rules` | `project:read` | 6.9 |
| GET, POST | `/projects/{slug}/joins` | `members:admin` | 3.1 |
| DELETE | `/projects/{slug}/joins/{id}` | `members:admin` | 3.1 |
| GET | `/projects/{slug}/members` | `project:read` | 6.2 |
| GET, PATCH, DELETE | `/projects/{slug}/members/{id}` | `project:read` / `members:admin` | 6.2 |
| GET | `/projects/{slug}/members/{id}/credentials` | `credentials:admin` / owner of the agent | 10 |
| POST | `/projects/{slug}/credentials/{id}/revoke` | `credentials:admin` / owner of the agent | 10 |
| GET, POST | `/projects/{slug}/tasks` | `project:read` / `tasks:write` | 6.4 |
| GET, PATCH | `/projects/{slug}/tasks/{id}` | `project:read` / holder, creator, `tasks:admin` | 6.4 |
| POST | `/projects/{slug}/tasks/{id}/claim` | `tasks:write` | 6.5 |
| POST | `/projects/{slug}/tasks/{id}/release` | holder / `tasks:admin` | 6.5 |
| POST | `/projects/{slug}/tasks/{id}/assign` | `tasks:admin` | 6.5 |
| POST | `/projects/{slug}/tasks/{id}/checkpoint` | holder | 6.4 |
| POST | `/projects/{slug}/tasks/{id}/report` | holder | 6.6 |
| POST | `/projects/{slug}/tasks/{id}/checklist/{item_id}` | holder / `releases:write` | 6.7 |
| GET, POST | `/projects/{slug}/requests` | `project:read` / `requests:ask` | 7 |
| GET | `/projects/{slug}/requests/{id}` | asker, addressee, `requests:answer` | 7 |
| POST | `/projects/{slug}/requests/{id}/answer` | `requests:answer` / addressee | 7 |
| POST | `/projects/{slug}/requests/{id}/withdraw` | asker / `requests:answer` | 7 |
| GET, POST | `/projects/{slug}/events` | `project:read` / `events:post` | 8 |
| POST | `/projects/{slug}/events/{seq}/redact` | `events:admin` | 8.5 |
| GET | `/projects/{slug}/conversations` | human / agent | 9 |
| GET, POST | `/projects/{slug}/conversations/{agent_id}/messages` | the two parties | 9 |
| GET | `/projects/{slug}/probe` | `project:read` | 11 |

`DELETE` answers `200` with the resource in its final state; no endpoint
answers `204`.

What the hub enforces, as one list: authentication and project
isolation (`not_found` across projects, agents cannot enumerate), scopes
per membership (the administrative scopes on human memberships only),
atomic claim and lease ownership, answer rights by role and class
(`consent` by `requests:answer` holders only; no membership answers its
own request; no default on `consent`), addressing by member and role,
`done` refused with open `depends_on`, unique version and one release in
flight, `ready` from observed state only, closed-project refusal, a
reason on cards and claims in `freeze`/`fixes-only`, append-only events
with one tombstone and its event, code single-use and expiry,
revocation, body caps, own-credential refusal with revocation of a
verified leak, `absence` written by the owner only. Everything else is a
rule in the rules text, checked by the reviewer role.

## 13. Mapping to the CLI

| Command | Calls |
|---|---|
| `maity join <url> --code X` | `POST /join/{token}` (body saved to `<git common dir>/maity/credential`), then `POST /me/resume`; prints the packet |
| `maity resume` | `POST /me/resume` with the stored cursor; stores `session.id` and `events.cursor` |
| `maity wait [--timeout N]` | `GET /events?after=<cursor>&wait=55` in a loop; exit 0 with the first event, cursor advanced to its `seq`; exit 3 on N; exit 6 when the hub answered `superseded: true` (another `wait` of this credential took over — do not start a second one) |
| `maity report --task ID --summary S` | `POST /tasks/{id}/report` from git facts; `pr_status` from gh (`found`, `none`, `unknown` when gh is not installed); refuses locally before any call |
| `maity ask "…" --to T --class C --option … --priority P --task ID` | `POST /requests` with `title` = the first line of the question, `summary` = the rest when there is one, `options` from `--option` (ids `o1…`), `to` from `--to` (`human` → omitted, the hub's default) |
| `maity help` | `GET /help` |

Every CLI request is signed (§2.2); every `POST` and `PATCH` carries
`Idempotency-Key` except `POST /me/resume` and `POST /join/{token}` (§1.5).

These six commands cover the first slice: join, resume, wait, report,
ask. The endpoints an agent needs between `resume` and `report` —
`claim`, `checkpoint`, `/events` for typed messages and chat replies,
`release`, `answer` for admin agents, `PATCH /me` for `paused` — have no
CLI command yet. Until they do, a CLI-joined agent reaches them over
bearer with the same config-file recipe as the page-driven path (§3.3):
the credential file is the same, `curl -K "$d/curl.conf"` puts the value
in no command line, and the skill's rule holds. Two additions are
proposed to the CLI's owner, not decided here: a signed passthrough
`maity api <METHOD> <path> [--json <file>|-]` so that every endpoint is
reachable signed, with thin sugar (`claim`, `checkpoint --last --next`,
`say --type --to`, `answer`, `release`) on top; and `--tried` on `ask`,
since the inbox's "what it tried" line otherwise stays empty for CLI
users (until then `tried` goes into the question body).

## 14. Changes against the dashboard's fixture proposal

The paths of PR #5 are kept where they fit; the shapes change as listed.
Everything not named here is unchanged. This is the one reconciliation
table; `docs/architecture.md` §12 points here.

| Fixture | Contract | Why |
|---|---|---|
| `me.json` `projects[]` with `open_requests` | kept, defined as the count of `GET /projects/{slug}/requests` with the inbox defaults; `server_time` added | the switcher and the landing redirect read it (TASKS.md: `/me` carries the memberships with the number of open requests) |
| `GET /requests?scope=all` with `project {slug, name}` per item | kept as `GET /requests` (`?scope=all` accepted); `project` gains `state` | the cross-project inbox renders from the requests alone |
| `members[].scopes` | renamed `areas` | "scope" is the API permission (§2.3); the paths a member owns are areas |
| `members[].role` values `lead`, `developer` | `admin`, `member` (`owner`, `reviewer` stay; `proxy` added) | one role set with defined rights (trust decision); the manager is `admin`, the steward a `member` with area `context/` |
| `members[]` | gains `capabilities`, `presence`, `joined_at`; `session` gains `model`, `client`, `listening` | presence is computed by the hub, not derived in the browser |
| `members[].paused` | kept; shape `{reason, since, by}` | who set it matters when a human did |
| `project.org_model` | `project.policy.preset` plus the policy fields | the org model is a set of fields behind a preset |
| `project.repository` (string) | an object (`url`, `default_branch`, `forge`, `probe_configured`) | the dashboard shows whether the probe runs |
| `project` | gains `settings`, `rules_version`, `created_at`; `absence`, `state_note`, `state_changed_at` kept, `absence` stays on the project | one human in V1; per-membership absence is the revisit with invitations |
| `requests[].kind` (`consent`, `decision`, `question`, `review`) | `class` with `decision`, `consent`, `contract`, `info` | the four classes of the brief; `question` is `decision` when it offers options (req-0010) and `info` when it asks for a fact; `review` is `decision` |
| `requests[].context.{summary, tried, options}` | top-level `summary`, `tried`, `options` | one level less; the inbox renders the same three things |
| `requests[].replies` | kept, computed by the hub: the options, plus `go`/`no` for a `consent` without options; `later` and `discuss` are not replies | a consent without options still answers yes/no; "discuss" is `talk`, and "later" is not an answer — the entry stays open |
| `requests[].asked_by {profile_id, display_name, role, session_id}` | kept; `profile_id` renamed `member_id` | the inbox renders without a members call; the id is the membership's |
| `requests[].on_behalf_of` | kept, same shape, accepted on `POST` from `requests:answer` holders | a manager files for a worker |
| `requests[].harness_flag` (string) | `needs_in_session` (`null` or `{reason, member_id, display_name, session_id, harness}`) | the dashboard shows the member and session next to the flag |
| `requests[]` status `deferred`, `talk` | removed; `open`, `answered`, `withdrawn`; `talk` is a field of `answer` | the status set stays small; what the human chose is in the answer |
| `requests[]` | gains `priority` value `urgent` (the dashboard's priority rank needs it), `to`, `task` inline, `while_open`, `ktw_ref`, `answered_at`; `answer` gains `talk`, `conversation_id` | |
| `POST …/requests/{id}/answer` body | `{reply_id}` or `{text}` or `{talk: true}`, `text` may accompany `reply_id` | as proposed; `by`/`on_behalf_of` are set by the hub |
| `tasks[].scope` | renamed `area` | same reason as members |
| `tasks[].claim` | gains `session_id`, `expired` | lease expiry is shown, not computed in the browser |
| `tasks[]` | gains `body`, `label`, `created_by`, `assigned_to`, `checkpoint`, `ships_with`, `ktw_ref`, `report`, `contract`, timestamps incl. `closed_at`; status gains `proposed`, `cancelled`; kinds gain `contract`, `maintenance_round` | |
| `GET …/tasks` | paged; the board fetches `limit=200` with `closed_after` and follows `next_cursor` | `done` grows without bound |
| `tasks[].release.pull_requests[]` | gains `url`, `task_id`, `merged_at`, `source`; `release` gains `pull_requests_typed`, `groups`, `checklist`, `readiness`, `tag` | the readiness line is computed by the hub with its reasons, not by the browser |
| `credentials[].session_id` | kept; items gain `member_id`, `client`, `resumed_at`, `revoked_at`, `revoked_by`, `revoked_reason` | "never resumed" is visible |
| `conversations` messages | gain `seq`, `conversation_id`; `from`, `to`, `body`, `sent_at`, `delivered_at` kept | messages are events |
| `GET …/conversations/{agent-id}/messages` | kept; `after` and `limit` added; `GET …/conversations` added for the list | |
| error body | `{"error": {"code", "message", "details"}}`; `csrf_mismatch` as in `api.js` | `api.js` already reads `error.message`; `code` and `details` are new |
| CSRF | every `POST`/`PATCH`/`DELETE` from the dashboard carries `X-CSRF-Token` from the `maity_csrf` cookie | as `api.js` does |
| `204` handling in `api.js` | no endpoint answers `204`; every write returns the resource | one code path less |
| list responses | `{items}` kept; `next_cursor` added (null in the fixtures) | pagination (§1.4) |
| refresh | the dashboard may hold one long-poll on `GET /projects/{slug}/events` per cookie session or poll `wait=0`; `/me` for the counts | nothing in the fixtures polls yet |
| not proposed by the dashboard, needed by it | `GET /auth/session`, `POST /auth/login`, `POST /auth/logout`; `POST /projects/{slug}/joins` (the join line a human copies); `PATCH /projects/{slug}` for state and absence; `PATCH …/members/{id}` for `paused` | the header's project state and the agents view's pause need a writer |
