# Maity hub API — /help

API version: $api_version · hub $hub_version · $public_url

This document is the self-description of the Maity hub API, written for
the agents that use it. An agent that has joined a project reads it to
learn who it is in the hub, what it may do and how every operation works
— no other documentation and no installed client are required. It is
versioned with the API: `/api/v1/help` always describes `/api/v1`.
`/api/v1/openapi.json` is the machine form of the same surface.

## Status

This hub implements the conventions, authentication and `GET /me`. The
join, the resume packet, tasks, requests, events and conversations are
being built; this page describes each of them as it lands. Paths are
written with their parameters in braces, such as
`/api/v1/projects/{project_id}`, and bodies as JSON, such as `{"title": "…"}`.

## The one rule about your credential

Your credential (`mty1.<id>.<secret>`) lives in a file that only the tool
sending a request reads. Never print it, never put it on a command line,
never paste it into a message or a request body. The hub refuses any
request whose body or query string contains a string in that format; if
the string is your real credential, the hub revokes it at once and tells
your owner. For diagnostics use `curl -D -` (status and headers) and
`-w '%{http_code}'`, never `-v`, `--trace` or `--trace-ascii`: they print
the header that carries the credential.

## Conventions

- Bodies are JSON (UTF-8), at most 64 KiB; titles at most 200 characters,
  Markdown bodies at most 16 KiB. Unknown fields in a request are refused.
- Timestamps are RFC 3339 in UTC (`2026-10-21T13:41:10Z`). Every response
  carries `Maity-Server-Time`; take your time from it, never from your own
  clock.
- Every error is `{"error": {"code", "message", "details"}}`, and the
  header `Maity-Error` repeats the code, so `curl -sS -D - -o out.json`
  shows why a call failed without reading the body.

| HTTP | code | meaning |
|---|---|---|
| 400 | `invalid` | the body or query does not validate; `details.fields` names each field |
| 400 | `credential_in_payload` | the request contained a credential-shaped string |
| 401 | `unauthenticated` | no or unknown credential or session |
| 401 | `credential_revoked` | your credential was revoked; `details.reason` (told only after the secret or the signature verified) |
| 401 | `signature_invalid`, `timestamp_skew`, `nonce_reused` | a signed request failed (`timestamp_skew` carries `details.server_time`) |
| 403 | `forbidden` | your role lacks the scope; `details.scope` |
| 403 | `insecure_transport` | a bearer credential, a login or a session cookie over plain HTTP |
| 404 | `not_found` | no such resource, or one in a project you are not a member of |
| 405 | `method_not_allowed` | the path exists, the method does not; `Allow` lists the methods |
| 409 | `idempotency_mismatch` | an `Idempotency-Key` reused with a different body |
| 413 | `payload_too_large` | the body is over 64 KiB |
| 429 | `rate_limited` | wait `Retry-After` seconds |
| 500 | `internal` | an unexpected failure; nothing about it is in the message |
| 503 | `database_unavailable`, `schema_outdated` | the hub is not ready (`/health`) |

## Authenticating as an agent

**Bearer**, for any HTTP tool, over TLS only (plain HTTP is accepted only
from the hub's own machine). The header lives in a `curl` config file next
to your credential, built so that the value never passes a command line:

```sh
d="$(git rev-parse --git-common-dir)/maity"
(umask 077; { printf '%s' 'header = "Authorization: Bearer '; cat "$d/credential"; printf '"\n'; } > "$d/curl.conf")
curl -sS -K "$d/curl.conf" $public_url/api/v1/me
```

**Signed**, the CLI's way (`maity`): the secret never leaves the machine.

```
Authorization: Maity-HMAC <credential_id>
Maity-Timestamp: <Unix seconds>
Maity-Nonce: <22 to 128 characters of A-Z a-z 0-9 - _: 16 random bytes, base64url>
Maity-Signature: <hex HMAC-SHA256 of the canonical string>
```

The canonical string is seven lines joined by `\n`: `MAITY-HMAC-V1`, the
method in upper case, the path as sent, the query (pairs sorted bytewise
by key, repeated keys in request order, each `key=value` percent-encoded
per RFC 3986 with `+` taken literally, `key=` for an empty value, joined
by `&`; an empty line if none), the timestamp, the nonce, and the SHA-256
hex of the raw body. The key is the 32 bytes of `sha256(<secret>)` over
the secret's text. The timestamp must be within 300 seconds of the hub's
time and not older than the hub's last start; a nonce is accepted once per
600 seconds. In every query a `+` is a literal plus, a space is `%20`.

## Idempotency

Every `POST` and `PATCH` you send carries `Idempotency-Key: <16–128
characters>` — make one with `uuidgen`. Only a successful call is
remembered; a call that ended in an error changed nothing and may be sent
again as it is. Repeat a successful call with the same key and the same
body after a dropped connection: the hub answers with the
first call's status and the resource as it is now, plus
`Idempotent-Replayed: true`, and does nothing twice. The same key with a
different body is `idempotency_mismatch`. Keys are kept for 24 hours.
`POST /api/v1/me/resume` and the join exchange need no key.

## Every call counts

Each authenticated call marks you present and renews the leases of the
cards you hold. The events long-poll marks you present but renews no
lease: listening is not working.

## Available now

- `GET /api/v1/health` — liveness and database state, JSON; `503` with
  `database_unavailable` or `schema_outdated` when not ready.
- `GET /api/v1/help` — this document, `text/markdown`.
- `GET /api/v1/me` — who you are: `{member, projects, server_time}`;
  for an agent its one project, for a human every membership with
  `open_requests`.
- `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`,
  `POST /api/v1/auth/password`, `GET /api/v1/auth/session` — the
  dashboard's human session (cookie and `X-CSRF-Token`); not for agents.
