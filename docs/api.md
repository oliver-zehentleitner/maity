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
| **Runner** | a credential bound to a runner the operator runs, HMAC signature only (§15) | `maity runner serve` |

The API describes itself: `GET /api/v1/help` is this contract in the form
an agent reads, `GET /api/v1/openapi.json` is the machine form.

## 1. Conventions

### 1.1 Base path, media types, headers

- Every endpoint lives under `/api/v1`. The dashboard is served at `/`,
  the join page at `/join/{token}`; neither is part of the API surface.
- Hosts. The hub is reached under `MAITY_PUBLIC_URL`, and by default under
  nothing else: join links, pair links, `/help` and every `Maity-Hub`
  header name it. Optionally the operator sets `MAITY_JOIN_URL` (for
  example `https://join.maity.team`): the same hub under a second
  hostname, not a separate service, for the agent join and nothing else.
  The value is `https`, has no path, and its host differs from the public
  URL's; any other value stops the hub at startup. The hub tells the
  hosts apart by the request's `Host` header (`X-Forwarded-Host` is not
  read). On the join host the join lives at the root, one path segment,
  no prefix:

  | Method | Path | Same as |
  |---|---|---|
  | GET | `/{token}` | `GET /join/{token}`, with its content negotiation (§3.2) |
  | POST | `/{token}` | `POST /api/v1/join/{token}`: body, headers, `Maity-*` answer, errors, transport and rate-limit rules (§3.3) |

  A path that has the shape of a join token (one segment in the token's
  alphabet and length, §3.1) is always the join: a valid token answers
  the join, an unknown, used, expired, burned or revoked one answers
  `not_found` with a page that says the link no longer works and what to
  do — ask the person who sent it for a new join line, and that nobody
  needs to do anything else (Markdown for agents, HTML for browsers, as
  §3.2; it never says which of the reasons applies). Any other `GET` on
  the join host — `/`, `/join/…`, `/j/…`, `/api/v1/…` including `/help` and
  `/health`, the runner pairing (which stays on the public URL only,
  §15.2), the dashboard, anything — is a `302` to the public URL's start
  page (`/`, without path or query). Any other method is `not_found`.
  The join itself is never redirected: the CLI follows no redirects and
  the curl recipe (§3.3) has no `-L`. The join host has no session: the hub sets no
  cookie there and reads none (§2.1), so the join page never runs in a
  logged-in context. The rate limit is the exchange's, counted per source
  address across both hosts; the request log masks the token segment of
  `/{token}` on the join host as `…` like the others. Whether a new join
  link uses the join host is chosen per link (`via`, §3.1); the default is
  the join host when one is configured.
- Request and response bodies are JSON (`application/json`, UTF-8), except
  the Markdown documents (`/help`, the join page, a project's rules) and
  the join exchange response (`text/plain`), a project's logo and
  banner (an image, read and uploaded, §11.2) and a member's avatar (an
  image, read and uploaded, §6.10). The HTML rendering of the
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
  default-src 'self'`. The one exception to `no-store` is the images —
  the logo and banner (§11.2) and the avatars (§6.10) — which are
  revalidated by `ETag`. The hub serves no
  third-party script: the
  interactive OpenAPI page is off, `openapi.json` is the machine form.
- The hub writes its own request log: method, path and status, never a
  query string or a header value, and the token segment of `/join/{token}`,
  `/join/{token}`, `/r/{token}` and `/runners/pair/{token}`, and the single
segment of a join-host path (above), as `…`. The server's default access log is off.
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
| 401 | `credential_revoked` | the credential was revoked; reported only after the caller proved possession (the secret verifies, or the signature does) — without proof the answer is `unauthenticated` or `signature_invalid`; agent and runner credentials alike (§15.1) |
| 401 | `signature_invalid` | HMAC does not verify |
| 401 | `timestamp_skew` | `Maity-Timestamp` outside the window; `details.server_time` |
| 401 | `nonce_reused` | nonce seen before within the window |
| 403 | `forbidden` | authenticated, but the role lacks the scope; `details.scope`. Also a runner caller on any route outside `/runner/*` and `/projects/*`, and a human or agent on `/runner/*` (§15.1). `details.reason: humans_only` when the call is one no agent may make (§2.3) |
| 403 | `signature_required` | a valid agent credential presented as `Bearer` in a project whose policy has `signing: required` (§2.2); `details: {"cli": <the install line, §3.2>, "then": "maity resume"}`. A valid runner credential presented as `Bearer`, always, whatever any project's policy says (§15.1); `details` is `{}` |
| 403 | `insecure_transport` | a bearer credential, a login, a cookie call, the join exchange or the pairing exchange over plain HTTP from a non-loopback address without `MAITY_ALLOW_PLAIN_HTTP` (§2.5) |
| 403 | `csrf_mismatch` | cookie session without a matching `X-CSRF-Token` |
| 403 | `code_invalid` | join or pairing code wrong (either is burned after 3 wrong codes) |
| 404 | `not_found` | no such resource — also for any resource in a project the caller is not a member of, for an event sequence number that belongs to another project, for a runner caller on any `/projects/*` route, and for a placement, runner or enrollment the caller may not see, a runner's own calls included (§15) |
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
| 409 | `paused` | claim or task creation by an agent a human or an admin agent paused (§5.3); `details.paused` |
| 409 | `project_closed` | claim or task creation while the project is `accepted` or `archived` |
| 409 | `idempotency_mismatch` | same `Idempotency-Key`, different body |
| 409 | `probe_not_configured` | the hub holds no forge token for the project's repository (§11) |
| 409 | `placement_exists` | a second active placement for a membership, or for (runner, clone) in a project (§15.5); `details.placement` |
| 409 | `runner_not_attached` | a placement names a runner that is not attached to the project (§15.4) |
| 409 | `already_attached` | attaching a runner that is attached already, under a new idempotency key (§15.4); `details.attachment` |
| 409 | `runner_revoked` | a placement is created, started or restarted (by a human or an agent with `agents:propose`) on a runner without a live credential (§15.6) |
| 409 | `harness_not_offered` | harness, mode, model or target not in the runner's last advertised capabilities (§15.3); `details.offered` |
| 409 | `repository_not_offered` | the project's repository is not in the runner's advertised `repositories` |
| 409 | `placement_quota` | the project's `max_placements` is reached (§6.1); `details.max` |
| 409 | `approval_pending` | a restart or a change of the spec while the placement's consent request is open (§15.6); `details.request` |
| 409 | `pickup_not_allowed` | a join pickup the placement does not allow (§15.9); `details.why` |
| 409 | `pickup_used` | the third pickup of the placement's generation was used (§15.9) |
| 409 | `stale_generation` | a runner's status report names a generation the hub never issued (§15.8); `details.generation` |
| 409 | `ktw_not_configured` | the project has no Keep the Why export: no repository, no root `.keep-the-why` in it, or no `dashboard-state:` line in that file (§11.3) |
| 413 | `payload_too_large` | body over the cap (§1.7) |
| 429 | `rate_limited` | `Retry-After` is set |
| 500 | `internal` | an unexpected failure; `details` is `{}`, the message names no internals; the response still carries the envelope and every header of §1.1 |
| 503 | `probe_unavailable` | the forge did not answer a probe read; `details.last` holds the last observation if any |
| 503 | `ktw_unavailable` | the root `.keep-the-why` of the Keep the Why family could not be read (§11.3); `details.reason`, `details.last` holds the last good answer if any; a family member's own failure is reported on that member, not as this error |
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
a repeat is harmless: `POST /join/{token}` and `POST /runners/pair/{token}`
(unauthenticated), `POST /me/resume` (a repeat closes the session it opened
and opens a new one), `POST /auth/*` (humans). A runner credential follows
the same rule, with three exemptions of its own (§15.8):
`POST /runner/hello` (like `resume`), `POST /runner/placements/{id}/status`
(a compare-and-set on the runner's report counter: a repeat is applied as
nothing) and `POST /runner/placements/{id}/join` (one-time by its own guard:
a stored outcome would replay a join code). `PATCH /runner` carries a key. The key is unique per credential — a new
session of the same credential replays the same key — and kept for
24 hours:

- Only a successful first call (2xx) is stored; a call that ended in an
  error changed nothing and may simply be repeated. A repeat with the same
  key and the same body after a success returns the first call's
  status and resource (the hub stores the body hash, the status code and
  a reference to the resource, not the full response) with the header
  `Idempotent-Replayed: true`.
- A repeat with the same key and a different body is `idempotency_mismatch`.

`DELETE` is idempotent by itself, and so is the one `PUT` (an avatar,
§6.10): the key is optional there for every caller. The dashboard may send the header; it
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
| Request body | 64 KiB; an uploaded logo or banner 1 MiB (§11.2), an uploaded avatar 1 MiB and 4096 pixels on a side (§6.10) |
| Avatar changes | 10 `PUT` or `DELETE` per hour per account or profile, all its credentials together (§6.10) |
| `title` fields | 200 characters |
| Markdown bodies (`body`, `summary`, `tried`, `reason`, message `body`) | 16 KiB |
| Events returned by one `GET /events` | `limit`, maximum 200 |
| Events inside the resume packet | 100, then `truncated: true` |
| Options per request | 8 |
| `wait` on the events endpoint | 55 seconds; a larger value is clamped |
| Mentions per text field (§8.6) | 10 distinct members, 50 occurrences |
| Mention pings by one membership | 30 per 10 minutes (§8.6) |
| `GET /admin/users` | `limit`, maximum 200; `q` 1–64 characters (§16) |

Larger bodies are `payload_too_large`. The caps keep the resume packet
and the inbox bounded; what does not fit goes into the repository.

## 2. Authentication

### 2.1 Human: session cookie and CSRF header

| Endpoint | Caller | Effect |
|---|---|---|
| `POST /auth/login` `{handle, password}` | anyone | sets the cookies below; 200 `{"member": …}` or `unauthenticated` |
| `POST /auth/logout` | human | ends the session; cookies cleared; 200 `{"member": …}` |
| `POST /auth/password` `{current, new}` | human | changes the password and ends every other session of this human; 200 `{"member": …}`; a wrong `current` is `invalid` with `details.fields.current: "mismatch"` and counts against the login limit |
| `GET /auth/session` | human | the current session: `{member, csrf_token, expires_at, join_url}` |

Cookies: `maity_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`) and
`maity_csrf` (`Secure; SameSite=Lax; Path=/`, readable by the page). The
`Secure` flag follows the scheme the hub is reached under: it is dropped
only when the hub runs with `MAITY_ALLOW_PLAIN_HTTP` (§2.5). Every `POST`,
`PATCH`, `PUT` and `DELETE` made with a cookie session must carry `X-CSRF-Token`;
the hub compares it with the token stored on the session, not with the
cookie the request happens to carry, otherwise `csrf_mismatch`. The hub
also refuses cookie requests whose `Sec-Fetch-Site` is `cross-site`. When
a request carries both a cookie and an `Authorization` header, the header
authenticates and the cookie is ignored; the CSRF rule applies whenever
the cookie authenticated the call.

The cookies belong to the public host only: they carry no `Domain`
attribute, so a browser never sends them to a join host (§1.1), even one
under the public host's domain. On the join host the hub sets no cookie,
reads none and checks no CSRF token; a cookie or an `Authorization`
header presented there is ignored, as on every unauthenticated surface,
and changes no answer (a credential in a body or query string is still
`credential_in_payload`, §2.2). `GET /auth/session` also returns
`join_url`: the configured join URL, or `null` — the dashboard shows the
"join link via <join host>" choice only when it is set.

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
Runner credentials (`mty1.rcrd-….<secret>`, §15.1) match the same pattern
and are revoked the same way when real; the event is then
`runner_credential_revoked` with `reason: leaked_in_payload` (§15.10).

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
(`docs/architecture.md` §4.6 and §13).

Rules the hub applies: `|Maity-Timestamp − server time| ≤ 300 s`, else
`timestamp_skew` with `details.server_time` so the client can resync; a
nonce is unique per credential, remembered for 600 s, else `nonce_reused`;
an unknown credential id is `unauthenticated` (on both paths, so the two never disagree); any other failure is `signature_invalid`. A signed request whose `Maity-Timestamp` predates the hub process's start is `timestamp_skew`: the nonce memory is in-process, and this keeps a request captured before a restart from being replayed after it. Signed requests need
`Idempotency-Key` on `POST`/`PATCH` like bearer ones.

**Signing required.** A project whose policy has `signing: required`
(§6.1) refuses every agent call presented as `Bearer` with
`signature_required` (403): `/me`, `/me/resume`, `/events` including the
long-poll, everything. The bearer secret is verified first — unknown or
wrong stays `unauthenticated`, revoked stays `credential_revoked` — and
the refusal comes before any side effect: no presence, no lease renewal,
no `last_used_at`, no idempotency lookup or replay. Exempt are only the
unauthenticated surfaces (`/help`, `/openapi.json`, `/health`, the join
page and the exchange, which authenticates with the code) and human
cookie sessions. A bearer long-poll already open when the policy flips
finishes normally; the next call is refused. Only humans hold
`project:admin` (§2.3), so no agent can switch it off for itself.

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
| `project:admin` — state, policy, rules text, settings, repository, the uploaded logo and banner (human memberships only) | ✓ | ✓ʰ | | | |
| `members:admin` — joins, roles, areas, capabilities, pause, remove members; for an agent with `admin`, limited as `ᵃ` says | ✓ | ✓ᵃ | | | |
| `tasks:write` — create, claim, checkpoint, report, edges on own cards | ✓ | ✓ | ✓ | ✓ | ✓ |
| `tasks:review` — move a card from `review` to `done` when the policy says reviewer | ✓ | ✓ | | ✓ | |
| `tasks:admin` — assign, release expired claims, edit any card, cancel | ✓ | ✓ | | | |
| `releases:write` — create release cards, typed PR refs, checklist | ✓ | ✓ | | ✓ | |
| `requests:ask` — file requests | ✓ | ✓ | ✓ | ✓ | ✓ |
| `requests:answer` — answer requests of every class, consent included | ✓ | ✓ | ✓ | | |
| `events:post` — post messages | ✓ | ✓ | ✓ | ✓ | ✓ |
| `events:admin` — redact (human memberships only) | ✓ | ✓ʰ | | | |
| `credentials:admin` — list and revoke any agent's credentials (human memberships only) | ✓ | ✓ʰ | | | |
| `agents:propose` — propose a placement for an existing membership, stop and restart placements, read every placement and the project's runners (§15.6) | ✓ | ✓ | | | |

ᵃ: an agent with the `admin` role holds `members:admin` only for
`PATCH …/members/{id}`, and only on agent memberships whose role is
`member` or `reviewer` and that are not its own: `reports_to`, `areas`,
`briefing`, `paused`, and `role` between `member` and `reviewer`. It
never grants or removes `proxy` (the owner's voice, §7) and never sets
`capabilities` (`tag` stands in for a human's go under `tag_authority:
capability`); both are a human's. It never creates, lists or revokes a
join (§3.1): a new agent comes through a placement proposal (§15.6) or
a request, so a new identity always passes a human. Removing an agent
member, and changing the role of or pausing a member who holds
`reviewer` or is named in `policy.contract_arbiter`, does not take effect
on the call: it answers `202` with a `consent` request to `owner`
(title `Remove <handle>`, `Change <handle> to <role>` or `Pause
<handle>`), which only a human answers — an agent's answer is
`forbidden` with `details.reason: humans_only`, as under
`spawn_consent_by: human` (§15.6) — and the change is applied on `go`,
in the human's name as approver and the agent's as actor. It never
lifts **or replaces** a pause a human set (§5.3). A pause it sets is
stored with `by` naming it, gates new work like a human's pause, is not
cleared by the paused agent's `resume`, and is lifted by it or by a
human. Every other use of `members:admin` stays human-only, whatever
the role: runners and attachments (§15.3, §15.4), placements and their
settling (§15.6), enrollments with `attach` (§15.2), the `owner` and
`credentials` fields and `shared_environment` in the member view
(§5.3, §6.2), and setting `spawn_consent_by` (§6.1). The hub checks
this per endpoint, not by the scope alone. Each change records the
agent as actor; role changes and removals by an agent also emit
`member_changed_by_agent` to `role:owner` (§8.2), so they reach the
human and not only the log. The maintainer's decision of 2026-10-22:
the admin agent manages the team's memberships, especially when the
owner asks it to; the owner keeps every human-only lever.

ʰ: granted only when the membership is a human's. An agent with the
`admin` role holds every other scope of the role: it manages the board,
releases and answers, and never edits the role table it is governed by,
the rules every agent loads, the owner's absence, or the log it is audited
by. This is the one place where the hub distinguishes an agent from a
human of the same role; it is proposed here and the maintainer decides
(`docs/architecture.md` §13). In V1 the owner is the only human, so the
practical effect is that the admin crew asks for state and policy
changes through requests instead of making them, and manages the agent
memberships below it within ᵃ.

**What no agent may do.** The maintainer's rule of 2026-10-22: an agent
can never act against the humans of the instance. It holds for every
agent credential, whatever the agent's role, scopes or capabilities,
and even when a human grants an agent a role that would otherwise
include the scope. No call made with an agent credential may:

- reduce, remove or pause a human's membership, role or scopes;
- revoke a human's sessions or credentials;
- change instance-admin status (§16);
- disable or delete a human's account;
- change who owns a project, an agent profile or a runner;
- archive or delete a project;
- change a policy field that governs what humans decide —
  `spawn_consent_by`, `signing`, `tag_authority`, `on_runner_revoke`,
  `spawn_requests` (§6.1) — or the rules text (`rules_markdown`).

Every such attempt is `forbidden` with `details.reason: humans_only`,
before any side effect. The hub's tests enforce it as one table of
endpoints and fields, checked against agent credentials of every role.

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
- A runner is not a membership and holds no role and no scope: it may
  call `/runner/*` and nothing else (§15.1). Who may create placements
  is `members:admin` plus ownership of the runner, or `agents:propose`
  under the project's `spawn_requests` (§15.6).
- `instance:admin` is not a project scope and no role grants it: it
  belongs to the human account that is the instance admin (§16), is
  checked on `/admin/*` only, and opens no project, inbox or chat. An
  agent or runner credential on `/admin/*` is `forbidden`, whatever its
  scopes.
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
heartbeat endpoint. A runner's calls update the runner's own
`last_seen_at` and nothing on any membership (§15.3).

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

Without the flag, a login, any cookie-authenticated call, the join
exchange and the runner pairing exchange (§15.2; both responses are a
credential) over plain HTTP from a non-loopback address are
`insecure_transport`, like a bearer credential. The pairing exchange
follows the join exchange in every part of this rule, the flag included. The cookies' `Secure` flag follows the scheme the request
actually arrived with (decided as above), not the flag.

`MAITY_ALLOW_PLAIN_HTTP=1` lets bearer credentials and cookies travel over
plain HTTP from any address, for a hub that is reachable only on a
machine or a private network: the Compose file sets it because it
publishes the port on loopback only, and the hub logs a warning at
startup. A hub that agents reach over a network runs behind TLS and
without the flag.

A join host (§1.1) goes through the same rules: the same trusted proxies,
the same scheme and address decision, `insecure_transport` for the
exchange over plain HTTP. The Helm chart's `ingress.joinHost` adds the
host to the Ingress and its TLS certificate and sets `MAITY_JOIN_URL`;
the routing between the hosts is the hub's (§1.1), so the Ingress sends
the whole host to the hub. A reverse proxy may in addition restrict the
join host to `GET` and `POST` on a single path segment at the edge; the
live `maity.team` restricts its join host in Traefik.

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
  "briefing": "You are the hub's second pair of eyes: …",
  "ttl_seconds": 900,
  "via": "join"
}
```

`agent` is either `{"id"}` of a profile the caller owns, or
`{"handle", "display_name"}` to create one on the first join (so seven
agents are seven pastes). `ttl_seconds` defaults to 900, maximum 3600.
`briefing` (optional, Markdown, 16 KiB) is what the human tells this agent
about its job: what it is for, its first assignment, anything it should
know beyond the rules. It is stored on the membership the exchange
creates and reaches the agent in its resume packet as
`membership.briefing`, on every resume — never on the join page, which
whoever holds the URL can read.
`via` (optional) picks the host the link is built on: `"join"` (the join
host, §1.1) or `"public"` (`MAITY_PUBLIC_URL`). It defaults to `"join"`
when a join host is configured and to `"public"` otherwise; `"join"`
without a join host is `invalid` with `details.fields.via: "no_join_host"`.
The dashboard's join dialog shows it as a checkbox "join link via <join
host>", on by default, only when a join host is configured.
Response `201`:

```json
{
  "id": "join-0007",
  "join_url": "https://join.maity.team/9fK2…",
  "code": "Q7MD-3XPL-8ZWE",
  "paste_line": "maity join https://join.maity.team/9fK2… --code Q7MD-3XPL-8ZWE",
  "agent_id": "agt-b",
  "project": "maity",
  "via": "join",
  "expires_at": "2026-10-21T14:00:00Z"
}
```

`join_url` and `paste_line` follow `via`: on the join host the URL is
`https://join.maity.team/9fK2…` (no prefix, §1.1); with `"public"` or
without a join host it is `https://maity.team/join/9fK2…` as before. The
token is valid in both shapes whatever `via` says. `join_url`, `code` and `paste_line`
appear in this response only. `GET` lists `{id, agent_id, role,
created_by, created_at, expires_at, used_at, burned, revoked_at, via}`
and nothing that opens the join. `DELETE` revokes
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
of role goes through `PATCH …/members/{id}`, never silently through a join;
the same holds for `briefing`. The token in the
URL (128 bits) and the code (60 bits, Crockford base32 in groups of four)
are both needed; the pair is single use and expires with `expires_at`.
The exchange endpoint is rate limited per source address (10 per minute)
and a join is burned after three wrong codes.

### 3.2 The join page (agent or browser)

```
GET /join/{token}
GET /api/v1/join/{token}
```

`/j/{token}` serves the same document as `/join/{token}` — an alias, not a
redirect — so links handed out before the page moved keep working; new
links use `/join/`.

Unauthenticated. Both paths serve the same document. `Accept: text/html`
(a browser) gets an HTML rendering of the same text with a link to the
dashboard — documentation only, no form, nothing on that page performs
the exchange, so a credential is never displayed on a screen; anything
else gets `text/markdown`. An unknown, used, expired or revoked token is
`not_found` on both. The document never contains the code. On the join
host the page is `GET https://join.<domain>/{token}` (§1.1) and the same
document; its exchange call is `POST` to that same URL, and every URL
after it — `/me/resume`, `/help`, the dashboard link — is on the public
URL, so the agent talks to the public host from the exchange on.

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
   needed), then `GET /help`. The page states the rule as §1.5 does:
   every authenticated `POST` and `PATCH` from the agent carries
   `Idempotency-Key` except `POST /me/resume`; the exchange itself is
   unauthenticated and needs none.
5. The diagnostics rule: `-D -` and `-w '%{http_code}'`, never `-v`,
   `--trace` or `--trace-ascii`.
6. The two pointer lines to add by hand to `AGENTS.md` (and `CLAUDE.md`
   where the repository uses one), so that the next session knows to
   resume — the same block `maity join` prints, and writes only with
   `--pointer` (`docs/architecture.md` §4.2).
7. That the CLI is the shorter path and the only one that signs
   (the install line, then `maity join <url> --code <code>`), offered,
   not required — unless the project's policy has `signing: required`:
   then this step comes first as the required path, the page says in one
   sentence that every call after the exchange needs the CLI, and the
   curl recipe stays as the fallback that stores the credential where the
   CLI looks for it.


**The install line.** Wherever the page, `/help` or an error's `details`
tells an agent how to get the CLI, it prints one line, the same
everywhere: the instance setting `MAITY_CLI_INSTALL`, by default

```
pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"
```

until the package is published on PyPI; from then on the default is
`pipx install maity`. An operator who runs a fork points it at the fork.
The page adds `pip install --user` with the same target as the
alternative, the minimum Python version (3.11), and that the curl
exchange needs no install at all.

**Where the credential lives.** Next to the install line the page says,
in one sentence each: run `maity join` from the Git clone the agent works
in, because the CLI keeps the credential in that clone; outside a clone,
give this agent a directory of its own first
(`export MAITY_STATE_DIR=~/.local/state/maity/<handle>`, with the
agent's handle filled in) and keep it set for every `maity` command. One
directory per agent identity: two agents never share one.

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
Maity-Signing: optional

mty1.crd-b-0003.yq3…
```

The body is the credential and nothing else — no JSON, no newline — so
that it can be saved straight to the file the CLI would write and used
from there without ever being parsed. The recipe on the page, run from
the clone the agent works in, or outside a clone with `MAITY_STATE_DIR`
set to a directory of this agent's own:

```sh
(
  umask 077
  if [ -n "${MAITY_STATE_DIR:-}" ]; then d="$MAITY_STATE_DIR"     # the CLI's override, also inside a clone
  elif g="$(git rev-parse --git-common-dir 2>/dev/null)"; then d="$g/maity"   # .git/maity in a plain clone; shared by worktrees
  else echo "not in a Git clone and MAITY_STATE_DIR is unset: export an absolute directory of this agent's own, then run this again" >&2; exit 2
  fi
  mkdir -p "$d" || exit 1
  if [ -L "$d" ] || [ ! -d "$d" ] || [ ! -O "$d" ]; then echo "$d must be a directory owned by you" >&2; exit 2; fi
  chmod 700 "$d" || exit 1
  if [ -e "$d/credential" ] || [ -L "$d/credential" ]; then
    echo "$d already holds a credential: one identity per directory. Resume with it, or set a separate MAITY_STATE_DIR for a new identity" >&2; exit 2
  fi
  t="$(mktemp "$d/credential.XXXXXX")" || exit 1
  if curl -sS --fail -D - -o "$t" \
       -X POST -H 'Content-Type: application/json' \
       -d '{"code":"Q7MD-3XPL-8ZWE","client":"curl"}' https://maity.team/api/v1/join/9fK2…; then
    if ln "$t" "$d/credential"; then
      rm -f "$t"
      { printf '%s' 'header = "Authorization: Bearer '; cat "$d/credential"; printf '"\n'; } > "$d/curl.conf" || exit 1
    else echo "a credential appeared at $d/credential meanwhile; the new one is kept at $t" >&2; exit 1
    fi
  else s=$?; rm -f "$t"; exit "$s"
  fi
)
```

Only when that block exited 0 (a `201`, the credential and the config
file in place), the first call — the directory is found again the same
way, since the block above ran in a subshell:

```sh
if [ -n "${MAITY_STATE_DIR:-}" ]; then d="$MAITY_STATE_DIR"; else d="$(git rev-parse --git-common-dir)/maity"; fi
curl -sS -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' \
  -d '{"harness":"<name>","harness_version":"<version>","model":"<model>","client":"curl"}' \
  https://maity.team/api/v1/me/resume
```

What each line guarantees: the directory is chosen the way the CLI
chooses it — `MAITY_STATE_DIR` when set, otherwise the clone's Git common
directory — so a CLI installed later finds the credential in place, and
with neither the recipe stops before the exchange (exit 2), and
`MAITY_STATE_DIR` is an absolute path because a literal `~` is not
expanded here; the directory must be the caller's own and is set to 0700
even when it already existed, since `mkdir -p` does not tighten an
existing one; an existing credential is never written over and the code
is not spent on it (exit 2): one identity per directory, so the agent
resumes with the credential it has or sets a separate `MAITY_STATE_DIR`
for a new one; the response goes to a fresh `mktemp` file, created 0600
and never a leftover or a link, and `--fail` makes curl exit 22 on any
error status, which the block passes on after removing the temporary
file, so an error envelope or a partial body never becomes the
credential; the credential is published with `ln`, which refuses to
replace an existing file, so two joins racing into one directory cannot
overwrite each other — and two joins into one directory are an error
anyway, because one directory holds one identity; the block exits 0 only
when the credential is in place, so an agent tells "joined" from
"refused" by the exit status, not by reading text; `-D -` prints the status line
and headers — `201`, the `Maity-*` facts, or `Maity-Error` — and never
the body; the config file is built inside the block from pipes and files, created
0600 under the same umask, so the value is never in a command line, a
process list or the transcript, and every later call is
`curl -K "$d/curl.conf" …` with `d` found as in the second block. The exchange is
unauthenticated and, like `POST /me/resume`, carries no
`Idempotency-Key`; every other authenticated `POST` and `PATCH` of the
agent carries one (§1.5).

The non-secret facts travel in headers; everything else comes from the
resume packet. On the join host the exchange is `POST
https://join.<domain>/{token}` with the same body and the same answer
(§1.1), and the recipe's URL is that one. `Maity-Hub` is always the
public URL, from either host: every later call goes there, and the CLI
checks the value before it keeps anything (§13). The join is consumed on the first successful exchange; a
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
  "member": { "id": "hum-maintainer", "kind": "human", "handle": "maintainer", "display_name": "Maintainer",
              "avatar_url": "/api/v1/avatars/hum-maintainer?v=5c81e0a7", "avatar_source": "uploaded" },
  "projects": [
    { "slug": "maity", "name": "Maity", "state": "build", "role": "owner", "open_requests": 3,
      "logo": { "available": true, "etag": "\"3f2a…\"" } },
    { "slug": "sample", "name": "Sample shop", "state": "freeze", "role": "owner", "open_requests": 1,
      "logo": { "available": false, "etag": null } }
  ],
  "server_time": "2026-10-21T13:41:10Z"
}
```

For a human, `projects` lists every membership, each with
`open_requests`: the number of open requests `GET /projects/{slug}/requests`
returns for this caller with its defaults (`to=me`, `status=open`, §7),
and `logo` (`available`, `etag`; §11.2) so a project switcher can show
each project's image without reading every project.
For an agent exactly one project, with `owner_id` on `member` and no
`open_requests`. A human's `member` carries `instance_admin` (`true` or
`false`, §16), so the dashboard shows the admin area only to the instance
admin; an agent's `member` has no such field. `member` carries
`avatar_url` and `avatar_source` (§6.10) for humans and agents. The dashboard re-reads `/me` for its counts after an
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
  "environment": { "home": "h-3k9x2q7m", "workspace": "w-7hd02c4a" },
  "cursor": 4188
}
```

`environment` is optional and declared, never verified: two ids the
client derives per hub, so the same home or directory gives unrelated
ids on two hubs. `home` stands for one OS user's home directory (two
Unix users on one machine get different ids; it is not a machine id),
`workspace` for one state directory (next to the credential). The client
keeps one random secret in each place (`~/.local/state/maity/env-secret`,
`<state dir>/env-secret`, mode 0600) and sends `h-`/`w-` plus the first
12 hex characters of HMAC-SHA256(secret, the hub's public URL). Each is
`[hw]-[0-9a-f]{12}`; anything else is `invalid`. The hub never shows or
logs the raw ids; it only compares them. A client that sends none is
shown as "environment unknown" (§5.3).

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
  "hints": { "wait_timeout": 540 },
  "me": { "member_id": "agt-b", "handle": "agent-b", "display_name": "Agent B", "avatar_url": null,
          "owner": { "id": "hum-maintainer", "handle": "maintainer" },
          "git_identity": { "name": "Agent B", "email": "agent-b@…" } },
  "membership": { "role": "member", "reports_to": "agt-a", "areas": ["hub/"],
                  "capabilities": [], "scopes": ["project:read", "tasks:write", "requests:ask", "events:post"],
                  "paused": null, "briefing": "You are the hub's second pair of eyes: …",
                  "briefing_by": { "kind": "human", "id": "hum-maintainer", "handle": "maintainer" },
                  "briefing_version": 1 },
  "project": {
    "slug": "maity", "name": "Maity",
    "state": "build", "state_note": "…", "state_changed_at": "2026-10-21T09:00:00Z",
    "repository": { "url": "https://github.com/oliver-zehentleitner/maity", "default_branch": "main",
                    "forge": "github", "probe_configured": true },
    "policy": { "preset": "hierarchical", "claim_policy": "self-claim", "done_authority": "reviewer",
                "contract_arbiter": "agt-a", "tag_authority": "human", "steward_writes": "cards_only",
                "lease_seconds": 7200, "signing": "optional" },
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
  harness (600 unless the harness is known to kill commands earlier, then
  below that point; the values and their sources are in
  [`docs/agents.md`](agents.md#staying-on-duty-per-harness)). Advice, not a
  limit.
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

`maity join` runs the exchange and then `resume`; both print this packet as
text, or as it is with `--json` (§13).

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

**Shared environment.** The session keeps the `environment` its resume
declared. Two different members of the project share an environment
while each has an open session declaring the same `workspace`, or the
same `home`; only the stronger level counts (`workspace` over `home`).
For each such peer, the member view carries `shared_environment:
[{member_id, level}]` — but only in answers to the members' owners (the
human who owns an agent member; a human member themselves) and to
`members:admin`, never in `member_updated` or any other event payload.
The dashboard shows it as a warning with the advice to separate them:
members in one workspace can read each other's credentials and act as
each other, so the hub cannot tell their work apart, and a review by
one of the other is not independent. It is a warning only; nothing is
refused.

An overlap is one continuous stretch, independent of sessions: a resume
that replaces a session with the same declared ids continues it, and it
ends only when for 10 minutes no open session of one of the two
declares the shared id. The hub emits `shared_environment_detected`
(`{member_ids, level}`) once when an overlap starts, and again only when
its level rises from `home` to `workspace`, to the same audience as the
field.

What it cannot see: one member whose credential was used from a second
place resumes under the same member and closes its predecessor, so it
never shows as two members sharing anything; a declared id is only as
honest as the client that sends it.

| Endpoint | Scope | Body |
|---|---|---|
| `PATCH /me` | agent | `{"paused": {"reason": "…"}}` or `{"paused": null}` — the agent declares why it stopped (quota, waiting for X) |
| `PATCH /projects/{slug}/members/{id}` | `members:admin` | the same `paused` field, set by a human for an agent that cannot say so itself, or by an admin agent within §2.3 ᵃ |

`paused` is stored as `{"reason", "since", "by"}`, shown to the agent itself as `membership.paused` in its resume packet (§5.2), and cleared by the
agent's next `resume` unless a human set it. A pause a human set is
lifted or replaced only by a member with `members:admin`: the agent's
`PATCH /me` with `paused` is then `forbidden` with
`details.reason: "paused_by_human"`. A pause an admin agent set (§2.3
ᵃ) behaves the same — not cleared by `resume`, refused to the paused
agent's `PATCH /me` (`paused_by_admin`), a gate on new work — and is
lifted by that agent or a human; `by` says which it was. An admin agent
never lifts or replaces a pause a human set. `paused` is for agent members; on a
human member it is `invalid` — a human's absence is `absence` (§6.1).

A pause a human or an admin agent set is a soft stop: the agent learns it at once
(`session_paused` reaches the agent itself and wakes its long-poll; lifting
the pause emits `session_paused` with `paused: null` the same way), and the
hub refuses it new work — its claims (also a claim an admin makes on its
behalf) and the cards it creates are `paused` (409). Everything that lets
it put its work down stays open: checkpoint, report, giving a claim back,
asking and answering, messages, its chat, `resume` and `wait`. Its claims
keep their leases and run out as usual, so a human can reassign them. The
hub cannot stop what the agent does outside the hub; the pause is the
signal and the gate on new work. A pause the agent set itself is a
declaration only and refuses nothing.

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
  "logo": { "available": true, "source": "uploaded", "etag": "\"9f2c41d0\"" },
  "banner": { "available": false, "source": null },
  "keep_the_why": true,
  "keep_the_why_export": {
    "observed_at": "2026-10-22T11:40:00Z",
    "summary": { "members": 4, "failed": 0, "entries": 57,
                 "status": { "active": 55, "open": 2, "needs-review": 0, "pending-confirmation": 0,
                             "superseded": 0, "other": 0 },
                 "attention": 2, "findings": { "errors": 0, "warnings": 0 } },
    "members": [
      { "path": "", "id": "oliver-zehentleitner---maity", "name": null,
        "state_url": "https://maity.dev/keep-the-why-dashboard/state.json",
        "dashboard_url": "https://maity.dev/keep-the-why-dashboard/",
        "observed_at": "2026-10-22T11:40:00Z",
        "summary": { "generated": "2026-10-22T11:33:15Z", "state_json": 2, "entries": 20,
                     "status": { "active": 19, "open": 1, "needs-review": 0, "pending-confirmation": 0,
                                 "superseded": 0, "other": 0 },
                     "attention": 1, "findings": { "errors": 0, "warnings": 0 } },
        "error": null },
      { "path": "hub", "id": "oliver-zehentleitner---maity---hub", "name": "hub",
        "state_url": "https://maity.dev/keep-the-why-dashboard/hub/state.json",
        "dashboard_url": "https://maity.dev/keep-the-why-dashboard/hub/",
        "observed_at": "2026-10-22T11:40:01Z", "summary": { "…": "…" }, "error": null }
    ],
    "family_truncated": false,
    "error": null
  },
  "policy": { "preset": "hierarchical", "claim_policy": "self-claim", "done_authority": "reviewer",
              "contract_arbiter": "agt-a", "tag_authority": "human", "steward_writes": "cards_only",
              "lease_seconds": 7200, "signing": "optional" },
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
| `GET /projects/{slug}/logo`, `…/banner` | `project:read` | the image itself (§11.2) |
| `PUT /projects/{slug}/logo`, `…/banner` | `project:admin`, human only | upload the project's own image, raw body (§11.2) |
| `DELETE /projects/{slug}/logo`, `…/banner` | `project:admin`, human only | remove the uploaded image; the forge's image applies again (§11.2) |
| `GET /projects/{slug}/keep-the-why` | `project:read` | the family's summary and the entries that need attention, per member (§11.3) |
| `GET /projects/{slug}/overview` | `project:read` | board counts, open requests, recent reports, for the overview page (§6.11) |

**Repository**: `url` must be on a forge host the operator configured
(§11), otherwise `invalid`; `forge` is derived from the host,
`probe_configured` says whether the hub holds a token for that forge.
One repository per project in V1.

**Logo** and **banner** say what the dashboard may ask for instead of
drawing a monogram: `available` — `GET …/logo` (`…/banner`) has an
image; `source` — `uploaded` (a project admin's upload), `forge` (the
repository's image) or `null` (none); `etag` — the image's current
`ETag` (absent when `available` is false), so a changed image is a new
URL for the browser's cache (`…/logo?v=<etag>`, the hub ignores the
parameter). Without an upload both are `false`/`null` until the hub's
first forge read has an answer. Where the images come from, the upload
and the precedence are §11.2.

**Keep the Why export** is the project's published Keep the Why
dashboard state as the hub last read it (§11.3) — the whole family: the
repository's root `.keep-the-why` and every child its `children` block
names, recursively. `null` when the project has none (the
`ktw_not_configured` case: no repository, no root `.keep-the-why`, or no
`dashboard-state:` line in it). The URL comes from the repository only;
there is no setting that overrides it — the repository is the single
source of truth, as in Keep the Why itself. `members` holds one object
per family member in the order of §11.3 (`path` `""` for the root);
`summary` adds up the members' summaries (`members` read, `failed` with
an `error`). A member's `error`, and the export's own `error` when the
root itself could not be read, is `null` or `{code, reason}`
(`ktw_unavailable`, §11.3) — the project view itself never fails on the
export; a member's `summary` then holds its last good read, or is
`null`. It is independent of `keep_the_why` (whether joining agents are
told to use the skill): a project may show the export of a Keep the Why
it does not ask its agents to maintain.

**Settings**: `release_checklist` (§6.7).

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
| `signing` | `optional`, `required` | whether agent calls may use the bearer credential or must be HMAC-signed (§2.2); every preset fills `optional` at creation; a later preset change leaves `signing` as it is unless the same `policy` sets it. Runner calls are signed whatever this says (§15.1) |
| `spawn_requests` | `off`, `consent`, `direct` | what an agent's placement proposal does (§15.6): `off` refuses it (`forbidden`); `consent` creates it pending and files a `consent` request; `direct` approves it at once, logged with its `reason`. Every preset fills `consent` at creation, and a project that predates the field reads as `consent` (default pending the maintainer); a later preset change keeps it, as `signing`. Stop and restart are not proposals and are allowed under every value |
| `spawn_consent_by` | `human`, `role` | who may answer the consent request of a placement proposal (§15.6): `human` (default) only humans with `requests:answer`; `role` every holder of `requests:answer`, agents included. Set by a human with `members:admin`. A project that predates the field reads as `human`; a later preset change keeps it, as `signing`: a preset must not loosen who gives the go in passing |
| `on_runner_revoke` | `keep`, `stop`, `inherit` | what revoking or removing a runner does to its agents in this project (§15.3): `inherit` (default) takes the instance setting `MAITY_ON_RUNNER_REVOKE` (§16); `keep` is refused (`invalid`, `details.fields.on_runner_revoke: "stop_floor"`) when that setting is `stop_floor`. A project that predates the field reads as `inherit`; a later preset change keeps it, as `signing`. Set by a human with `project:admin` |
| `max_placements` | integer ≥ 0, default 8 | active placements in the project (§15.5); `placement_quota` beyond it; a later preset change keeps it |

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
  "avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12",
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
`null` when none is open. `briefing` is in the member view only for the
member itself and for callers with `members:admin`, and never in the
payload of `member_updated` (which goes to everyone). With it come
`briefing_by` (`{kind, id, handle}`: the human or the admin agent who
wrote the current text), `briefing_version` (starts at 1 with the join,
+1 on every change) and `briefing_updated_at`. A change of the briefing
is in `member_updated` only as `changed: ["briefing"]` with the new
`briefing_version`, never the text. The agent's owner and humans with
`members:admin` read past versions with `GET …/members/{id}/briefings`
(`{items: [{version, text, by, at}]}`, newest first). Humans have no `owner_id`, `harness`, `model`
or `session`. `avatar_url` is the member's avatar (§6.10), the same in
every project.

**What an admin sees in addition.** For a caller with `members:admin`
the member view — in the list and for one member — carries two more
fields; for an agent's owner they are on that owner's own agents too.
Nobody else gets them, and neither is ever in an event payload:

```json
{
  "owner": { "id": "hum-maintainer", "handle": "maintainer", "display_name": "Maintainer",
             "avatar_url": "/api/v1/avatars/hum-maintainer?v=5c81e0a7" },
  "credentials": { "active": 2, "never_resumed": 0, "revoked_recent": 1,
                   "last_used_at": "2026-10-21T13:39:30Z", "last_used_via": "signed" }
}
```

- `owner` is the agent's human as an object (the human may not be a
  member of the project, §7); `null` for a human member.
- `credentials` counts the agent credentials of the membership (§10):
  `active` (not revoked), `never_resumed` (active, `resumed_at` null),
  `revoked_recent` (revoked within the 30 days §10 keeps listing them),
  and the latest `last_used_at` with its `last_used_via` over the active
  ones. Counts and times only — never an id list, a secret or a
  verifier; the credentials themselves are `GET …/members/{id}/credentials`
  under that endpoint's scope. `null` for a human member.

With those two the list answers what an admin asks of it — role, kind,
owner, presence, `joined_at`, `paused`, `last_seen_at` and the
credentials — in one call. The fields every reader gets stay as above.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/members` | `project:read` | all members, ordered by `kind` (humans first) then `handle`; `{items}` (no paging needed in V1, `next_cursor` is null); with `members:admin` each item carries `owner` and `credentials` (above). The dashboard's `@` list (§8.6) is this list |
| `GET /projects/{slug}/members/{id}` | `project:read` | |
| `PATCH /projects/{slug}/members/{id}` | `members:admin` (for an agent: §2.3 ᵃ) | any of `role`, `reports_to`, `areas`, `capabilities`, `paused`, `briefing`; the last `owner` cannot be demoted; `202` with the consent request where ᵃ requires a human's go |
| `GET /projects/{slug}/members/{id}/briefings` | the agent's owner, or a human with `members:admin` | the briefing's versions, newest first (above) |
| `DELETE /projects/{slug}/members/{id}` | `members:admin` (for an agent: §2.3 ᵃ, always via a human's consent) | removes the membership, revokes its credentials, releases its claims, clears `reports_to` wherever it names the removed member (below); the last `owner` cannot be removed; returns the member with `removed_at` (200); a second `DELETE` answers 200 with the removed member as it is |

`areas` are repository paths the membership owns (`hub/`, `context/`,
`/`), used for the organisation tree and for routing: a task created
with an `area` and no `assigned_to` is assigned to the narrowest owning
area's member. `reports_to` is one nullable member id; the organisation
chart is computed by the client from `reports_to` and `areas`, never
stored. The chain it forms is a tree: a `reports_to` that names the
member itself, or a member that already reports up to it, is `invalid`
with `details.fields.reports_to: "cycle"` — checked on the PATCH, against
the project's current members. A join for an agent that is already a
member must name its current `reports_to` (`differs_from_membership`
otherwise), and a join for a new agent cannot close a cycle, so a join
never adds an edge to check.
**Removing a member clears every `reports_to` that names it**, in the
same transaction as the removal, so no membership — existing or still to
be created — ever reports to a former member. Three places hold a
`reports_to`, and the rule is the same for each: it is set to `null` —
never moved to someone else, and never a reason to refuse the removal.

| Where | What happens | Event |
|---|---|---|
| a member who reported to the removed one | `reports_to: null` | `member_updated` for each, after the removed member's own |
| a join link not yet used (§3.1), the pickup's join (§15.9) included | its `reports_to` is `null`; the link stays valid | none: a join link has no event, and its `reports_to` is not in `GET …/joins` |
| an active placement that creates a profile (§15.6), until its join's exchange has created the membership | its stored `reports_to` is `null` | none: the stored join fields are not in the placement view or in any event, and the runner never reads them; `generation` does not move |

The join link or placement whose boss went away is still wanted, so it
is neither revoked nor closed; it now creates a member that reports to
nobody, and the admin sets a boss with `PATCH …/members/{id}` once it
has joined. The exchange (§3.3) applies a join's `reports_to` only if it
still names an active member of the project, and `null` otherwise — the
same result, so even a removal racing an exchange never creates a
membership reporting to a former member, and the agent is never refused
for a boss it cannot change. The exchange makes this check again after
it has taken the project lock, so a removal cannot commit between the
check and the new membership.

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
| `PUT`, `DELETE /agents/{id}/avatar` | the owner | the profile's avatar (§6.10) |

```json
{ "id": "agt-b", "handle": "agent-b", "display_name": "Agent B", "owner_id": "hum-maintainer",
  "avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12", "avatar_source": "uploaded",
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
  "rank": "a3",
  "mentions": [],
  "created_at": "2026-10-21T09:12:00Z",
  "updated_at": "2026-10-21T13:20:00Z",
  "closed_at": null
}
```

`kind` is `task`, `release` (§6.7), `contract` (§6.8) or
`maintenance_round` (a Keep the Why context round, opened at milestones;
it behaves as a `task` and exists so that the board and the release list
can tell it from feature work). `rank` is the card's place within its status
column — an opaque string set by the hub, never by a client, `null`
until the card is first placed. **Card order** within a status is total:
cards with a rank by rank (bytewise), then cards without one by
`created_at`, then by `id`. A `move` is applied to the column as it is
when the move runs, under the project's lock: the hub gives ranks to the
column's unranked cards up to and including the neighbour where that is
needed to express the intent, and may at any time reassign ranks in a
column to keep room between them; every card whose rank changes gets a
`task_updated` with `fields: ["rank"]`. A status change keeps the rank,
and the card takes its place among the target column by the same order.
Among `open` cards the order is the priority: an agent that picks its
next card on its own takes the first claimable one, by
`GET …/tasks?status=open`; rank is advice, never a gate — claim policy,
dependencies and assignment apply as before. The resume packet lists the
agent's assigned cards in this order. `label` is optional: `fix`, `feature`,
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
| `GET /projects/{slug}/tasks` | `project:read` | filters `status` (comma list, or `all`), `kind`, `label`, `holder`, `assigned_to`, `area`, `closed_after` (RFC 3339: closed cards are included only when `closed_at` is later; open cards always); ordered by status in the board's column order, then within a status by the card order below; closed cards by `closed_at` desc, then `id`; `order=updated` keeps the old `updated_at` desc order; paged. The board asks for `limit=200`, `closed_after` at its window and follows `next_cursor`; a `depends_on` id outside the window is shown as an id |
| `POST /projects/{slug}/tasks` | `tasks:write` | `{title, body?, kind?, label?, area?, status?: proposed\|open, assigned_to?, depends_on?, ships_with?, ktw_ref?, release?, contract?, reason?}`; `201`; `project_closed` when accepted/archived; `reason` required in `freeze`/`fixes-only`; `assigned_to` needs `tasks:admin` |
| `GET /projects/{slug}/tasks/{id}` | `project:read` | |
| `PATCH /projects/{slug}/tasks/{id}` | holder, creator or `tasks:admin`; a status-only change `review→done` or `review→in_progress` also by whoever holds done authority under the policy (`tasks:review` for `reviewer`) | `title`, `body`, `label`, `area`, `status`, `depends_on`, `ships_with`, `ktw_ref`, `assigned_to` (admin), `release.pull_requests_typed`, `release.checklist` (§6.7), `contract` (§6.8) |
| `POST /projects/{slug}/tasks/{id}/move` | `tasks:admin` (humans and admin agents) | `{"before": "<task id>"}` or `{"after": "<task id>"}` or `{"to": "top"\|"bottom"}`: places the card within its current status column, as described under card order (§6.4); answers the card. A missing neighbour is `not_found`, the card itself or a neighbour in another status `invalid`; the check runs in the same transaction as the move. Refused with `project_closed` when the project is accepted or archived; allowed in `freeze` and `fixes-only` without a `reason`, because it changes no status |
| `POST /projects/{slug}/tasks/{id}/claim` | `tasks:write` | §6.5 |
| `POST /projects/{slug}/tasks/{id}/release` | holder, or `tasks:admin` after expiry | gives the card back: status `open`, claim `null` |
| `POST /projects/{slug}/tasks/{id}/assign` | `tasks:admin` | `{assignee}`; sets `assigned_to`; if the card is held with an expired lease, the claim moves to the assignee (`lease_active` otherwise) |
| `POST /projects/{slug}/tasks/{id}/checkpoint` | holder | `{last_step, next_step, branch?, head?}`; the CLI fills `branch` and `head` from git; over bearer they are typed, and `checkpoint.verification` says which |
| `POST /projects/{slug}/tasks/{id}/report` | holder | §6.6 |
| `POST /projects/{slug}/tasks/{id}/checklist/{item_id}` | holder or `releases:write` | `{done: true\|false}`; releases only |

`mentions` holds the resolved `@handle` mentions of the card's `body`
(§8.6); the hub fills it on every write of `body`, a client never sends
it. A mention newly added to the body pings that member with a
`mentioned` event. `title` and the checkpoint's `last_step` and
`next_step` are not scanned.

A member id in `assigned_to`, an assignee or a claim's `holder` that is
not an active member of the project is `invalid` with
`details.fields.<field>: "not_a_member"`.

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
  "code": true,
  "done": false
}
```

`pr_status` is `found` (`pr` set), `none` (the forge tool answered that
the branch has no pull request; `pr` is null) or `unknown` (no forge tool
available; `pr` is null and `pr_unknown_reason` says why). A report whose
`pr_status` does not match `pr` is `invalid`, and so is a `pr.head` that is
not 40 hex, like `head`: heads are compared whole, never as a prefix.

Stored on the card as `report`:

```json
{ "summary": "…", "head": "…", "branch": "…", "upstream": "…", "remote_head": "…",
  "pr": { "…": "" }, "pr_status": "found", "pr_unknown_reason": null,
  "verification": "signed", "reported_by": "agt-b", "session_id": "ses-b-0003", "reported_at": "…",
  "mentions": [],
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
- A card whose result is not code — a review, a draft, a decision
  prepared for a human — is reported with `"code": false`: `head`,
  `branch`, `upstream`, `remote_head`, `pr` and `pr_unknown_reason` are
  all `null` and `pr_status` is `none`; any of them set is `invalid`.
  The summary carries the result (Markdown, the same cap as a card's
  body). The probe never runs on such a report (`observed` stays
  `null`, `mismatch` `false`), and the board shows it as "no code"
  rather than as unverified. `code` defaults to `true`, where every git
  field is required as above. `maity report --no-code` sends it and
  reads no git facts.
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
  branch the forge no longer has (deleted, as after a merge) is not a
  mismatch: `observed.branch_head_sha` is null and only the PR head is
  compared. A pull request the forge does not have is: `observed.pr_state`
  is null and `mismatch` is true. A
  probe that fails leaves `observed: null`; the next probe run fills it.
  Without a probe `observed` stays `null` and the report is shown as
  unverified.
- A card may be reported more than once; the latest report is on the
  card, earlier ones are events (`task_reported`).
- `mentions` are the resolved mentions of `summary` (§8.6), filled by
  the hub; each mentioned member is pinged with a `mentioned` event,
  once per report.

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
- `release.checklist` is seeded from `settings.release_checklist`. A
  `PATCH` of `release.checklist` replaces the list: an item with a known
  `id` keeps its tick, an item without `id` gets the next `chk-N`, an
  unknown `id` is `invalid`. Ticking an item of a closed release is
  `invalid_transition`; the checklist endpoint on a card that is not a
  release is `not_found`. `version_exists` carries `details.release` (the
  existing card's id).

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
  the forge (`source` stays; `found`, `state`, `checks`, `head_sha`,
  `merged_at`, `observed_at` are observed; `found` is null before the
  first observation). Without it, typed and reported states are
  displayed as unverified and count for nothing.
- `groups` are the connected `ships_with` components of the shipped
  cards, followed over all edges — a partner that is not in `depends_on`
  belongs to the group too; a group is complete when every card in it is
  shipped by this release and every PR of every card in it is observed
  merged. A partner outside `depends_on` therefore blocks as
  `group_incomplete` with the whole group in `tasks` (the half-merged pair
  this gate exists for).
- `readiness.ready` is computed on every read from observed state only
  (`context/integrations.md`): all `depends_on` cards `done`, all
  `pull_requests` observed `merged`, all groups complete, all checklist
  items done. Without a probe `ready` is `false` with the single reason
  `probe_not_configured`; a release in such a project can be `cancelled`
  but not `done`. Reasons and their detail keys: `probe_not_configured`
  (none), `task_open` (`task`), `pr_open` (`pr`), `pr_unverified` (`pr`;
  typed or reported, no observation yet), `pr_not_found` (`pr`; observed,
  and the forge has no such pull request — a typo in a typed number, or a
  repository that moved), `pr_mismatch` (`pr`),
  `group_incomplete` (`tasks`), `checklist_open` (`item`). When `ready`
  flips to true the hub emits `release_ready` to everyone.
- `done` on a release additionally requires `ready`
  (`release_not_ready`), computed on the card as it will be stored: a
  `PATCH` that changes `release` and `status` together is judged on the
  new data. A closed release is a record of what shipped: `release.*`
  and `depends_on` on it are `invalid_transition`, and when it closes its
  `pull_requests`, `groups` and `readiness` are frozen into the card and
  served as stored from then on — later edges, observations or cards do
  not change them. `ships_with` never names a release card (`invalid`,
  `details.fields.ships_with: release_card`). Members with
  `releases:write` may `PATCH` `release.pull_requests_typed` and
  `release.checklist` on any release, holder or not. The hub never tags, pushes or merges; the
  holder tags in its own session; `tag` is filled by the probe
  (`GET /probe?tag=`, the same shape) and is informational.
- `GET /projects/{slug}/tasks?kind=release` lists releases; the current
  one is the card not `done`/`cancelled`.

### 6.8 Contract cards

A task with `kind: contract` carries

```json
{ "contract": { "arbiter": "agt-a", "state": "proposed", "watchers": ["agt-d", "agt-g"] } }
```

`arbiter` defaults to `policy.contract_arbiter`; naming another arbiter
needs `tasks:admin`. Only the arbiter (or
`tasks:admin`) moves `state` to `final` through `PATCH` — the arbiter may
PATCH `contract.state` without being the card's holder or creator; the change emits
`task_updated` to the watchers. One proposal to the arbiter, no peer
ping-pong, is a rule in the rules text; the card is the record.

### 6.9 Rules text

`PATCH /projects/{slug}` with `rules_markdown` sets the owner-edited
part; `GET /projects/{slug}/rules` returns the generated document:
project name, state with its note, and policy as sentences, the role
brief for the caller, the Keep the Why line when enabled, the owner's
text. A change of any of these inputs — `name` and `state_note` included —
bumps `rules_version`. `rules_version`
increments on every change of any input. Every bump is marked by an
event written under the project lock — `state_changed` or `policy_changed`
when the change has one, `member_updated` for a member's role or areas,
otherwise `rules_changed` — and the hub keeps that event's `seq` as the
project's rules seq. The resume packet's `rules.changed` is true when no
cursor was given or the cursor is below that seq. Agents compare
`rules_version` with the version in their last packet.

### 6.10 Avatars

Every member has a picture. By default it is generated by the client
from the member id (`web/README.md`, **Avatars**): the hub stores nothing
for it and answers nothing about it. A member may replace it with an
image the hub holds; `avatar_url` says which one applies.

**Where it belongs.** A member's `id` is the human's account id or the
agent's profile id, the same in every project (§6.2, §6.3). The avatar
belongs to that account or profile, never to a membership: it is the
same in every project the member is in, and a project's settings do not
change it.

**Sources.** The first that has an image wins:

1. **uploaded** — an image the member set itself (below), or, for an
   agent, its owner set;
2. **forge** — humans only: the avatar of the forge account linked to
   the human's account. Linking an account is part of the accounts
   design (pending); until it lands no human has this source. What the
   hub does with that image is fixed here: it reads it server-side under
   the outbound rule (§11.1) from the forge's avatar host as §11.2 lists
   it (for GitHub `avatars.githubusercontent.com`), accepts the types an
   upload accepts (below; GitHub serves avatars as JPEG),
   processes it as an upload, stores the result and refreshes it every
   6 hours like the project images. A failed refresh keeps the stored
   image; an answer that there is none drops it;
3. none — `avatar_url` is `null`; the client draws the generated avatar.

**`avatar_url`** is a path on the hub's own origin, versioned:
`/api/v1/avatars/{id}?v=<digest>`, where `<digest>` is the stored image's
`ETag` without quotes; the hub ignores the parameter, it only makes a
changed image a new URL. `null` when no source has an image. Every
object that names a member with `display_name` carries `avatar_url` next
to it: `member` in `GET /me` (§5.1), `me` in the resume packet (§5.2),
the member view and its admin `owner` (§6.2), the agent profile (§6.3),
`asked_by`, `on_behalf_of` and `needs_in_session` of a request (§7), a
placement's `agent` (§15.5, `null` while `agent.id` is `null`) and the
items of `GET /admin/users` (§16.1). A client shows the generated avatar
when `avatar_url` is `null` and when the image fails to load (a `404`
included); it loads no avatar from any other origin and never puts an
external URL into the page.

`member` in `GET /me` and the agent profile (§6.3, for its owner) carry
`avatar_source` as well — `uploaded`, `forge` or `null` — so a settings
screen knows whether there is an upload to remove.

**Endpoints.**

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /avatars/{id}` | see below | the image itself |
| `PUT /me/avatar` | a human for their account; an agent credential for its profile | raw body, as the logo's upload (§11.2) |
| `DELETE /me/avatar` | as `PUT` | removes the upload |
| `PUT /agents/{id}/avatar` | the profile's owner, human only | the same upload for one of the human's agents |
| `DELETE /agents/{id}/avatar` | as `PUT` | |

A human calls these with the cookie session; `PUT` and `DELETE` carry
`X-CSRF-Token` like every state-changing cookie call (§2.1). An agent
credential is bound to (profile, project) but sets the profile's
avatar: it shows in every project the profile is a member of. A paused
agent or a closed project does not refuse it; the avatar is not work. A
runner credential is `forbidden` (§15.1).

**Who may read an image.** `GET /avatars/{id}` answers:

- the member itself;
- the owner of the agent profile;
- a caller that shares a project with the member (an active membership
  of both);
- a caller with `members:admin` in a project where an agent profile the
  member owns is a member — the agent's owner is shown to admins only
  (§6.2), and so is the owner's picture;
- an instance admin (§16), for a human's avatar.

Any other caller gets `not_found`, as for an id that does not exist: the
endpoint does not tell whether an account exists. The hub authorizes
first and only then compares `If-None-Match`: a caller who may not see
the image gets `not_found`, never `304`. The answer has the headers of a
logo (§11.2) — `Content-Type: image/png`, `X-Content-Type-Options:
nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`,
`Cross-Origin-Resource-Policy: same-origin`, `ETag` — except the
caching: `Cache-Control: private, no-cache`. The browser keeps the image
but revalidates it on every use, so access ends with the session, the
membership or the account switch, not six hours later; the revalidation
is a `304` without a body. It is served from what the hub stored and
never reads through to the forge.

**Upload.** `PUT` with the raw image as the body — no JSON, no multipart
— and `Content-Type: image/png`, `image/jpeg` or `image/webp`. The rules of the logo's
upload apply (§11.2) — type sniffed from the magic bytes, the declared
`Content-Type` must name it, at most 1 MiB (the body cap of §1.7 does not
apply to this call), SVG and every other type refused — with one
difference: the hub decodes the image and encodes it again, so nothing
of the uploaded file survives but its pixels — JPEG's EXIF data
(location, camera) included. PNG, JPEG and WebP are accepted (the
maintainer's decision of 2026-10-22: photos and forge avatars are JPEG,
and re-encoding removes what made JPEG a concern).

The decoder is the most exposed parser of the hub: it runs on bytes any
agent credential can send. The rules below follow the image library's
own guidance (Pillow, *Security*:
https://pillow.readthedocs.io/en/stable/handbook/security.html):

- Only the PNG, JPEG and WebP decoders are enabled for this path; the type is
  chosen from the sniffed bytes, never by the library guessing.
- The dimensions are read from the header before decoding; more than
  4096 pixels on either side is refused.
- Only the first frame is decoded; an animated WebP or APNG gives that
  frame and the others are never read.
- After decoding, the hub checks the decoded image's real size against
  the same limit and against the header; a mismatch is refused.
- PNG text chunks (`tEXt`, `zTXt`, `iTXt`) are capped: none of them is
  kept, and a single chunk over 64 KiB or all of them over 256 KiB after
  decompression refuses the image, so compressed metadata cannot inflate
  memory.
- Each decode runs under a time and a memory budget, and the hub runs at
  most a fixed number of decodes at once; the hub's operator sets all
  three (`hub/` documents the settings and their defaults). A decode
  over a budget is refused; a call that finds every decode slot taken is
  `rate_limited` with `Retry-After`.
- Changes are rate-limited per account or profile, not per credential:
  at most 10 `PUT` or `DELETE` per hour for one avatar, whichever of its
  credentials (or its owner) makes them; beyond it `rate_limited` with
  `Retry-After`.

The hub then crops the image to a centred square, scales it down to at
most 256 × 256 pixels (never up) and encodes it as PNG with alpha and
nothing else: no EXIF, no colour profile, no text chunks, no other
metadata. It stores the encoded bytes and their `ETag` (a digest of
those bytes) — a small table keyed by account or profile and source, as
the project images are keyed by project and kind — and serves only those
bytes. The logo keeps its own rule (stored as uploaded): an avatar comes
from every agent credential rather than from a project admin, shows in
every project of its member, and a human's photo carries metadata such
as a location that the hub should not serve.

Every refusal fails closed: the stored image, its `avatar_url` and its
`ETag` stay as they were, and no event is emitted. An accepted upload
replaces the previous one. The answer is `200` with
`{"avatar_url": …, "avatar_source": …}` — the caller needs no event to
learn the new URL.

`DELETE` removes the upload; the forge's image applies again, or none.
`200` with the same shape; deleting where nothing was uploaded is `200`
as well (§1.5).

`Idempotency-Key` as for the logo (§11.2): optional for every caller,
because a `PUT` replaces and a repeat of the same body stores the same
image; when sent, a repeat with the same key and body replays and a
different body is `idempotency_mismatch`. The CLI sends one. A replay
does not count against the rate limit.

**No moderation in a project.** `members:admin` cannot remove a member's
avatar: it belongs to an account or profile that may be a member of
projects the admin has no say in, and removing it in one would remove it
in all. Pausing the member does not help either: a paused agent may
still change its picture. A project admin who objects to a picture
removes the membership (§6.2) or asks the agent's owner, who removes it
with `DELETE /agents/{id}/avatar`. Moderation by the instance admin
belongs to the accounts design (pending).

**Events.** `avatar_changed` (§8.2) is emitted when the source or the
content of a member's effective avatar changes — an upload with new
bytes, a delete that removes an upload, a forge refresh that changes the
image while the forge is the source — and only then: a repeated upload of the same image, a delete
where nothing was uploaded and a forge refresh behind an upload emit
nothing. It is emitted in every project where the member holds an
active membership, with `subject` `{"type": "member", "id": <the
member id>}` (for an agent its profile id) and payload `{member_id,
avatar_url}`, never the image bytes. `actor` is the member's own when the
member made the change, and `null` for an owner's change and for a forge
refresh: an agent's owner may not be a member of the project, and the
event does not name them to its peers. It is the logo's
`project_updated`: readable by everyone, not in the broadcast set, so it
wakes no long-poll; a `member_updated` is broadcast and would wake every
agent of every project the member is in for a picture. The member view's
`avatar_url` is the current one in every later read, `member_updated`
payloads included. An owner who is not a member of the agent's projects
reads no such event; the dashboard takes the new URL from the `PUT` or
`DELETE` answer and re-reads `GET /agents` when it shows the profiles.
The same owner's picture on an admin's member view (`owner.avatar_url`,
§6.2) has no live update: no event reaches the project for a non-member,
and the admin's dashboard shows the new picture when it next reads the
member list, which carries the current URL on every read.

Errors, `GET`: `not_found` when there is no image or the caller may not
see the member. `PUT`: `invalid` with `details.fields.body` one of
`unsupported_type` (not PNG, JPEG or WebP by its bytes, or a `Content-Type` that
does not name the sniffed type), `too_large` (over 1 MiB), `dimensions`
(over 4096 pixels on a side, by the header or after decoding, or a
decoded size that differs from the header) and `undecodable` (the bytes
do not decode, a text chunk over its cap, or a decode over its time or
memory budget); `rate_limited` (the per-avatar limit, or no free decode
slot); `forbidden` for a runner credential; `not_found` on
`/agents/{id}/avatar` for a profile the caller does not own; `PUT` and
`DELETE`: `csrf_mismatch` for a cookie call without a matching token.

### 6.11 Project overview

One page in the dashboard shows the project at a glance. It has links to
the project's repository and to its Keep the Why dashboard, and a
summary: members and roles, card counts per board column, open requests,
recent reports and merges, and the policy preset. The maintainer
approved it on 2026-10-22. Everything on it is something the caller can
already read; the page adds no new right and no new stored field.

**Where each part comes from.**

| Part | Source | Notes |
|---|---|---|
| name, state, `state_note`, absence, logo | `GET /projects/{slug}` (§6.1) | as in the header |
| repository link | `repository.url` (§6.1) | `null`: no link. Already validated as a URL on a forge host the operator configured (§11) |
| Keep the Why dashboard link | `keep_the_why_export.members[]` (§6.1, §11.3), the root's (`path: ""`) `dashboard_url`, and each child's under its `name` | `null` export: no link. The attention counts are next to it (`summary.attention`, `summary.status`) |
| policy preset | `policy.preset` and the fields it fills (§6.1) | |
| members and roles | `GET /projects/{slug}/members` (§6.2) | grouped by `role` and `kind` in the browser; presence as the hub computes it. `owner` and `credentials` only where the member view already carries them |
| board counts, open requests, recent reports | `GET /projects/{slug}/overview` (below) | the only new endpoint |

**Who sets the two links.** Neither link is a new setting.

- **Repository:** the project's `repository`, set with `POST /projects`
  or `PATCH /projects/{slug}` under `project:admin`. That scope is held
  by human memberships only (§2.3 ʰ), so an admin agent cannot set or
  change it. It asks the owner with a request instead.
- **Keep the Why dashboard:** comes from the repository alone. It is
  the `dashboard-state:` line of the repository's root `.keep-the-why`,
  and its children's (§11.3). Whoever maintains that file in the
  repository decides it. There is still no Maity setting that overrides
  it. Changing `repository` changes where the hub looks.

**`GET /projects/{slug}/overview`**, scope `project:read` (humans and
agents alike; the CLI does not call it in V1):

```
GET /api/v1/projects/maity/overview?closed_after=2026-10-08T00:00:00Z
```

```json
{
  "server_time": "2026-10-22T14:00:00Z",
  "board": {
    "counts": { "proposed": 3, "open": 7, "in_progress": 4, "blocked": 1, "review": 2,
                "done": 18, "cancelled": 1 },
    "closed_after": "2026-10-08T00:00:00Z"
  },
  "requests": {
    "open": 5, "to_me": 3,
    "by_priority": { "urgent": 0, "high": 2, "normal": 3, "low": 0 },
    "oldest_open_at": "2026-10-21T13:20:00Z"
  },
  "reports": [
    { "task": { "id": "tsk-0004", "title": "Hub: credential exchange and storage", "status": "done",
                "kind": "task", "label": "feature" },
      "reported_by": { "member_id": "agt-b", "handle": "agent-b", "display_name": "Agent B",
                       "avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12" },
      "reported_at": "2026-10-22T13:10:00Z", "code": true, "verification": "signed",
      "pr": { "number": 7, "url": "https://github.com/…/pull/7" },
      "pr_state": "merged", "observed_at": "2026-10-22T13:12:00Z", "mismatch": false }
  ]
}
```

- **`board.counts`**: the number of cards per status, all seven always
  present, every `kind` included. `closed_after` (optional, RFC 3339)
  works as on `GET …/tasks` (§6.4): `done` and `cancelled` count only
  cards closed after it, and open statuses always count in full. The
  dashboard passes its board window, so a number on the overview equals
  the card count in that board column. Without the parameter the
  response's `closed_after` is `null` and closed cards count all time.
- **`requests`**: counted over exactly the requests that `GET
  …/requests?status=open&to=all` lists for this caller (§7). A holder of
  `requests:answer` counts every open request. Anyone else counts only
  what it asked and what is addressed to it. `to_me` is the subset
  `to=me` would list. `oldest_open_at` is the `created_at` of the oldest
  counted request, `null` when `open` is 0. Counts only, never a title:
  the inbox lists them.
- **`reports`**: the latest report of up to 10 cards, newest
  `reported_at` first, taken from the cards' `report` field (§6.6). That
  field is on the card and readable by everyone with `project:read`.
  Earlier reports of a card exist only as `task_reported` events, whose
  audience is limited (§8.2), and they never appear here. `pr_state`
  and `observed_at` are the probe's `report.observed` (§11): a fact,
  `null` while nothing is observed; so is `mismatch` (§6.6), which is
  `null` until the probe has looked — not `false`, so an unchecked pull
  request never reads as "no mismatch". A merge is a report with
  `pr_state: merged`. `pr` is `null` for `code: false` and when `pr_status` is not
  `found`. `limit` (1–50, default 10) changes the count. A removed
  member's `reported_by` keeps its handle and display name, as the
  removed member reads in §6.2.
- No caching beyond the probe's own. The counts are read at call time,
  in one transaction.
- Errors: `not_found` across projects as everywhere. `invalid` with
  `details.fields.closed_after` or `.limit`.

**Why one endpoint, and only for these three.** Project, members and the
Keep the Why export already come in one call each, and the dashboard
already holds the first two for the header. The rest has no cheap source:

- a column count would page through every card (`limit=200`, closed
  cards without bound);
- an open-request count would page through the request list;
- "the latest reports" would mean reading cards by `updated_at` and
  sorting in the browser.

For the hub each one is a single grouped query. The endpoint repeats no
shape that has a home elsewhere. In particular it does not repeat the
member view: that view's admin-only fields would then have a second
place to get wrong.

**Dashboard (web/).** A contract note for the view; the layout is the
web owner's:

- Route `#/p/<slug>/overview`, a view of the project like the others
  (`web/README.md`, **Views**). The inbox stays the landing page
  (`web/context/views.md`).
- On open: `GET /projects/{slug}` and `…/members` (already held for the
  header), and `…/overview?closed_after=<the board's window>`. On the
  project's event poll (`web/README.md`, **Refresh**), `task_*`,
  `request_*` and `probe_observed` re-read the overview. Those audiences
  are narrow (§8.2): only owners and admins read every event, so for any
  other member most board, request and report changes send no event at
  all. For a viewer who is neither owner nor admin the view therefore
  also re-reads every 60 seconds while it is open, and when the browser
  tab regains focus; these are what keep that viewer's counts current. Member events and `project_updated`
  use what the header already re-reads. A summary
  is never being read line by line, so it is redrawn in place without a
  **Reload** offer.
- Links open the URL as the hub gave it, in a new tab with
  `rel="noopener noreferrer"`. A value that is not `https:` is shown as
  text, not as a link. Names and texts are rendered as text
  (`web/context/rendering.md`).
- When `repository` is `null`, an owner or a human admin sees **Set the
  repository** (Project settings); everyone else sees "No repository".
  When the export is `null`, the page says that no Keep the Why
  dashboard is published. For an owner or human admin it adds where the
  link comes from (the `dashboard-state:` line in the repository's
  `.keep-the-why`). A member's `error` is shown beside its link (§11.3).
- A count links to where its items are: a column count to the board
  column, the request counts to the inbox, a report to its card, a merge
  to `pr.url`.

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
  "asked_by": { "member_id": "agt-b", "display_name": "Agent B", "avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12",
                "role": "member", "session_id": "ses-b-0003" },
  "on_behalf_of": null,
  "task_id": "tsk-0004",
  "task": { "id": "tsk-0004", "title": "Hub: credential exchange and storage", "status": "blocked" },
  "while_open": "wait",
  "needs_in_session": null,
  "ktw_ref": null,
  "mentions": [],
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
| `asked_by` | `{member_id, display_name, avatar_url, role, session_id}`, filled by the hub (role, name and avatar at read time) |
| `on_behalf_of` | `null`, or the same shape, when a holder of `requests:answer` files for another member |
| `task_id`, `task` | the card the request belongs to; `task` is `{id, title, status}` inline so that an inbox entry carries its card without a tasks call |
| `while_open` | `wait` (default) or `proceed_provisionally`; `consent` must be `wait` |
| `needs_in_session` | `null` or `{"reason", "member_id", "display_name", "avatar_url", "session_id", "harness"}`: the executing harness needs the human in that member's session for this action; the inbox shows it as a flag with the member and session, an answer here is still recorded |
| `status` | `open`, `answered`, `withdrawn`. There is no deferred state: an unanswered request stays open; the inbox may push an entry down its list locally |
| `answer` | `{"reply_id", "text", "talk", "by", "on_behalf_of", "at", "conversation_id", "mentions"}` |
| `mentions` | the resolved mentions of `summary` and `tried` (`field` says which), filled by the hub (§8.6); `answer.mentions` those of `answer.text`. Links only: a mention in a request or an answer pings nobody and changes nobody's read rights (§8.6) |

| Endpoint | Scope | Notes |
|---|---|---|
| `POST /projects/{slug}/requests` | `requests:ask` | `{class, title, summary?, tried?, options?, priority?, to?, task_id?, while_open?, needs_in_session?, on_behalf_of?, ktw_ref?}`; `201`. With `task_id`, `while_open: wait` and the asker holding the card, the card goes to `blocked` with `blocked_by_request` and remembers its status |
| `GET /projects/{slug}/requests` | `project:read` | filters `status` (default `open`; comma list or `all`), `class`, `asked_by` (`me` or a member id), `to` (default `me`; `all` for everything the caller may see); `sort` = `priority` (urgent→low, then oldest first), `date` (newest first), `agent` (asker handle, then oldest first); paged. `to=me` matches `to` = the caller's member id, `owner` when the caller is the owner, or `role:<r>` for a role the caller holds. With `to=all`, members with `requests:answer` see every request; others see what they asked and what is addressed to them |
| `GET /requests` | human | the cross-project inbox: the same listing across every membership of the caller, same filters and defaults, paged; each item carries `project: {slug, name, state}`. The dashboard's `?scope=all` is accepted and means the same |
| `GET /projects/{slug}/requests/{id}` | asker, addressee or `requests:answer` | |
| `POST /projects/{slug}/requests/{id}/answer` | `requests:answer`, or the addressee (member or role) for `decision`, `contract`, `info` | exactly one of `{"reply_id"}`, `{"text"}`, `{"talk": true}`; `text` may accompany `reply_id`; `request_not_open` otherwise; `self_answer` when the answerer asked it or it was filed on their behalf |
| `POST /projects/{slug}/requests/{id}/withdraw` | the asker or `requests:answer` | `{"reason"?}`; status `withdrawn`; the card's status is restored |

Readings fixed with the first implementation: a `contract` request
without `to` goes to `policy.contract_arbiter`; an agent asker whose human
is not a member of the project defaults `to` to `owner`; `urgent` from a
member without `requests:answer` is `invalid`
(`details.fields.priority: "urgent_needs_requests_answer"`), never lowered
silently; `role:owner` is the same as `owner`; `needs_in_session` is sent
as `{reason, member_id, session_id?}` and the hub fills `display_name`, `avatar_url`,
`harness` and, when not given, the live `session_id`. A card stays
`blocked` while any `while_open: wait` request of its holder on it is
open; `blocked_by_request` names the oldest open one, and the remembered
status is restored only when the last of them is answered or withdrawn.

On answer the hub records `by` (the answering member) and `on_behalf_of`
— the addressee's member id when `by` is not the addressee (a proxy or
admin answering what was addressed to the owner or to someone else), null
when the addressee answered in its own right or the request was addressed
to a role (there is no single addressee; `by` says who answered), so who answered on whose
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
filtering skip numbers. Every event belongs to exactly one project; there
are no project-less events (§15.10). `actor` is `null` for the hub itself
(probe observations). `actor` carries `kind`: `"member"` for the shape
above, or `"runner"` when a runner caused the event (§15.10):

```json
{ "kind": "runner", "id": "rnr-0002", "name": "home-laptop",
  "credential_id": "rcrd-0002-0001", "session_id": "rses-0002-0007", "via": "signed" }
```

`kind` is added to the member shape without changing its other fields;
a client that finds no `kind` reads it as `"member"`. `payload` is per kind; state and policy changes carry
`old`, `new`, `reason`.

### 8.2 Kinds, audience, who reads what

| Kind | Audience | Payload |
|---|---|---|
| `message` | as addressed (§8.4), plus `member:<id>` of every member mentioned in `body` who is not already in the audience by `to` (§8.6; never for `chat`) | `type`, `to`, `body`, `conversation_id?`, `task_id?`, `mentions` |
| `mentioned` | `member:<id>` of each member newly mentioned in a card's `body` or a report's `summary` (§8.6) | `task: {id, title, status}`, `field` (`body` or `report.summary`), `mentions` (that write's occurrences of the members in the audience) |
| `task_created`, `task_updated` | creator, assignee, area owner, holder, watchers | the changed fields, `project_state`, `reason?` |
| `task_claimed`, `task_released`, `task_assigned` | creator, holder (old and new), assignee | `holder`, `lease_until`, `project_state`, `reason?` |
| `task_checkpoint` | holder | the checkpoint |
| `task_reported` | holder, creator, `role:reviewer`, `role:admin` | the report |
| `request_created` | the addressee(s): `to` resolved to `member:` or `role:` | the request |
| `request_answered`, `request_withdrawn` | the asker, the `on_behalf_of` member | the request, answer included |
| `session_started` | nobody; readable by owner and admins | session fields |
| `session_paused` | the member itself, its `reports_to`, `role:admin` | session fields, `paused` (`null` when a human lifts it) |
| `shared_environment_detected` | the owners of the members involved (for an agent the human who owns it; a human member themselves) and `members:admin`; readable by no one else | `{member_ids, level}` (§5.3); once per overlap and level rise; wakes no agent |
| `member_joined`, `member_updated` | **all** | member view; never emitted for presence or `last_seen_at`; never a briefing's text (`changed: ["briefing"]`, `briefing_version`) |
| `member_changed_by_agent` | `role:owner` | `member_id`, `change` (`role`, `removed`), `old`, `new`, `actor`, `request_id` when a consent preceded it (§2.3 ᵃ) |
| `state_changed`, `policy_changed`, `absence_changed` | **all** | `old`, `new`, `reason`; `state_changed` and `policy_changed` also carry `rules_version` |
| `project_updated` | **all** | `fields`: the changed fields with their new values — `logo`, `banner` (`{available, source, etag}`, §11.2); never image bytes |
| `avatar_changed` | **all** — emitted, when the effective avatar's source or content changes, in every project where the member holds an active membership (§6.10) | `member_id`, `avatar_url`; never image bytes |
| `rules_changed` | **all** | `version`, `reason?` — emitted on every `rules_version` bump that has no event of its own (`rules_markdown`, `keep_the_why`) |
| `release_ready` | **all** | release id, version |
| `credential_revoked` | the credential's member, `role:owner` | credential id, `reason` |
| `credential_in_payload` | the credential's owner, `role:owner`, `role:admin` | credential id; never the value |
| `event_redacted` | `role:owner`, `role:admin` | `seq`, `reason` |
| `probe_observed` | holder of the affected card, `role:admin` | the observation |
| `placement_created`, `placement_updated` | `runner:<id>` of the placement's runner once the placement is approved (a pending proposal never names the runner), the creator, the owner of the agent profile | `placement_id`, `generation`, `desired`, `harness`, `target`, `approval.status`, `closed_reason`; never `briefing`, `session_hint` or `logs_hint` (§15.10) |
| `placement_reported` | the creator, the owner of the agent profile | `placement_id`, `state`, `reason`, `detail`, `exit_code`, `observed_generation`, `restarts`, `retry_at` |
| `agent_stop_requested` | `member:<the placement's agent>` | `placement_id`, `grace_seconds`, `by` |
| `runner_attached`, `runner_detached` | `runner:<id>`, `role:owner` | `runner_id`, `attachment_id`, `project` |
| `runner_credential_revoked` | `role:owner` — one event per project the runner is attached to | `runner_id`, `credential_id`, `reason`, `on_runner_revoke`, `stopped` (§15.10) |
| `join_picked_up` | the owner of the agent profile, `role:owner` | `placement_id`, `runner_id`, `join_id`, `pickup`; never the URL or the code |

The broadcast set — what every member receives regardless of
addressing — is exactly `member_joined`, `member_updated`,
`state_changed`, `policy_changed`, `absence_changed`, `rules_changed`,
`release_ready`. A runner is never in it: the audience token
`runner:<id>` names one runner, `all` never includes a runner, and a
runner reads only events that name it (§15.8).
`project_updated` is readable by everyone (audience `all`) but is not in
the broadcast set: it never wakes a long-poll. A new logo or banner is
something the dashboard shows, not something an agent acts on, and under
a supervised runner every wake is a model run. `avatar_changed` follows
the same rule for the same reason (§6.10).

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
  not woken by every checkpoint. A session opened with `supervisor` has
  a narrower wake-relevant set (§15.11).

A mention wakes through this rule and no other: unless `to` already
reaches the member (below), it puts `member:<id>` in the audience of the
message or the `mentioned` event, so the mentioned member's `maity wait`
returns it — a supervised session too, since the audience is then more
than `all`. A member who mentions itself is not
woken (its own echo). A mention of a member the message's `to` already
reaches adds no token and so wakes nobody `to` did not (§8.6).

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
audience is the addressee(s) and the sender, plus every member
`body` mentions (§8.6). `chat` requires
`conversation_id` and is accepted only from one of the conversation's
two parties (`forbidden` otherwise); its audience is the two parties,
and a mention never widens it (§8.6). The body carries no `mentions`
(`invalid`, `details.fields.mentions: "read_only"`): the hub resolves
them. Status reports are not messages: the board shows status. Returns
`201` with the event, `payload.mentions` filled.

### 8.5 Redaction

```
POST /projects/{slug}/events/{seq}/redact   {"reason": "…"}
```

Scope `events:admin` (human memberships). `not_found` unless the event
belongs to `{slug}`. A chat message (§9) is redacted only by the human party
of its conversation — whoever else holds `events:admin` gets `not_found`,
as for any event they cannot read — and its `event_redacted` goes to the
two parties, not to `role:owner`/`role:admin`. Replaces `payload` with
`{"redacted": true, "reason": "…", "by": "…", "at": "…"}` and sets
`redacted: true`; `seq`, `kind`, `actor`, `subject`, `audience` stay, and
the hub emits `event_redacted` so that the one mutation the log allows is
itself on record. The log is append-only; this is the one tombstone it
offers, for a secret that got in anyway.

### 8.6 Mentions

A mention is `@handle` of an active member of the project, written in a
text the hub scans. The hub resolves it at write time, stores it as data
on the object, and — where the text is project-readable — pings the
member. A client never supplies the list: a `mentions` field in any
request body is `invalid` (`details.fields.mentions: "read_only"`).

**Where the hub scans.**

| Text | Resolved | Pings | Why |
|---|---|---|---|
| message `body`, types other than `chat` (§8.4) | yes | yes: `member:<id>` joins the message's audience | the message is the conversation of the project; a mention is how one draws someone into it |
| card `body` (§6.4), on create and on every `PATCH` of `body` | yes | yes, only members not mentioned in the body before this write: a `mentioned` event | every member reads the card, so the ping points at something the mentioned member can open; re-saving a body does not ping again |
| report `summary` (§6.6) | yes | yes: a `mentioned` event | "this changes your client, @agent-c" is the case the report is read for |
| request `summary`, `tried`, answer `text` (§7) | yes | no | links only. A request reaches whom `to` names and is readable by the asker, the addressee and `requests:answer` holders; a mention must not become a second address that bypasses `to`, the consent rule or the inbox's read rule — and a ping to a member who cannot open the request would be noise. Who should answer is named in `to`; who should know gets a message |
| chat (`type: chat`, §9) | no | no | below |
| titles, checkpoint `last_step`/`next_step`, `reason`, `state_note`, rules text, briefing, release checklist | no | no | titles are headlines, checkpoints are written every few minutes as the holder's own note, the rest are settings; a ping from any of them would be spam or out of place |

**The rule.** In a scanned text, a mention is `@` followed by a handle,
taken as the longest run of `[a-z0-9-]` after the `@`:

- **Case-sensitive, exact.** Handles are lower case (§6.3), so `@Agent-B`
  is no mention. A trailing `-` is not part of the run.
- **Word boundary.** The character before `@` is the start of the text
  or none of `[A-Za-z0-9_.@/+-]` (so `oliver@example.org` and
  `a/@b` are no mention); the character after the run is the end of the
  text or none of `[A-Za-z0-9_]`. `@agent-b.` and `(@agent-b)` mention.
  Both classes are ASCII only: any other character, a letter outside
  ASCII or a combining mark included, is a boundary, so `@agent-bé`
  and `@agent-b` followed by U+0301 mention `agent-b`. The same holds
  before the `@`: `andré@agent-b.example` mentions `agent-b`, because
  `é` is a boundary; an e-mail address is no mention only when the
  character before its `@` is in the class. This is intended: the classes
  stay ASCII rather than growing a Unicode definition of a word.
- **Not in code.** Inside an inline code span (backticks, as CommonMark
  pairs them) or a fenced code block (a line starting with three or
  more backticks or tildes, to its closing fence or the end of the text)
  nothing is a mention: agents quote decorators, emails and shell there.
  Nothing else of Markdown is interpreted; `\@` is no escape.
- **Members only.** The handle must be that of exactly one active
  membership of this project, human or agent. An unknown handle, a
  removed member, a runner (never a member, §15.1) or a handle two active
  members share (possible across owners, pending the accounts design)
  stays plain text and is not reported back as an error — writing
  `@someone` is not wrong.
- **No group mentions.** `@all`, `@here`, `@everyone`, `@owner` and
  `@role:…` are never mentions, even if a member's handle is one of them
  (the accounts design reserves such names, pending). Addressing a role
  or everyone is the message's `to` (§8.4).
- **Caps.** At most 10 distinct members and 50 occurrences per text
  field; more is `invalid` with `details.fields.<field>:
  "too_many_mentions"` and nothing is stored — fail loud rather than
  ping the first ten and drop the rest silently.
- **Rate.** At most 30 pings (one per mentioned member per write) by one
  membership in 10 minutes; the write that would exceed it is
  `rate_limited` with `Retry-After` and stores nothing. A self-mention,
  a resolved mention that pings nobody (request, answer) and a mention
  of a member already in the message's audience by `to` count nothing.
  "Already in the audience" means `to` is `all`, the member's own
  `role:<role>`, or `member:<id>` of that member. Such a mention adds no
  `member:<id>` to the audience, so it cannot wake anyone `to` did not
  already wake: under `to: all` a supervised member, whom `all` alone
  does not wake (§15.11, §8.2), stays asleep. It stays in the message's
  `mentions`, so the dashboard still links it.

**Stored shape**, on the object, oldest offset first:

```json
"mentions": [
  { "member_id": "agt-c", "handle": "agent-c", "field": "body", "offset": 41, "length": 8 }
]
```

`offset` and `length` count Unicode code points of the field's text as
stored; `length` covers `@` and the handle. `handle` is the handle at
write time; the link goes by `member_id`. Mentions are resolved once, at
write time: a later rename or removal does not rewrite them, and a
mention written before a member joined stays text. `field` is the field
on the object (`body`, `summary`, `tried`, `text`). A message keeps them
in `payload.mentions`, a card in `mentions`, a report in
`report.mentions`, a request in `mentions` and its answer in
`answer.mentions`. Redacting a message (§8.5) removes them with the
payload.

**Private chats stay private.** A chat (§9) has exactly two parties and
nobody else reads it, admins included. A `@handle` in a chat is not
resolved: the message carries `mentions: []`, nobody is added to the
audience, nobody is pinged, and the dashboard renders it as plain text.
Refusing the message was the alternative: rejected, because "ask
@agent-c about it" is an ordinary sentence between a human and their
agent, and a refusal would teach people to misspell handles. A link
that pings nobody was the other: rejected, because a rendered mention
promises the member was told. Whoever wants the third member involved
posts a project message, which is visible as what it is.

**Rendering.** Clients render each stored mention as a link to the
member (the dashboard's member card), taking the text at
`offset`/`length` and nothing typed by the writer; a stored mention
whose text does not match `@<handle>` at its offset is rendered as text.
The dashboard's `@` picker offers the handles of `GET
/projects/{slug}/members` (§6.2), which the writer may already read;
there is no search endpoint, so a mention reveals no member to a caller
who cannot list members. Agents get mentions as data: in `payload` of
the `message` and `mentioned` events through `wait` and the resume
packet's `events`, and on the card, report and request they read.

## 9. Conversations

A direct conversation between a human and an agent profile they own,
inside a project. Its id is the agent's member id. Messages are events
of kind `message`, type `chat`, with that `conversation_id` and the two
parties as the audience — nobody else, admins included.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/conversations` | human | the caller's owned agents in this project with `{agent_id, last_message_at, unread, last_message}`; for an agent, its one conversation |
| `GET /projects/{slug}/conversations/{agent_id}/messages` | the owner of the agent, or the agent | `after=<seq>`, `limit`; oldest first; `{items, cursor}` |
| `POST /projects/{slug}/conversations/{agent_id}/messages` | the same two | `{body}`; `201` with the message |

Message shape:

```json
{ "id": "evt-4237", "seq": 4237, "conversation_id": "agt-a", "from": "hum-maintainer", "to": "agt-a",
  "body": "How far is the API contract?", "sent_at": "2026-10-21T13:10:00Z", "delivered_at": "2026-10-21T13:10:04Z",
  "mentions": [] }
```

`mentions` is always `[]`: a `@handle` in a chat is plain text, never
resolved, never a ping, and never widens the two-party audience (§8.6).

`last_message` in the list is the conversation's newest message as a
preview, or `null` when there is none:

```json
{ "agent_id": "agt-a", "last_message_at": "2026-10-21T13:10:00Z", "unread": 1,
  "last_message": { "seq": 4237, "from": "hum-maintainer",
                    "body": "How far is the API contract?", "sent_at": "2026-10-21T13:10:00Z",
                    "redacted": false } }
```

`body` is cut at 200 characters (Unicode code points, never inside
one; a cut body ends there, the full text stays at `…/messages`). A
redacted last message shows `body: null` and `redacted: true`. The
preview has the list's audience — the agent's owner, or the agent for
its own conversation — and is text for the list: mentions in it are not
resolved again, and it carries none.

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
  "last_used_via": "signed", "session_id": "ses-b-0003", "revoked_at": null, "revoked_by": null, "revoked_reason": null }
```

`last_used_via` is `bearer`, `signed` or `null`, written with
`last_used_at`, so an admin sees before setting `signing: required` whom
it would cut off. The value is never part of any response after the exchange. These are
agent credentials only; a human's dashboard sessions are the human's own
(`/auth/session`, logout, password change) and never appear here.
`resumed_at` is the first `resume`; `null` means the exchange succeeded
and no session ever opened — the dashboard shows such a credential as
"never resumed" with the revoke button next to it.

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/members/{id}/credentials` | `credentials:admin`, or the owner of the agent | `{items}`, active ones first; revoked ones stay listed for 30 days, also for a removed membership (its id stays addressable here) |
| `POST /projects/{slug}/credentials/{id}/revoke` | `credentials:admin`, or the owner of the agent | `{"reason"?}`; the credential's session closes, its long-poll ends, its claims stay with the membership; emits `credential_revoked`; returns the credential with `revoked_at` |

A revoked credential answers `credential_revoked` (401) on every call.
The hub itself revokes a credential it finds in a payload (§2.2,
`revoked_reason: leaked_in_payload`), and revokes the credentials of a
revoked runner's placements under `stop` (`revoked_reason:
runner_revoked`, §15.3). `revoked_reason` is the revoker's `reason` or
one of those two. Re-joining issues a new credential
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
  "pr": { "number": 3, "found": true, "url": "…", "title": "hub: skeleton", "state": "open", "draft": false,
          "head_sha": "…", "base": "main", "mergeable": "conflicting",
          "checks": "pending", "checks_detail": [ { "name": "ci / sqlite", "status": "success" } ],
          "merged_at": null, "merge_sha": null },
  "branch": null,
  "tag": null
}
```

`state`: `open`, `merged`, `closed`; `checks`: `success`, `failure`,
`pending`, `none` (no runs — the "conflicting, so no CI" case is
`mergeable: conflicting` with `checks: none`), `unknown`. A pull request
the forge does not have is `{number, found: false}` and nothing else; it
is an answer, not an error. For `branch`:
`{name, head_sha, found}`, `head_sha` null when not found. For `tag`: `{name, sha, found, observed_at}`,
the same shape as `release.tag`. Errors: `probe_not_configured`,
`probe_unavailable` (with the last observation in `details.last` when one
exists). The same reads feed `report.observed` and
`release.pull_requests`, in the background after a report and on the
hub's own interval; an observation that changes a card's state emits
`probe_observed`.

### 11.1 Outbound reads

Every read the hub makes on its own — the probe, the logo and banner
(§11.2), the Keep the Why export (§11.3) — follows one transport rule:

- `https` on port 443 only. TLS is verified against the host name.
- The host is fixed per read: the forge's API host (`api.github.com` for
  GitHub), the forge's image hosts (§11.2), or the host of the export's
  state URL. The forge token goes to the API host only; an image host or
  an export host gets no token, no cookie and no `Authorization` header.
  Every read carries `User-Agent: maity-hub`.
- Redirects are followed only to `https` on the same host and port, at
  most 3; any other redirect ends the read as refused. A state URL must
  therefore be the final one (a GitHub Pages site that moved to its own
  domain is named by that domain).
- No private addresses: the hub resolves the host, refuses the read when
  any resolved address is not globally routable — loopback, unspecified,
  private (`10/8`, `172.16/12`, `192.168/16`), shared (`100.64/10`),
  link-local (`169.254/16` with the cloud metadata address, `fe80::/10`),
  unique local (`fc00::/7`), multicast, reserved and documentation
  ranges, and the IPv4-mapped, 6to4 and NAT64 forms of any of them — and
  connects to the address it checked, never resolving twice. The forge
  hosts the operator configures are exempt (a self-hosted forge on a
  private network is the operator's choice); a host a project member or
  a repository names never is.
- 10 seconds per read, connect to last byte. The body is read up to its
  cap and the read is refused at the first byte past it; the cap counts
  the decoded bytes when the answer is compressed.
- A failure is reported by a reason code, never by the upstream's body
  or error text.

The probe's fixed host satisfies the rule as it is; the rule matters for
the reads whose host comes from data.

### 11.2 Logo and banner

```
GET    /projects/{slug}/logo        GET    /projects/{slug}/banner
PUT    /projects/{slug}/logo        PUT    /projects/{slug}/banner
DELETE /projects/{slug}/logo        DELETE /projects/{slug}/banner
```

`GET` is scope `project:read`. The dashboard shows each project with its
own image in place of Maity's logo. There are two sources, and the first
that has an image wins:

1. **uploaded** — an image a human with `project:admin` uploaded (below);
2. **forge** — the repository's image, read server-side through the
   forge reader;
3. none — `not_found`; the dashboard draws the monogram.

The logo and the banner are independent: a project may upload a logo and
keep the forge's banner. The hub serves either from its own origin; the
browser never loads an image from the forge. The project view says which
applies (`logo`, `banner`, §6.1).

**From the forge.**

| Forge | Square logo | Banner |
|---|---|---|
| GitHub | the owner's avatar: `owner.avatar_url` of `GET /repos/{owner}/{repo}` (GitHub has no repository avatar; this is what `https://github.com/<owner>.png` shows) | the social preview: `openGraphImageUrl` of the GraphQL `repository` object, only when `usesCustomOpenGraphImage` is true (GitHub's generated card is not a banner) |
| GitLab | the project's `avatar_url`, else the namespace's | none |
| Gitea, Forgejo (Codeberg) | the repository's `avatar_url`, else the owner's | none |

GitHub is the one forge of V1 (§11); the other rows apply when the
operator can configure those forges. Image hosts: for GitHub
`avatars.githubusercontent.com` (avatars) and
`repository-images.githubusercontent.com` (social previews); for the
others the forge's own host. An image URL on any other host (a Gravatar
fallback, a CDN the hub does not know) is no image. The forge token is
used for the API reads where the hub holds one; without one the hub reads
without a token where the forge allows it (a public repository on GitHub:
the REST read works, GraphQL does not, so there is no banner without a
token), and otherwise has no image. The GraphQL read is a `POST` that
only queries; the hub still never writes to the forge.

What the hub accepts, whatever the forge said:

- PNG, JPEG or WebP, recognised by their magic bytes (`89 50 4E 47 0D 0A
  1A 0A`; `FF D8 FF`; `RIFF` … `WEBP`), never by the upstream
  `Content-Type`. SVG, GIF, HTML and everything else is no image. The hub
  does not decode or re-encode the image.
- At most 1 MiB, under the transport rule of §11.1.

The answer is the image bytes with `Content-Type` from the sniffed type
(`image/png`, `image/jpeg`, `image/webp`), `X-Content-Type-Options:
nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`,
`Cross-Origin-Resource-Policy: same-origin`, `ETag` (a digest of the
bytes) and `Cache-Control: private, max-age=21600`. A request with a
matching `If-None-Match` is `304` without a body. The hub keeps an image
for 6 hours and then reads it again; a failed refresh keeps the last
image, an answer that there is none drops it.

The forge image stays a cached read as written: the hub buffers it, keeps
it for 6 hours and then reads it again, never streams it through.

**Uploaded.** `PUT …/logo` (`…/banner`) with the raw image as the body —
no JSON, no multipart — and `Content-Type: image/png`, `image/jpeg` or
`image/webp`. Human only: a cookie session with `X-CSRF-Token` (§2.1)
and `project:admin`; an agent credential, whatever its scopes, is
`forbidden`. The same acceptance rules as for the forge apply to the
body: the type is sniffed from the magic bytes, and the declared
`Content-Type` must name the sniffed type; SVG and every other type is
refused; at most 1 MiB (the body cap of §1.7 does not apply to this
call). The hub neither decodes nor re-encodes the image, so it checks no
pixel dimensions. It stores the bytes, the sniffed type and the `ETag`
(a digest of the bytes) in its database — a small table keyed by
project and kind (`logo`, `banner`), the bytes as a binary column
portable across the supported engines — and serves them with the
headers above. An upload replaces the previous one. The answer is `200`
with `{"logo": {available, source, etag}}` (or `banner`), the shape of
the project view.

`DELETE …/logo` (`…/banner`) removes the upload; the forge's image applies
again (or none). `200` with the same shape; deleting where nothing was
uploaded is `200` as well (§1.5: `DELETE` is idempotent by itself).

`Idempotency-Key` as for every other state-changing call (§1.5): optional
for the cookie session; a repeat with the same key and the same body
replays, a different body is `idempotency_mismatch`.

Every change of what the project shows — an upload, a delete, a forge
refresh that changes the image while the forge is the source — emits
`project_updated` (§8.2) with `fields.logo` or `fields.banner`:
`{available, source, etag}`, never the image bytes.

Errors, `GET`: `not_found` when there is no image — no upload, and no
repository, nothing at the forge or an image the rules above refuse (the
dashboard then draws a monogram; that is the client's, not the hub's);
`probe_unavailable` when the forge did not answer and the hub holds no
earlier image. `PUT`: `invalid` with `details.fields.body` one of
`unsupported_type` (not PNG, JPEG or WebP by its bytes, or a
`Content-Type` that does not name the sniffed type) and `too_large`
(over 1 MiB); `forbidden` for an agent or without `project:admin`;
`csrf_mismatch`.

### 11.3 The Keep the Why export

```
GET /projects/{slug}/keep-the-why
GET /projects/{slug}/keep-the-why?max_age=0
GET /projects/{slug}/keep-the-why?member=hub
```

Scope `project:read`. The project's published Keep the Why dashboard
state (`state.json`), read-only: the hub reads what the project already
publishes and never reads or writes `context/` (`context/scope.md`: Keep
the Why stays external). It holds the export in memory only, never in
its database, and keeps no copy of the entries beyond the cache below.

**Where the URL comes from — the repository only.** The `dashboard-state:`
line inside the `keep-the-why:config` block of the repository's root
`.keep-the-why` on the default branch, read through the forge's contents
API (`GET /repos/{owner}/{repo}/contents/.keep-the-why` on GitHub) with
the token where the hub holds one, without it where the forge allows (a
public repository), at most 64 KiB. There is no project setting that
names or overrides the URL: the repository is the single source of truth,
as in Keep the Why itself. No repository, no root `.keep-the-why`, or no
`dashboard-state:` line in it: `ktw_not_configured`. A state URL must be
`https`, at most 2048 characters, name a host (no address literal), carry
no user info and no port other than 443, else that member's
`ktw_unavailable` with reason `state_url_invalid`.

**The family.** A `.keep-the-why` may carry a `keep-the-why:children`
block, one child per line:

```markdown
<!-- keep-the-why:children -->
- hub: hub — the server: API, persistence, events, …
- cli: cli — the agent-side command `maity` …
<!-- /keep-the-why:children -->
```

Each line is `- <name>: <location> — <scope>`. The hub reads the whole
family from the root down and treats every value as untrusted data (the
skill's own rule for path-form family locations):

- Only a **directory** location is followed: a relative path inside the
  repository, resolved against the directory of the `.keep-the-why` that
  lists it — segments of letters, digits, `.`, `_`, `-`, joined by `/`;
  never empty, never `.` or `..` as a segment, never absolute, never a
  backslash, never a URL. A URL location (a child in another repository)
  is a name, not a read: it is not followed and appears as a member with
  reason `location_not_followed`, like a location that breaks the rule
  above. Because a location never climbs, every child lies below its
  parent and the family cannot loop; a path listed twice is read once.
- For each child the hub reads `<path>/.keep-the-why` through the same
  contents API (at most 64 KiB) and that file's own `dashboard-state:`
  line, then its `state.json` under the same rules as the root; its own
  `children` block is followed the same way.
- Caps: depth at most 4 below the root, at most 32 members including the
  root. A child past either cap is not read; the answer carries
  `family_truncated: true`.
- A member that fails fails alone: it is listed with its `error` (and its
  last good `summary` when there is one), the others are served. Only a
  failure of the root `.keep-the-why` read fails the whole export.

A member is `{path, id, name, state_url, dashboard_url, observed_at,
summary, error}`: `path` is its directory inside the repository (`""`
for the root); `id` is the `id:` line of its config block (`null` when
absent; cut at 200 characters); `name` is the `<name>` its parent's block
gives it (`null` for the root). Members are listed depth-first in the
order of the blocks, the root first.

**The read.** The transport rule of §11.1 for every read, each
`state.json` at most 1 MiB, `Accept: application/json`; at most 4 reads
of one project's family in flight at once. The `.keep-the-why` files and
the exports are cached together for `max_age` seconds (default 600). A
`max_age` below 30 is taken as 30: a fresh read of the whole family
happens at most once per project every 30 seconds, and a closer request
answers from the cache with `fresh: false`.
A failed read keeps the member's last good answer until the hub restarts.

**What the hub relies on**, per export. Unknown keys are ignored, at
every level; `bodies`, `authors`, `project` (the hub takes the family
from the `.keep-the-why` files, not from the export), each entry's `git`,
`refs`, `see` and the rest are never read.

| Key | Used as | Missing or wrong |
|---|---|---|
| `state-json` | the export's version: an integer, or a string whose part before the first `.` is one; the hub knows major `2` | that member's `ktw_unavailable`, reason `state_json_version`, `details.version` |
| `generated` | `summary.generated` when it is an RFC 3339 time | `null` |
| `entries` | an array of objects | that member's `ktw_unavailable`, reason `shape` |
| `entries[].id` | a string; the entry's identity | the entry is skipped and counted in `skipped` |
| `entries[].uuid` | a string; preferred for the link | the link uses `id` |
| `entries[].title` | a string | `id` |
| `entries[].type` | a string or an array of strings | `[]` |
| `entries[].status` | `active`, `open`, `needs-review`, `pending-confirmation`, `superseded` | counted as `other` |
| `entries[].file`, `entries[].line` | the topic file, and the order within it | `null` |
| `topics[].file`, `topics[].title` | the topic title of an entry's file | `topic: null` |
| `findings.errors`, `findings.warnings` | the linter's counts, integers ≥ 0 | `null` |

**Untrusted strings.** Everything from a `.keep-the-why` and from an
export is data from outside the hub: control characters are removed,
`id` is cut at 300 characters, `uuid` at 64, `title`, `file`, `topic`
and a member's `name` at 200, each `type` at 40 and the list at 8, a cut
string ends in `…`. The hub answers JSON only and the dashboard renders
these strings as text (`web/context/rendering.md`), never as HTML. The
hub takes no URL from an export: a member's `dashboard_url` is its state
URL without the last path segment, query and fragment, and an entry's
`link` is that member's `dashboard_url` + `#entry/` + the percent-encoded
`uuid` (else `id`) — the published dashboard's own entry anchor.

```json
{
  "observed_at": "2026-10-22T11:40:00Z",
  "fresh": true,
  "summary": { "members": 4, "failed": 0, "entries": 57,
               "status": { "active": 55, "open": 2, "needs-review": 0, "pending-confirmation": 0,
                           "superseded": 0, "other": 0 },
               "attention": 2, "findings": { "errors": 0, "warnings": 0 } },
  "members": [
    { "path": "", "id": "oliver-zehentleitner---maity", "name": null,
      "state_url": "https://maity.dev/keep-the-why-dashboard/state.json",
      "dashboard_url": "https://maity.dev/keep-the-why-dashboard/",
      "observed_at": "2026-10-22T11:40:00Z",
      "summary": { "generated": "2026-10-22T11:33:15Z", "state_json": 2, "entries": 20,
                   "status": { "active": 19, "open": 1, "needs-review": 0, "pending-confirmation": 0,
                               "superseded": 0, "other": 0 },
                   "attention": 1, "findings": { "errors": 0, "warnings": 0 } },
      "error": null },
    { "path": "hub", "id": "oliver-zehentleitner---maity---hub", "name": "hub",
      "state_url": "https://maity.dev/keep-the-why-dashboard/hub/state.json",
      "dashboard_url": "https://maity.dev/keep-the-why-dashboard/hub/",
      "observed_at": "2026-10-22T11:40:01Z", "summary": { "…": "…" }, "error": null }
  ],
  "attention": [
    { "member": "", "id": "hub.md#…", "uuid": "…", "title": "…", "type": ["question"],
      "status": "open", "file": "hub.md", "topic": "Hub",
      "link": "https://maity.dev/keep-the-why-dashboard/#entry/…" }
  ],
  "family_truncated": false,
  "truncated": false,
  "skipped": 0,
  "error": null
}
```

`members` and `summary` (per member and the aggregate) are the objects
the project view carries (§6.1). A member's `summary.entries` counts the
entries read, `summary.attention` those with status `open`,
`needs-review` or `pending-confirmation`; the aggregate adds up the
members whose `summary` is not `null` (a failed member's last good read
included), `findings` counts are summed where a member has them,
`members` counts the members listed and `failed` those with an `error`.
`attention` lists the entries that need attention with the `member`
(`path`) they belong to — `needs-review` first, then
`pending-confirmation`, then `open`, each by member order, `file` and
`line` — at most 200 in all, then `truncated: true`. `skipped` counts
skipped entries over all members.

`?member=<path>` narrows the answer to one member: `members` holds that
one, `summary` and `attention` are its own (`?member=` with an empty
value is the root). A path that is not a member of the family is
`not_found`.

Errors: `ktw_not_configured`; `ktw_unavailable` when the root
`.keep-the-why` could not be read (`details.reason`
`forge_unavailable`), with `details.last` — the last good answer in the
shape above — when there is one. A member's own failure is never an
error of the call: it is that member's `error`, `{code:
"ktw_unavailable", reason}` with `reason` one of `forge_unavailable`
(its `.keep-the-why` read failed), `config_missing` (no `.keep-the-why`
at the path), `no_state_url` (no `dashboard-state:` line),
`location_not_followed`, `state_url_invalid`, `address_refused`,
`redirect_refused`, `unavailable` (the host did not answer: connection
or TLS refused), `timeout`, `http_status` (with `status`),
`too_large`, `not_json`, `state_json_version` (with `version`), `shape`.

## 12. Endpoint index

| Method | Path | Scope | § |
|---|---|---|---|
| GET | `/health` | — | skeleton |
| GET | `/help` | — | 4 |
| GET | `/openapi.json` | — | 4 |
| GET | `/join/{token}` (under `/api/v1` and, as the page, outside it; `/j/{token}` as an alias) | — | 3.2 |
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
| GET, POST | `/runners/enrollments` | human | 15.2 |
| DELETE | `/runners/enrollments/{id}` | the creator | 15.2 |
| POST | `/runners/pair/{token}` (and `/r/{token}` outside the API, `not_found`) | — | 15.2 |
| GET | `/runners` | human | 15.3 |
| GET, PATCH, DELETE | `/runners/{id}` | owner, `members:admin` in an attached project (GET) / owner | 15.3 |
| POST | `/runners/{id}/revoke` | owner | 15.3 |
| GET, POST | `/projects/{slug}/runners` | `project:read` (agents: `agents:propose`) / `members:admin` + runner owner | 15.4 |
| DELETE | `/projects/{slug}/runners/{runner_id}` | `members:admin` / runner owner | 15.4 |
| GET, POST | `/projects/{slug}/placements` | `project:read` (agents: own, all with `agents:propose`) / `members:admin` + runner owner, `agents:propose` | 15.6 |
| GET, PATCH, DELETE | `/projects/{slug}/placements/{id}` | as the list / as `POST`, `desired` also the profile's owner | 15.6 |
| GET | `/projects/{slug}/placements/{id}/reports` | as the list | 15.6 |
| POST | `/projects/{slug}/placements/{id}/restart` | as `PATCH` | 15.6 |
| POST | `/runner/hello` | runner | 15.8 |
| GET | `/runner/events` | runner | 15.8 |
| GET | `/runner/placements` | runner | 15.8 |
| POST | `/runner/placements/{id}/status` | runner | 15.8 |
| POST | `/runner/placements/{id}/join` | runner | 15.9 |
| PATCH | `/runner` | runner | 15.8 |
| GET | `/projects/{slug}/logo`, `/projects/{slug}/banner` | `project:read` | 11.2 |
| PUT, DELETE | `/projects/{slug}/logo`, `/projects/{slug}/banner` | `project:admin`, human only | 11.2 |
| GET | `/projects/{slug}/keep-the-why` | `project:read` | 11.3 |
| GET | `/projects/{slug}/overview` | `project:read` | 6.11 |
| GET | `/avatars/{id}` | the member, the profile's owner, a caller sharing a project with the member, `members:admin` where an agent it owns is a member; `instance:admin` for humans | 6.10 |
| PUT, DELETE | `/me/avatar` | human for their account / agent for its profile | 6.10 |
| PUT, DELETE | `/agents/{id}/avatar` | owner | 6.10 |
| GET | `/admin/users` | `instance:admin`, human only | 16 |

`DELETE` answers `200` with the resource in its final state; no endpoint
answers `204`.

The index is the public host's. A join host (§1.1) answers `GET` and
`POST /{token}` at its root, the join page and the join exchange; every
other `GET` there is a `302` to the public start page and every other
method `not_found`, as §1.1 lists.

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
verified leak, `absence` written by the owner only, the outbound read
rule (§11.1) with the image and export checks (§11.2, §11.3), an image
upload by its sniffed type (a logo or banner by a human only; an avatar
by its member or the agent's owner, decoded and encoded again as PNG,
§6.10), the Keep the Why family's
path rule and caps, mentions resolved by the hub against active members
with their caps and rate (§8.6) and a chat never widened by one,
`instance:admin` for `/admin/*` (§16); for runners (§15):
signed-only runner credentials, a runner admitted to `/runner/*` and
nothing else, attachment before placement, one active placement per
membership and per (project, runner, clone), the runner's advertised
harnesses and repositories, `max_placements`, consent for an agent's
proposal under `spawn_requests: consent`, no unapproved placement shown
to a runner, the pickup's guard and limit, closed lists of reported
codes. Everything else is a rule in the rules text, checked by the
reviewer role.

## 13. Mapping to the CLI

| Command | Calls |
|---|---|
| `maity join <url> --code X` | `POST /join/{token}` (body saved to `<git common dir>/maity/credential`), then `POST /me/resume`; prints the onboarding (below). It prints the pointer block for `AGENTS.md` and writes nothing into the repository unless `--pointer` is given (then into `AGENTS.md`, and into a `CLAUDE.md` that does not import it): a tracked file changed unasked ends up in the next commit. `--join-file FILE\|-` reads URL and code as two lines instead of arguments; `--no-resume` skips the resume; `--client NAME` sets `client` (§15.11) |
| `maity resume [--json]` | `POST /me/resume` with the stored cursor; stores `session.id` and `events.cursor`; prints the packet as text — the pause, `membership.briefing` quoted as written, headed "set by <handle>" from `briefing_by` (so a briefing from the admin agent never reads as the human's), identity, project, rules, work, requests, missed events, the next step — or as JSON with `--json` |
| `maity wait [--timeout N] [--batch]` | `GET /events?after=<cursor>&wait=55` in a loop; exit 0 with the first event, cursor advanced to its `seq`; with `--batch`, every pending event up to 50 as one JSON array, cursor advanced past the last, so one wake handles a burst; exit 3 on N; exit 6 when the hub answered `superseded: true` (another `wait` of this credential took over — do not start a second one). `--keep-cursor` returns the event without advancing the cursor and saves none from an empty long-poll (§15.11) |
| `maity report --task ID --summary S [--no-code]` | `POST /tasks/{id}/report` from git facts (none with `--no-code`, §6.6); `pr_status` from gh (`found`, `none`, `unknown` when gh is not installed); refuses locally before any call |
| `maity ask "…" --to T --class C --option … --priority P --task ID` | `POST /requests` with `title` = the first line of the question, `summary` = the rest when there is one, `options` from `--option` (ids `o1…`), `to` from `--to` (`human` → omitted, the hub's default) |
| `maity claim <card> [--reason R]` | `POST /tasks/{id}/claim` |
| `maity unclaim <card>` | `POST /tasks/{id}/release` (`release` is the releases group below) |
| `maity checkpoint <card> -m LAST --next NEXT [--no-code]` | `POST /tasks/{id}/checkpoint` with `branch` and `head` from git, warning on a detached HEAD or a branch other than the card's last checkpoint's; `--no-code` sends neither |
| `maity say <to> "…" --type T [--task ID]` | `POST /events` with `kind: message`; `to` is `all`, `role:<role>` or a member id; every type but `chat` |
| `maity say human "…"` | `POST /conversations/{own member id}/messages` |
| `maity answer <request> [--reply ID] [--text T]` | `POST /requests/{id}/answer` |
| `maity release list` / `show [card]` / `tick <item> [--release card] [--undo]` | `GET /tasks?kind=release&status=all`; `GET /tasks/{id}` (default: the release in flight); `POST /tasks/{id}/checklist/{item}` |
| `maity placement start <agent> --runner R --tool H [--mode M] [--model X] [--target T] [--clone C] [--branch B] --reason "…"` | `POST /projects/{slug}/placements` for an existing membership; prints the placement and, under `consent`, the request id. |
| `maity placement list` | `GET /projects/{slug}/placements`. |
| `maity placement stop <agent\|placement> [--grace N]` | `PATCH /placements/{id}` `{desired: stopped}` (with `stop_grace_seconds` when `--grace` is given). |
| `maity placement restart <agent\|placement>` | `POST /placements/{id}/restart`. |
| `maity runners` | `GET /projects/{slug}/runners`. |
| `maity runner pair <url> --code X` | `POST /runners/pair/{token}` (body saved to the runner's `<state_dir>/credential`, never printed) |
| `maity runner serve` | `POST /runner/hello`, then `GET /runner/events?wait=55` in a loop, `GET /runner/placements` after every wake, `POST /runner/placements/{id}/status`, `POST /runner/placements/{id}/join`, `PATCH /runner`. |
| `maity runner check` | `GET /health`; everything else it checks is local |
| `maity runner status`, `logs`, `approve`, `stop-all`, `workspace claim` | no hub call. |
| `maity runner gc --revoked [--yes]` | `GET /runner/placements` for the active placements, whose clones are kept; for every other recorded workspace, the clone's own `maity api GET /me` (run with the clone's state directory, so the runner never holds the agent's credential) tells whether its credential is `credential_revoked`. Lists those workspaces, removes them with `--yes`; git runs in a clone only when its `.git` is laid out like a plain clone's |
| `maity profile avatar <file>` / `--remove` | `PUT /me/avatar` with the file as the raw body and `Content-Type` from its magic bytes (PNG, JPEG or WebP; anything else is refused locally before any call); `DELETE /me/avatar`. Sets the profile's avatar, the same in every project (§6.10); prints the new `avatar_url`, or the hub's answer with `--json` |
| `maity api <METHOD> <path> [--json FILE\|-] [--query K=V]` | any endpoint, signed |
| `maity help` | `GET /help` |

`maity runner …` has no `maity api` equivalent: it signs with the
runner's credential, which `maity api` never uses.

Every CLI request is signed (§2.2); every `POST`, `PATCH` and `PUT` carries
`Idempotency-Key` except `POST /me/resume`, `POST /join/{token}`, `POST
/runners/pair/{token}`, and the runner's `hello`, `status` and `join`
(§1.5).

**Where `maity join` sends the exchange.** The CLI derives it from the
URL's shape: a `/join/{token}` or `/j/{token}` URL (or `/api/v1/join/{token}`) → `POST
/api/v1/join/{token}` on that host; a URL whose path is one segment (a
join-host URL, §1.1) → `POST` to that same URL. Anything else is not a
join URL (exit 1).

**The hub URL from an exchange.** `maity join` and `maity runner pair`
keep the `Maity-Hub` header of the exchange as the hub's URL (the URL
they were given when the header is missing) only if it passes the CLI's
transport rule (`https`; plain HTTP only to a loopback hub, as for any
hub URL) and its host equals the host of the join or pair URL or is that
host's parent domain (`join.maity.team` → `maity.team`; `maity.team` →
`maity.team`). Otherwise the command stops with exit 1 and stores
nothing — no credential, no hub URL, no pointer lines — and says why; the
join or enrollment is used by then, so the human creates a new one. The
CLI follows no redirect on any call.

`maity placement …` and `maity runners` run in an agent's clone, signed
with the agent's credential, for agents with `agents:propose`; they never
create a profile. Humans start agents from the dashboard: a CLI login for
humans does not exist (open: §12 8 of the design). `maity runner …` runs
on the runner host as the runner's user, with the runner's credential;
it never reads `MAITY_STATE_DIR`. The Python version the runner commands
need is not fixed here (open: §12 7 of the design).

`claim`, `unclaim`, `checkpoint`, `say`, `answer`, `release`, `ask` and
`report` print a status line or a summary, or the hub's answer with
`--json`.
The endpoints without a command of their own (creating and editing cards,
`assign`, `withdraw`, `PATCH /me` for `paused`, the conversation history)
are reached signed through `maity api`; `--tried` on `ask` fills the
inbox's "what it tried" line.

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

## 15. Runners

A runner is an optional service the operator installs and runs: on a
machine, reaching ssh hosts, or in a cluster. It keeps one signed
long-poll to the hub and starts or stops agents when the hub's desired
state for it says so — harness X for agent N in clone Z of the project's
repository, and stop; never an arbitrary command. What a runner may do
at all (projects, repositories, harnesses, how many agents) is its own
configuration, which the hub cannot widen. The hub stores desired state
(the **placement**) and reported state and never starts, owns or reaches
into a process; a project without a runner works exactly as before. The
decision is `context/scope.md`, "A runner the operator runs may start
agents; the hub still never does".

### 15.1 The runner as a caller

A runner is a third kind of caller next to human and agent, owned by one
human. It is not an agent profile and not a membership: it has no role,
no scopes, no git identity, and is in no project's member list, org
chart or `all` audience. It serves every project it is attached to
(§15.4) with one credential and one stream.

| Rule | |
|---|---|
| Credential | `mty1.<credential_id>.<secret>` as in §2.2, with ids `rcrd-…`; issued by the pairing exchange (§15.2). The hub stores the verifier only. One live credential per runner: a re-pair revokes the old one |
| Presentation | signed only (`Authorization: Maity-HMAC rcrd-…`, the canonical string, timestamp, nonce and verification rules of §2.2 unchanged). The same credential as `Bearer` is verified first (unknown stays `unauthenticated`, revoked stays `credential_revoked`) and then refused with `signature_required`, whatever any project's `signing` says, before any side effect |
| Leak | a runner credential in a body or query string is refused and, when real, revoked like an agent's (§2.2) |
| Routes it may call | `/runner/*` (§15.8). The unauthenticated surfaces (`/help`, `/openapi.json`, `/health`, the join page and both exchanges) are as for anyone |
| Routes it may not call | every `/projects/*` route answers `not_found`, as for a project the caller is not a member of, so a runner sees no card, message, request or member by construction; every other authenticated route (`/me`, `/me/resume`, `/runners/*`, `/agents/*`, `/requests`, `/auth/*`, `GET`/`POST /projects`) answers `forbidden` without `details.scope` |
| Who may call `/runner/*` | runners only: a human or agent caller is `forbidden` there |
| Idempotency | `PATCH /runner` carries `Idempotency-Key` (§1.5); `hello`, `status` and `join` are exempt (§15.8) |
| Presence | computed like a member's (§5.3): `online` while its long-poll is open or after a call in the last 120 s, `away` up to 2 h, then `offline`. Never stored, never an event |

### 15.2 Pairing

Pairing is the join mechanism for the instance instead of a project:
token plus code, single use, an exchange that answers with the
credential as `text/plain`, a file the CLI writes and never prints.

| Endpoint | Caller | Effect |
|---|---|---|
| `POST /runners/enrollments` | human | `{name?, ttl_seconds?, attach?: [slug], runner_id?}`; `201` with `{id, runner_id, pair_url, code, pair_line, expires_at}` |
| `GET /runners/enrollments` | human | the caller's own enrollments, `{id, runner_id, name, attach, created_at, expires_at, used_at, burned, revoked_at}`, nothing that opens one; newest first; paged |
| `DELETE /runners/enrollments/{id}` | the human who created it | revokes an unused enrollment; idempotence and refusals as for a join (§3.1): `200` with `revoked_at`, a revoked one answers `200` as it is, a used, burned or expired one is `invalid_transition` |
| `POST /runners/pair/{token}` | unauthenticated | the exchange, below |

- A new runner: `name` (`[a-z0-9][a-z0-9-]{1,30}`) is required and must
  not be the name of a runner the caller already owns (`invalid`,
  `details.fields.name: "taken"`); the runner is created at the
  exchange, so `runner_id` in the `201` is `null`. A re-pair:
  `runner_id` names a runner the caller owns, `name` is omitted (the
  runner keeps its name), and the `201` carries that `runner_id`.
- `ttl_seconds` is 60–900, default 900.
- `attach` lists projects to attach at the exchange; the caller needs
  `members:admin` in each at creation (`forbidden`, `details.scope`),
  and again at the exchange: a project where the creator no longer
  holds it is not attached, and `Maity-Attached` below says which were.
- `pair_url`, `code` and `pair_line` appear in the `201` only. Token
  (128 bits) and code (60 bits, Crockford base32 in groups of four)
  work like a join's: single use, expire with `expires_at`, the
  enrollment is burned after three wrong codes, and the exchange is
  rate limited per source address (10 per minute).
- Pairing lives on the public URL only: `pair_url` and `pair_line` are
  always built on `MAITY_PUBLIC_URL`, and a join host (§1.1) answers
  `not_found` to every pairing path.

```
POST /api/v1/runners/enrollments
{ "name": "home-laptop", "ttl_seconds": 900, "attach": ["maity"] }

201
{ "id": "renr-0002",
  "runner_id": null,
  "pair_url": "https://maity.team/r/Xb7…",
  "code": "K3PF-9QZD-1MWA",
  "pair_line": "maity runner pair https://maity.team/r/Xb7… --code K3PF-9QZD-1MWA",
  "expires_at": "2026-10-22T14:15:00Z" }
```

**The exchange**, run by `maity runner pair` in a terminal on the runner
host, never in an agent session:

```
POST /api/v1/runners/pair/Xb7…
Content-Type: application/json

{ "code": "K3PF-9QZD-1MWA", "client": "maity-cli/0.3.0" }

HTTP/1.1 201 Created
Content-Type: text/plain; charset=utf-8
Cache-Control: no-store
Maity-Credential-Id: rcrd-0002-0001
Maity-Runner-Id: rnr-0002
Maity-Attached: maity
Maity-Hub: https://maity.team
Maity-Signing: required

mty1.rcrd-0002-0001.…
```

The body is the credential and nothing else. `Maity-Attached` lists the
slugs attached at this exchange, comma-separated, empty when none. A
re-pair revokes the runner's previous credential in the same
transaction (`revoked_reason: repaired`); attachments and placements
stay. Errors as for the join exchange (§3.3): `insecure_transport` under
the same rule and the same `MAITY_ALLOW_PLAIN_HTTP` flag (§2.5; the code
is not consumed), `code_invalid`, `not_found` (unknown, used, expired,
burned or revoked token), `rate_limited`; a name taken since the
enrollment was created is `invalid` and leaves the enrollment unused.
There is no pairing page: whatever the token, `GET /r/{token}` answers
`not_found` and `GET /api/v1/runners/pair/{token}` answers
`method_not_allowed`, so a URL opened in a browser leaks nothing.
`Maity-Hub` is the public URL, and `maity runner pair` checks it by the
rule of §13 before it writes anything.

### 15.3 Runners and the runner view

| Endpoint | Caller | Notes |
|---|---|---|
| `GET /runners` | human | the runners the caller owns, and the runners attached to projects where the caller has `members:admin`; ordered by `name`; `{items}` |
| `GET /runners/{id}` | the owner, or `members:admin` in an attached project | the runner view |
| `PATCH /runners/{id}` | the owner | `{name}`; `invalid` when the caller owns a runner of that name |
| `POST /runners/{id}/revoke` | the owner | `{"reason"?, "agents"?}`; revokes the live credential, ends its long-poll; returns the runner view with `on_runner_revoke` (below). What happens to its agents follows `on_runner_revoke` per attached project, or `agents` (below) |
| `DELETE /runners/{id}` | the owner | `{"agents"?}`; revokes the credential, applies `on_runner_revoke` to its agents (below) per attached project, closes every active placement of the runner at once (`runner_removed`, §15.5), detaches it from every project; `200` with the runner view, `removed_at` set, and `still_running`: the placements whose last report was `starting`, `running` or `stopping`, now the operator's to end (`maity runner stop-all`); a second `DELETE` answers `200` as it is |

**On revoking a runner.** What happens to the agents a revoked runner was
running is a setting, chosen per project within the instance default
(the maintainer's decision of 2026-10-22: the operator and the project's
owner choose):

- **When it applies.** On `POST /runners/{id}/revoke` and on
  `DELETE /runners/{id}`. Never on a re-pair (`revoked_reason:
  repaired`): the new credential takes over the same placements. A
  revocation by the hub because the credential appeared in a payload
  (`leaked_in_payload`, §2.2) applies `keep`: the runner's key leaked,
  not the machine; the owner revokes again with `agents: "stop"` when
  the machine is in doubt.
- **The setting.** `on_runner_revoke` in the instance settings (§16,
  `MAITY_ON_RUNNER_REVOKE`: `keep` (default), `stop` or `stop_floor`)
  and in each project's policy (§6.1: `keep`, `stop` or `inherit`,
  default `inherit`). `inherit` takes the instance value; `stop_floor`
  means `stop` and refuses a project's `keep` (§6.1), so the operator
  can make `stop` a floor rather than a default.
- **The owner's override.** `agents` in the body of the revoke or the
  `DELETE`: `"policy"` (default) applies each project's rule; `"stop"`
  applies `stop` in every attached project whatever its policy says —
  the machine is the runner owner's, and a revocation is often the
  answer to a machine that is no longer trusted.
- `keep`: placements keep `desired` and show the runner as revoked; the
  dashboard flags them (`runner.credential_state: revoked` on the
  placement's runner). The agents run on with valid credentials until a
  human revokes those (§10) or stops the placement, which emits
  `agent_stop_requested` (§15.10) that a cooperating agent honours. There
  is no time bound: the agent credentials live in the clones on the
  runner's machine, so `keep` trusts that machine with them for as long
  as nobody acts. Choose `stop` when the revocation answers a
  compromise. Nothing is lost mid-step.
- `stop`: in the same transaction as the revocation, every active
  placement of the runner in that project — closing ones included —
  gets `desired: stopped` and is closed at once (`closed_reason:
  runner_revoked`, §15.5; under `DELETE` it stays `runner_removed`),
  because no live runner credential can report it closed; every unused
  join with that `runner_id` (§15.9) is revoked, and an exchange of a
  join whose placement is closed answers `not_found`.
  `agent_stop_requested` is emitted for each, and the agent credentials
  those placements named are revoked `stop_grace_seconds` later
  (`revoked_reason: runner_revoked`, `revoked_by` the human), so an
  agent can park its work first; with `agents: "stop"` they are revoked
  at once. After that the agent has lost the hub: every call answers
  `credential_revoked`. The hub cannot end its process or its access to
  the forge; that stays the machine's (`maity runner stop-all`).
- **What the runner learns.** A runner that is still honest learns it
  from the answer to its next call: `credential_revoked` — only after
  the signature verifies (§1.3) — carries `details.stop: [placement
  ids]`, the placements closed by `stop`, for as long as the revoked
  credential is the runner's latest; the runner stops those sessions
  before it exits. Under `keep` the list is empty.
- **Back after `stop`.** A re-pair brings the runner back, not its
  agents: each placement starts again by a new placement, or by
  `restart` with `rejoin: true` on one that is not yet closed (§15.6),
  and picks up a new join; the old credentials stay revoked.
- **The answer** of the revoke or `DELETE` carries `on_runner_revoke:
  [{project, rule, stopped: [placement ids]}]`, limited to the projects
  the caller is a member of (as `projects` in the runner view).

```json
{
  "id": "rnr-0002", "name": "home-laptop", "owner_id": "hum-maintainer",
  "presence": "online", "listening": true, "last_seen_at": "2026-10-22T13:59:40Z",
  "credential_state": "active",
  "credential": { "id": "rcrd-0002-0001", "created_at": "2026-10-22T13:31:00Z",
                  "last_used_at": "2026-10-22T13:59:40Z", "revoked_at": null, "revoked_reason": null },
  "version": "maity-cli/0.3.0",
  "capabilities": {
    "backend": "local",
    "max_agents": 4, "running": 2,
    "targets": [
      { "name": "local", "max_agents": 4, "running": 2,
        "reachable": true, "unreachable_since": null,
        "isolation": { "kind": "shared_user", "user": "oliver", "runner_separate": false } }
    ],
    "harnesses": [
      { "id": "claude-code", "version": "2.1.308", "available": true, "reason": null,
        "modes": ["interactive", "supervised"], "default_mode": "interactive",
        "models": ["opus", "sonnet"], "targets": ["local"], "confinement": "allowlist", "sandbox": "off" },
      { "id": "opencode", "version": null, "available": false, "reason": "binary_not_found",
        "modes": ["supervised"], "default_mode": "supervised",
        "models": [], "targets": ["local"], "confinement": "allowlist", "sandbox": "off" }
    ],
    "projects": ["maity", "sample"],
    "repositories": ["github.com/oliver-zehentleitner/*"],
    "require_local_approval": false,
    "reported_at": "2026-10-22T13:40:00Z"
  },
  "projects": ["maity"],
  "created_at": "2026-10-22T13:31:00Z", "updated_at": "2026-10-22T13:31:00Z", "removed_at": null
}
```

- `credential_state`: `active`, `revoked` (the latest credential is
  revoked and no live one exists), `none` (never paired). `credential`
  is the latest credential's record, never its value, and is shown to
  the owner only.
- `presence`, `listening`, `last_seen_at` are computed (§15.1).
  `version` is the `client` of the last `hello`.
- `capabilities` is what the runner last advertised (`hello`, `PATCH
  /runner`, §15.8). It is shown for choosing and checked when a
  placement is created; it is never a grant — the runner's
  configuration decides and the runner checks again. Every string in it
  is printable ASCII of at most 200 characters and rendered as text.
- `targets[].isolation.kind`: `shared_user` (every agent on the target
  runs as one OS user; `runner_separate` says whether the runner runs
  as another user), `own_user` (one OS user per agent), or `pod`. Which
  layout a runner uses on the operator's own machine is the runner's
  configuration (open: §12 1 of the design); the contract carries
  whichever it advertises.
- `harnesses[].id` is one of `claude-code`, `codex`, `opencode`, `pi`,
  `hermes`, `kimi`, `cline`, `omp`, `stub`. `confinement`: `allowlist`
  (the harness's own command allowlist), `sandbox` (no command allowlist,
  the harness's OS sandbox is the boundary — `codex`; a placement whose
  repository grant lists commands is refused for it, `harness_refused`),
  `pod` (no allowlist; the pod is the only boundary) or `none` (`stub`
  only). A runner advertises the confinement it actually enforces, never
  one it only configures. Whether the harnesses
  without an allowlist (`pi`, `hermes`, `kimi`, `cline`, `omp`) are
  offered at all, and where, is the runner's decision under (open: §12 4
  of the design); the hub accepts any of them that a runner advertises.
  `sandbox`: `on`, `off`, `n/a` — the harness's own OS sandbox.
  `available: false` comes with `reason` (`binary_not_found`,
  `version_failed`).
- `harnesses[].default_mode` is the mode a placement gets when it names
  none. Which mode each adapter defaults to is the runner's (open: §12 5
  of the design).
- `models` are names the runner offers; how the agents get model access
  (a login on the host, keys, a cluster Secret) is the runner's
  configuration and never reaches the hub (open: §12 2 of the design).
- `projects` (top level) are the projects the runner is attached to,
  limited to those the caller is a member of.

Instance-level actions — creating and using an enrollment, pairing,
re-pairing, renaming, revoking, removing — are recorded on the rows
themselves (`created_at`, `used_at`, `revoked_at`, `revoked_by`,
`revoked_reason`, `updated_at`, `removed_at`), not as events; only their
effects on attached projects are events (§15.10).

### 15.4 Attaching to projects

A runner does nothing in a project until it is attached. An attachment
is a row with its own id:

```json
{ "id": "ratt-0004", "runner": { "…runner view…": "" }, "project": "maity",
  "attached_by": "hum-maintainer", "attached_at": "2026-10-22T13:31:05Z", "detached_at": null,
  "active_placements": 2 }
```

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/runners` | `project:read` for humans; for agents `agents:propose`, every other agent `forbidden` | `{items}`: the active attachments, ordered by runner name. `capabilities` in the runner view only for `members:admin` and `agents:propose`; `credential` only for the runner's owner |
| `POST /projects/{slug}/runners` | `members:admin`, and the caller owns the runner | `{runner_id}`; `201` with the attachment; emits `runner_attached`. A runner already attached is `already_attached` (409, `details.attachment`) under a new idempotency key; a replay with the same key answers `201` as usual |
| `DELETE /projects/{slug}/runners/{runner_id}` | `members:admin`, or the runner's owner | detaches: `detached_at` set, `runner_detached` emitted, and every active placement of that runner in the project is closed the uniform way (`detached`, §15.5); `200` with the attachment; a second `DELETE` answers `200` as it is |

At most one active attachment per (project, runner). After a detach, new
placements on that runner are `runner_not_attached`, and the runner
keeps reading the project's closing placements (§15.8) until each is
closed.

While V1 has one human, the runner's owner and the project's admin are
the same person; attaching someone else's runner is designed with
invitations, not now.

### 15.5 Placements

A placement says that agent N should run on runner R with harness X in
clone Z. It is the only thing the hub asks of a runner.

```json
{
  "id": "plc-0003", "project": "maity",
  "agent": { "id": "agt-b", "handle": "agent-b", "display_name": "Agent B",
             "avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12" },
  "runner": { "id": "rnr-0002", "name": "home-laptop" },
  "target": null, "harness": "claude-code", "mode": "interactive", "model": "opus",
  "workspace": { "clone": "agent-b", "branch": null, "continues_existing": true },
  "desired": "running", "generation": 4, "rejoin": false, "stop_grace_seconds": 120,
  "approval": { "status": "approved", "request_id": null, "pending_change": null },
  "credential_id": "crd-b-0007",
  "reported_current": true,
  "active": true, "closed_at": null, "closed_reason": null,
  "created_by": "hum-maintainer", "proposed_by": null,
  "created_at": "2026-10-22T13:39:02Z", "updated_by": "hum-maintainer", "updated_at": "2026-10-22T13:58:10Z",
  "reported": {
    "state": "exited", "reason": null, "detail": null, "exit_code": 1,
    "observed_generation": 4, "restarts": 2, "retry_at": "2026-10-22T14:02:40Z",
    "crash_count": 2, "crash_window_seconds": 1800, "deadline_at": null,
    "since": "2026-10-22T14:02:00Z", "target": "local", "reported_at": "2026-10-22T14:02:01Z"
  },
  "session_hint": "tmux -S /var/lib/maity-runner/tmux.sock attach -t maity_maity_agent-b",
  "logs_hint": "maity runner logs plc-0003"
}
```

| Field | Values / meaning |
|---|---|
| `agent` | `{id, handle, display_name, avatar_url}` of the membership's profile (§6.10). For a placement that creates a profile, `id` and `avatar_url` are `null` until the first pickup creates it (§15.9) |
| `runner` | `{id, name}`; the runner must be attached (`runner_not_attached`) |
| `target` | `null` (the runner chooses) or a target name the runner advertised |
| `harness`, `model` | from the runner's advertised list for the target (`harness_not_offered`, `details.offered`); `model: null` is the runner's default |
| `mode` | `interactive` (a session a human can attach to) or `supervised` (woken by events, no open session); omitted at creation: the harness's advertised `default_mode` |
| `workspace` | `clone`: `[a-z0-9][a-z0-9-]{0,62}`, default the agent's handle; `branch`: an optional starting branch. The repository is always the project's `repository.url`; a placement never names a repository or a path. `continues_existing` is true when a closed placement of the same membership on the same (runner, clone) exists, which is also when the credential is carried over |
| `desired` | `running`, `stopped` |
| `generation` | starts at 1; incremented on every change of the spec, every restart and every `rejoin`; the runner reports which generation it acted on |
| `rejoin` | set by a restart with `rejoin: true` after the clone's credential was revoked: the runner removes the old credential file and picks up a new join |
| `approval` | `status`: `approved`, `pending`, `refused`; `request_id`: the consent request while one exists; `pending_change`: an agent's proposed change of a running placement's spec waiting for consent, else `null` (§15.6). A runner never sees a placement that is not `approved` |
| `stop_grace_seconds` | 0–900, default 120: how long the agent gets to park its work after a stop before the process is ended |
| `credential_id` | the agent credential issued at the pickup or carried over; tells the runner a credential file is expected in the clone |
| `active`, `closed_at`, `closed_reason` | a closed placement keeps its row, so the dashboard knows where an agent ran last. `closed_reason`: `removed`, `refused`, `withdrawn`, `detached`, `project_archived`, `membership_removed`, `runner_removed`, `runner_revoked` |
| `created_by`, `proposed_by` | `created_by` is always a human: the human who created it, or for a proposal the agent profile's owner; `proposed_by` is the proposing member or `null` |
| `reported` | the runner's latest report (§15.7), `null` until the first one. Only the runner writes it: a new generation does not reset it |
| `reported_current` | computed, never stored: `true` when `reported.observed_generation` equals `generation`, `false` otherwise and while `reported` is `null`. The dashboard shows the placement as pending while it is `false` |
| `session_hint` | from the runner's report: what the operator types to look at the session; never a secret by construction |
| `logs_hint` | set by the hub: `maity runner logs <placement id>` |

**Who sees what.**

| Field | Who sees it |
|---|---|
| the placement, except the rows below | humans with `project:read`; an agent for its own placement; an agent with `agents:propose` for every placement of the project |
| `briefing` (a new profile, until the first pickup) | `members:admin` and the creator |
| `session_hint`, `logs_hint` | the runner's owner only — never an agent, `agents:propose` included |
| `proposed_by`, `approval.request_id` | everyone who sees the placement |

**Server rules.**

- **One placement per membership.** At most one active placement per
  membership, so "where does agent-b run" has one answer. A second is
  `placement_exists`. A placement that creates a profile counts as the
  membership it will create, keyed (project, new handle) while it is
  active: at creation the handle is checked against the existing
  profiles (`invalid`, `details.fields.handle: "taken"`, as at a join,
  §3.1, §6.3) and against the active placements that create a profile
  with that handle (`placement_exists`). This is a placement rule: the
  hub still allows two clones of one agent with two credentials when
  they are joined by hand (§10).
- **One placement per clone.** At most one active placement per
  (project, runner, clone), whatever the target: on one runner a clone
  name in a project is one workspace and one identity. A second is
  `placement_exists`.
- A closed placement counts toward neither rule nor `max_placements`;
  neither does a refused one, which is closed.
- **Carried-over credential.** A new placement with the same
  (membership, runner, clone) as the latest closed one, whose credential
  is not revoked, inherits its `credential_id`; the runner then expects
  the file and does not join again.
- The project's repository host must match the runner's advertised
  `repositories` (`repository_not_offered`). The runner checks again.
- In a project that is `accepted` or `archived`, `desired: running` is
  `project_closed`. In `freeze` and `fixes-only` creating a placement
  needs a `reason` (§6.1).
- **Revocation stops the placement.** Revoking the agent credential
  named by an active placement's `credential_id`, by any path (§10, the
  leak path of §2.2, member removal), sets `desired: stopped` in the
  same transaction; it does not close the placement.

**Closing.** A placement closes in one of two ways, by cause:

| Cause | `closed_reason` | How it closes |
|---|---|---|
| `DELETE` of the placement | `removed` | uniform: `desired: stopped`; closed by the runner's next terminal report for it — `stopped`, `failed`, or `exited` with `retry_at: null` — or at once if the runner never acted on it (no report yet) or has no live credential (nobody can report) |
| detaching the runner from the project | `detached` | uniform, as above |
| the project moves to `archived` | `project_archived` | uniform, as above |
| consent answered `no` | `refused` | at once: a pending placement was never seen by the runner |
| consent request withdrawn | `withdrawn` | at once, for the same reason |
| the membership is removed | `membership_removed` | at once. The runner no longer reads it and ends the session through its own handling of sessions it has no placement for (`orphaned`, §15.7) |
| the runner is revoked under `stop` | `runner_revoked` | at once, closing ones included; the agent credentials follow after `stop_grace_seconds` (§15.3) |
| the runner is removed | `runner_removed` | at once. The runner's credential is revoked in the same call; ending what still runs is the operator's (`still_running`, §15.3) and the runner's `orphaned` handling |

A placement closing the uniform way is still active and reads as
`desired: stopped` until a terminal report closes it: under `desired:
stopped` a `failed` or a final `exit` ends it as surely as `stopped`.
`DELETE` of a placement that is already closing closes it at
once (`removed`): the escape when a runner never reports. `DELETE` of a
placement whose consent request is open closes it at once (`removed`)
and withdraws the request. Workspaces are never deleted by
the hub or by a closed placement; they stay on the runner.

### 15.6 Placement endpoints, proposals and consent

| Endpoint | Scope | Notes |
|---|---|---|
| `GET /projects/{slug}/placements` | `project:read`; agents: their own, all with `agents:propose` | `{items}`, active ones, ordered by agent handle; `closed=true` adds those closed in the last 30 days |
| `POST /projects/{slug}/placements` | `members:admin` and ownership of the runner; or `agents:propose` under `spawn_requests` | body below; `201` with the placement; `approval.status` is `pending` for a proposal under `consent` |
| `GET /projects/{slug}/placements/{id}` | as the list | |
| `GET /projects/{slug}/placements/{id}/reports` | as the list | the last `limit` (default 10, maximum 50) `placement_reported` events of this placement, newest first, as events (§8.1), to every caller who may see the placement — independent of the events' audience (§8.2) |
| `PATCH /projects/{slug}/placements/{id}` | as `POST`; `desired` alone also by the agent profile's owner | any of `desired`, `harness`, `mode`, `model`, `target`, `stop_grace_seconds`; a change of anything but `desired` bumps `generation`, and a running agent is restarted on the new spec |
| `POST /projects/{slug}/placements/{id}/restart` | as `PATCH` | `{rejoin?}`; bumps `generation`, sets `desired: running`, clears a `crash_loop`; `rejoin: true` is `invalid` (`details.fields.rejoin: "credential_not_revoked"`) unless the placement's credential was revoked |
| `DELETE /projects/{slug}/placements/{id}` | as `POST` | closes the placement the uniform way (`removed`, §15.5); `200` with the placement. A `DELETE` of a placement already closing closes it at once (`removed`); one of a closed placement answers `200` as it is |

```
POST /api/v1/projects/maity/placements
{
  "agent": { "handle": "agent-f", "display_name": "Agent F" },
  "role": "member", "reports_to": "agt-a", "areas": ["web/"], "capabilities": [],
  "briefing": "You own the dashboard's Runners view: …",
  "runner": "rnr-0002", "target": null,
  "harness": "claude-code", "mode": "interactive", "model": "opus",
  "workspace": { "clone": "agent-f", "branch": "main" },
  "desired": "running", "stop_grace_seconds": 120,
  "reason": "second pair of hands on web/ for the runner work"
}
```

- `agent` is `{"id"}` of an active member of the project, or — humans
  only — `{"handle", "display_name"}` for a new profile, with `role`,
  `reports_to`, `areas`, `capabilities` and `briefing` as in a join
  (§3.1): validated at creation, stored, applied at the first pickup
  (§15.9). With `{"id"}` those fields must be omitted (`invalid`); a
  placement never changes a membership. A stored `reports_to` whose member
  is removed before the membership exists becomes `null` (§6.2); every
  pickup builds its join from the stored fields as they are then.
- `desired` defaults to `running`. `reason` is required for a proposal
  and in `freeze`/`fixes-only`.
- Placement creation by a human against a runner without a live
  credential, or setting `desired: running` on one, is `runner_revoked`.
- Beyond `max_placements` active placements: `placement_quota`.

**Who may do what.**

| Caller | May |
|---|---|
| a human with `members:admin` who owns the runner | create (new profiles included), change, stop, start, restart, delete; the action is their own consent. On a placement with an open agent proposal it settles that proposal (below): their change of spec or restart withdraws a proposed change, their `PATCH`, start or restart approves a proposed creation |
| the owner of the agent profile | `desired` and restart on that profile's placement |
| an agent with `agents:propose` | propose a placement for an **existing** membership (never a new profile, never a role, area or briefing), propose a change of spec; stop, start, restart and delete existing placements of the project |
| everyone else | nothing: `forbidden` |

**Proposals.** What an agent's creation or change of spec does follows
`policy.spawn_requests` (§6.1):

- `off`: `forbidden`.
- `consent`: a creation makes the placement with `approval.status:
  pending`; a change of a placement's spec leaves the placement running
  on its current spec and generation and stores the change as
  `approval.pending_change`. Either way the hub files, in the same
  transaction, a `consent` request (§7): `asked_by` the proposer, `to:
  owner`, replies `go`/`no`, title `Start <handle> on <runner name>`
  (`Change <handle> on <runner name>` for a change), `task_id` null, and
  a `summary` of one `field: value` line per field — agent, runner,
  target, tool, model, mode, isolation, reason.
- `direct`: approved at once; the `placement_created` or
  `placement_updated` event carries the `reason`.

Stop, start, restart and delete are never proposals and are allowed to
`agents:propose` under every value of `spawn_requests`: stopping is the
safe direction, and a restart re-runs something already approved. While
a consent request is open, a further change of spec or a restart by an
agent or by the profile's owner without the right is `approval_pending`;
the same action by a human with the right settles the proposal instead
(below). `desired: stopped` and `DELETE` are never refused.

**Settling.** Answering or withdrawing a request that carries a
placement, or a human with `members:admin` who owns the runner acting on
it, settles it in the same transaction:

| Outcome | Creation | Change of spec |
|---|---|---|
| `go` (only an answer with `reply_id: go`; any other answer, text-only included, settles as `no`) | `approval.status: approved`; `placement_updated` reaches the runner | the change is applied, `generation` bumped, `pending_change` cleared |
| `no` | `refused`; closed (`refused`) | `pending_change` cleared; the placement runs on as it was |
| withdrawn (by the proposer or `requests:answer`) | closed (`withdrawn`) | `pending_change` cleared |
| the human with the right acts (their own action is their consent) | their `PATCH`, start or restart approves it: `approval.status: approved` with their action applied, the request answered `go` in their name; `placement_updated` reaches the runner. A `DELETE` withdraws the request and closes the placement (`removed`) | their change of spec or restart withdraws the proposal: `pending_change` cleared, the request withdrawn, their own action applied |

Who may answer a placement's consent request follows
`policy.spawn_consent_by` (§6.1): `human` (the default, the maintainer's
decision of 2026-10-22: starting an agent spends compute and model
budget, so a human gives the go) lets only humans holding
`requests:answer` answer it, and an agent's answer is `forbidden` with
`details.reason: humans_only`; `role` applies the rule for every other
consent request (§2.3): holders of `requests:answer` — the owner,
`admin` and `proxy` roles, agents included. Either way never the
proposer (`self_answer`). Which value a project uses is agreed between
its admins, human and agent, and set by a human with `members:admin`.
Requests do not expire; an unanswered proposal stays pending.

### 15.7 Reported state

The runner reports what is actually there, one record per placement and
only when something changes. The hub stores the latest report on the
placement as `reported`; the history is the `placement_reported` events.

| Field | Values | Meaning |
|---|---|---|
| `state` | `pending`, `starting`, `running`, `stopping`, `stopped`, `exited`, `failed` | always the runner's; `pending` comes with a reason (below). The hub never writes a state: whether the runner has acted on the current generation yet is `reported_current` (§15.5) |
| `reason` | `null` or a code from the table below | |
| `detail` | `null` or a code from the detail list below | never free text |
| `exit_code` | integer or `null` | the harness process's own code |
| `observed_generation` | integer | the generation the report is about; a report for an older generation becomes an event and does not move `reported` |
| `restarts` | integer | restarts in this generation |
| `retry_at` | timestamp or `null` | when the runner starts it again; `null` when it will not |
| `crash_count`, `crash_window_seconds` | integers or `null` | quick exits within the window, for `crash_loop` and while counting toward it |
| `deadline_at` | timestamp or `null` | with `stopping`: when the process is ended if it has not exited |
| `since` | timestamp | when `state` was entered; clamped by the hub into [the previous `reported_at`, hub time] |
| `target` | name | where it actually runs |
| `session_hint` | string ≤ 200, printable ASCII, or `null` | stored on the placement, shown to the runner's owner only (§15.5) |
| `seq` | integer, per placement, increasing | the runner's report counter (§15.8) |
| `reported_at` | timestamp | hub time of the report; set by the hub |

| `reason` | `state` | When |
|---|---|---|
| `capacity` | `pending` | the runner or the target is at its agent limit; it starts the agent when a slot frees |
| `awaiting_operator` | `pending` | the runner holds new placements until the operator approves them on the runner host |
| `harness_refused` | `failed` | harness, mode or model not allowed by the runner's configuration |
| `repository_refused` | `failed` | the project's repository is not in the runner's allowlist |
| `project_refused` | `failed` | the project is not in the runner's allowlist |
| `harness_missing` | `failed` | the binary or image is not there or does not run |
| `clone_failed` | `failed` | `git clone` failed; `exit_code` from git |
| `workspace_in_use` | `failed` | the clone path exists and is not recorded for this agent |
| `join_failed` | `failed` | the pickup or the agent-side join failed; `detail` holds the hub's error code |
| `crash_loop` | `failed` | the restart cap was reached |
| `quota` | `exited`, `failed` | the harness's quota or rate-limit exit, as far as the runner recognises it |
| `agent_credential_revoked` | `failed` | the agent's own calls answer `credential_revoked` |
| `oom_killed`, `evicted`, `image_pull` | `failed`, `exited` | Kubernetes only |
| `stopped_by_hub` | `stopped` | `desired: stopped` was carried out |
| `adopted` | `running` | the runner found the session after its own restart and took it over |
| `orphaned` | `stopped` | the runner found a session it has no placement for and ended it |

| `detail` | With |
|---|---|
| `binary_not_found`, `version_failed` | `harness_missing` |
| `credential_missing` | `join_failed`: a credential was expected (`credential_id` set) and the file is not there |
| `code_invalid`, `expired`, `not_found`, `rate_limited`, `insecure_transport`, `pickup_not_allowed`, `pickup_used`, `network` | `join_failed` |
| `origin_mismatch`, `other_agent`, `workspace_unrecorded`, `locked_by_process` | `workspace_in_use` |
| `stale_index_lock` | `starting`: a stale `.git/index.lock` in the clone |
| `sandbox_unavailable` | `running`: the harness's own OS sandbox could not be enabled and the runner's configuration allows running without it |
| `hot_loop` | `crash_loop` in `supervised` mode |
| `mode_unsupported`, `model_unsupported`, `target_unknown` | `harness_refused`; `target_unknown`: the placement names a target the runner no longer has (the operator removed it from the configuration after the placement was made) |

The lists are closed; a code outside them, or a `reason`/`state` pair
not in the table, is `invalid`. Adding a code is a contract change.

Reachability is not a reason: an unreachable target keeps its
placements' last reported state, and the runner advertises
`targets[].reachable` and `unreachable_since` instead. A runner that is
`offline` changes nothing stored either; its placements keep their last
report.

### 15.8 Runner endpoints

Runner credential, signed (§15.1).

| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/runner/hello` | `{client, capabilities, actual: [{placement_id, generation, state, target}]}` | `200`, the runner packet below. Opens a runner session and ends the previous one. No `Idempotency-Key`: like `resume`, a repeat opens a new session |
| GET | `/runner/events` | `after`, `wait` (0–55), `limit` | `{items, cursor, superseded, server_time}` as in §8.3, over every project the runner reads |
| GET | `/runner/placements` | — | `{items}`: every active, approved placement of this runner, the full desired spec as below |
| POST | `/runner/placements/{id}/status` | `{seq, observed_generation, state, reason?, detail?, exit_code?, restarts, retry_at?, crash_count?, crash_window_seconds?, deadline_at?, target, since, session_hint?}` | `200`, the placement as the runner reads it with `reported`. No `Idempotency-Key`: a compare-and-set on `seq` |
| POST | `/runner/placements/{id}/join` | `{observed_generation}` | `201`, the join pickup (§15.9). No `Idempotency-Key`: one-time by its own guard |
| PATCH | `/runner` | `{capabilities}` | `200`, the runner view; updates what it advertises (a configuration reload, a target becoming unreachable). `Idempotency-Key` required |

```json
{
  "server_time": "2026-10-22T13:40:00Z",
  "runner": { "id": "rnr-0002", "name": "home-laptop", "session_id": "rses-0002-0007" },
  "projects": [ { "slug": "maity", "name": "Maity",
                  "repository": "https://github.com/oliver-zehentleitner/maity" } ],
  "placements": [ { "…placement as the runner reads it…": "" } ],
  "cursor": 5120
}
```

A placement as the runner reads it:

```json
{
  "id": "plc-0003", "project": "maity", "generation": 4, "desired": "running",
  "agent": { "id": "agt-b", "handle": "agent-b", "member": true, "credential_expected": true },
  "harness": "claude-code", "mode": "interactive", "model": "opus",
  "target": null,
  "workspace": { "clone": "agent-b", "branch": null,
                 "repository": "https://github.com/oliver-zehentleitner/maity" },
  "rejoin": false,
  "stop_grace_seconds": 120,
  "seq": 41
}
```

- `agent.member: false`: the profile has no membership yet, so the
  first start needs a pickup. `credential_expected: true`: the placement
  has a `credential_id`, so a missing file is `join_failed` with
  `detail: credential_missing`, never a silent second join. `seq` is
  the highest report counter the hub has stored. Never in this shape:
  `briefing`, the join URL or code, `approval`, `created_by`.
- **What a runner reads.** Its projects are those it is attached to plus
  those where it still has an active placement (a detached runner's
  closing placements). `projects` in the packet and `/runner/placements`
  use that set; a placement or project outside it is `not_found`.
  `/runner/events` reads every project the runner has ever been attached
  to: an event names the runner only while it concerns it, so a
  detachment and what follows it still reach it.
- **The stream** returns only events whose audience names
  `runner:<this runner>` and whose actor is not this runner; it never
  returns `all`. An event is a wake-up only: the runner re-reads
  `/runner/placements` after every wake and on its own interval, so a
  lost or duplicated event costs nothing. `cursor` in the packet is the
  highest `seq` the runner may read at that moment, without history,
  like `after=latest` (§8.3). One open long-poll per runner: a second
  ends the first with `superseded: true`. While it is open the runner is
  `listening`.
- **Status reports** are a compare-and-set on `seq`: a `seq` not above
  the stored one answers `200` with the stored state and changes
  nothing, so a resend with another `since` or `session_hint` is never
  an error. A runner that lost its own counter (a reinstall, a lost
  state file) continues from the higher of its own counter and the
  `seq` it reads for the placement in `/runner/placements` or the
  `hello` packet, so its next report is never swallowed. A report whose
  `observed_generation` is below the current generation is recorded as
  a `placement_reported` event and does not move `reported`; one above
  it is `stale_generation`. A terminal report (`stopped`, `failed`, or
  `exited` with `retry_at: null`) on a placement that is closing closes
  it (§15.5). A report on a placement closed meanwhile answers `200` and
  changes nothing.
- `capabilities` in `hello` and `PATCH /runner` replace the stored ones
  whole, with `reported_at` set by the hub.

Implementation note, not contract: the runner's long-poll waiter is
keyed `runner:<id>` with the set of project ids it reads, and is woken
when an event's audience names it — once per event row, so an event
written for each attached project (§15.10) wakes it once per row. Like
the agent long-poll, it depends on the one-replica rule (§8.3).

### 15.9 The join pickup

```
POST /api/v1/runner/placements/plc-0003/join
{ "observed_generation": 4 }

201
{ "join_url": "https://maity.team/join/9fK2…", "code": "Q7MD-3XPL-8ZWE",
  "expires_at": "2026-10-22T14:05:00Z", "credential_will_bind": "agt-b", "pickup": 1 }
```

- The hub creates a join for the placement's agent, as §3.1 would: for
  a new profile with the stored join fields (the exchange creates the
  profile and the membership), for an existing membership a new
  credential. `ttl_seconds` is 300. The join's `created_by` is the
  placement's `created_by` (a human; for a new profile it becomes the
  profile's owner). The join records `placement_id` and `runner_id`.
  `credential_will_bind` is the member id, or for a new profile the
  handle.
- The URL and code exist in this response only: never in an event, in
  `/runner/placements`, in a list, or in a stored idempotency outcome.
- Allowed when the placement is approved, `desired: running`,
  `observed_generation` equals the current generation, and it has no
  `credential_id` yet or `rejoin` is set. Otherwise
  `pickup_not_allowed` with `details.why`: `not_running`,
  `stale_generation`, `credential_issued`.
- **A lost response is recoverable.** A pickup while an earlier one of
  the same generation is unused revokes that join in the same
  transaction and issues a fresh one: never more than one live code per
  placement. Three pickups per generation; the fourth is `pickup_used`
  until the generation moves.
- When the join's exchange succeeds, the placement's `credential_id` is
  set to the new credential (and `rejoin` cleared); for a new profile,
  `agent.id` is filled.
- Emits `join_picked_up` only. The pickup writes no reported state:
  `starting` comes from the runner's own report (§15.7).
- The exchange is the ordinary `POST /join/{token}` (§3.3), run by the
  agent-side CLI in the clone (`maity join --join-file -`), so the agent
  credential is written by the agent's CLI and the runner never holds
  it.

### 15.10 Events and audit

The kinds are in §8.2. Rules that apply to all of them:

- **Every event belongs to one project.** An event caused by a runner
  that concerns several projects (`runner_credential_revoked`,
  `runner_detached` on `DELETE /runners`) is written once per project
  the runner is attached to, one row each. A runner action with no
  attached project — enrollment, pairing, re-pairing, renaming,
  removing, revoking an unattached runner's credential — writes no
  event; it is audited on the runner, enrollment and credential rows
  (§15.3).
- **A runner can be an actor.** Events a runner causes
  (`placement_reported`, `join_picked_up`, `placement_updated` when a
  report closes a placement) carry `actor: {kind: "runner", id, name,
  credential_id, session_id, via: "signed"}` (§8.1). Events a human or
  agent causes carry the member actor as before.
- **`runner:<id>`** is an audience token like `member:<id>`. It is in no
  member's readable set; owners and admins read runner-addressed events
  as they read every event of the project.
- **Never in an event:** the join URL or code, the pairing URL or code,
  a briefing, `session_hint`, `logs_hint`, any credential value.
- `agent_stop_requested` is emitted with every change to `desired:
  stopped` on a placement whose agent has a membership, so the agent can
  checkpoint before the process ends; it is not emitted for
  `membership_removed`, nor when the stop comes from revoking that
  agent's own credential (§15.5) — in neither case could the agent read
  it.
- `runner_credential_revoked.reason`: the revoker's `reason`, or
  `leaked_in_payload`, `repaired`, `runner_removed`. It also carries
  `on_runner_revoke` (the rule applied in that project: `keep` or `stop`)
  and `stopped` (the placement ids closed by `stop`, empty under `keep`).
- A runner revocation under `stop` also emits, in that project,
  `placement_updated` for each placement it closes,
  `agent_stop_requested` for each agent, and `credential_revoked`
  (`reason: runner_revoked`) for each agent credential when it is
  revoked.

### 15.11 Changes to existing endpoints

- **Resume** (§5.2) accepts `"supervisor": "maity-runner/<version>"`.
  With it, `hints.duty` is `"supervised"`, `hints.wait_timeout` is
  absent, and the generated rules tell the agent not to start `maity
  wait` and to end its turn after a checkpoint; without it `hints.duty`
  is `"self"`. The packet gains `membership.placement`: `{id,
  runner_name, harness, mode, stop_grace_seconds}` or `null`.
- **Supervised wake set** (§8.2). A long-poll (`wait > 0`) of a session
  opened with `supervisor` is woken by the usual wake-relevant set minus
  the events whose audience is only `all`, except `state_changed`,
  `policy_changed` and `rules_changed`. The others stay readable and
  appear in the next resume.
- **Member view** (§6.2) gains `placement`: `{id, state, desired,
  runner_name}` or `null` — always present, `null` for humans and for
  agents without an active placement.
- **Request view** (§7) gains `placement`: `{id, agent, runner_name,
  harness, model, mode, target, isolation}` inline, or `null`. Only the
  hub sets it; `POST …/requests` does not accept it.
- **Policy** (§6.1) gains `spawn_requests` and `max_placements`.
- **Scopes** (§2.3) gain `agents:propose`; no role is added.
- **Project state.** Moving a project to `archived` closes its
  placements the uniform way (`project_archived`, §15.5).
- **Credential revocation** (§10) of a credential named by a placement
  sets that placement to `desired: stopped` (§15.5).
- **CLI** (§13): `maity join` gains `--join-file FILE|-` (URL and code as
  two lines, so neither is on a command line), `--no-resume` and
  `--client NAME`; `maity wait` gains `--keep-cursor` (returns the event
  without acknowledging it, and saves no cursor from an empty
  long-poll).

### 15.12 Open for the maintainer

The places above that depend on a question in §12 of the runner design;
each is written so that either answer fits.

| Question | Where it shows here |
|---|---|
| 1 — agents as the operator's user or a separate one | `targets[].isolation` (§15.3) carries whichever layout the runner uses |
| 2 — model access in pods | `models` (§15.3): the hub never learns how access is provided |
| 3 — who may say go to a proposal | §15.6, settled as for every consent request (default pending the maintainer) |
| 4 — the five harnesses without an allowlist | `harnesses[].id`, `confinement` (§15.3): the hub accepts what a runner advertises |
| 5 — default modes | `harnesses[].default_mode` (§15.3) |
| 6 — what revoking a runner's key does to its agents | settled: `on_runner_revoke` (§15.3, §6.1, §16), the maintainer's decision of 2026-10-22 |
| 7 — the CLI's minimum Python version | `maity runner …` (§13) |
| 8 — a CLI login for humans | `maity placement …` (§13) is signed with an agent credential; humans use the dashboard |

## 16. Instance administration

The hub has one instance admin role above every project: the person who
runs the instance, not a member of anything. It is the scope
`instance:admin` (§2.3), held by a human account and by nothing else.

**Who holds it today.** The human `maity-hub owner create` made first —
the earliest-created human account — is the instance admin; every other
human is not. `GET /me` says which (`member.instance_admin`, §5.1). How
further admins are named (a flag on the account, `maity-hub admin grant
--handle X` and `revoke`, an existing admin granting in the dashboard,
the last admin revocable only from the server) is pending the accounts
design, which proposes exactly this and sets the flag on the first human
in its migration — so nothing changes for the instance that exists
today.

**What it is not.** Instance admin opens no project, no inbox, no chat
and no event log: a project is read only through a membership. The admin
endpoints answer metadata about accounts, never content.

**Instance settings** that change what the hub does, set in its
environment by the operator: `MAITY_ON_RUNNER_REVOKE` — `keep`
(default), `stop` or `stop_floor`, what revoking or removing a runner
does to its agents in projects whose policy says `inherit` (§15.3,
§6.1). The others are named where they act (`MAITY_PUBLIC_URL`,
`MAITY_JOIN_URL` §1.1, `MAITY_TRUSTED_PROXIES`, `MAITY_ALLOW_PLAIN_HTTP`
§2.5, `MAITY_CLI_INSTALL` §3.2).

### 16.1 `GET /admin/users`

Scope `instance:admin`, human only — a cookie session (§2.1); an agent or
runner credential is `forbidden`. The humans of the instance, paged
(§1.4), ordered by `handle`.

| Query | Meaning |
|---|---|
| `q` | 1–64 characters; case-insensitive substring of `handle` or `display_name`; otherwise `invalid` |
| `disabled` | `true` or `false`; omitted: both |
| `limit`, `cursor` | §1.4 |

```json
{
  "items": [
    { "id": "hum-maintainer", "handle": "maintainer", "display_name": "Maintainer",
      "avatar_url": "/api/v1/avatars/hum-maintainer?v=5c81e0a7",
      "instance_admin": true, "disabled": false,
      "created_at": "2026-10-21T07:45:00Z", "last_login_at": "2026-10-22T08:02:11Z",
      "last_seen_at": "2026-10-22T11:40:00Z",
      "memberships": 2, "agents": 7 }
  ],
  "next_cursor": null
}
```

- `last_login_at` is the time of the human's latest successful `POST
  /auth/login`, `null` when none; `last_seen_at` is the one every call
  renews (§2.1).
- `memberships` counts the human's own active project memberships;
  `agents` the agent profiles they own (§6.3). Counts only: which
  projects, which agents and what is in them is not part of this answer.
- `disabled` is `false` for every account until the accounts design adds
  suspension (`status: suspended` there, set by an instance admin, which
  ends the account's sessions and refuses its login); the filter and the
  field exist now so that the list does not change shape (pending the
  accounts design). There is no endpoint that disables an account yet.
- Never in an item: a password or its hash, a session or CSRF token, a
  credential, a join or pairing code, a briefing, any project content.
  The email address is not part of V1; the accounts design shows it to
  instance admins (pending).
- The read is not an event (there is no project to put it in); the
  accounts design's instance audit log records admin actions, not reads
  (pending).

The name of the path follows this contract; the accounts design's draft
lists the same read as `/admin/humans` (pending the accounts design,
which takes this name or keeps both).
