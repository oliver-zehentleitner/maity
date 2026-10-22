# Joins

## The join page's HTML comes from markdown-it-py with raw HTML off

**Id:** 99c3acf7-2d66-4f0a-8a1c-6f97551a9d5b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the join slice)
**Revisit when:** the join page needs a construct CommonMark with tables cannot express, or markdown-it-py stops being maintained

A browser opening a join URL gets the same document as an agent,
rendered to HTML by `markdown-it-py` in CommonMark mode with tables, raw
HTML disabled, inside a fixed page with a link to the dashboard and no
script or form. Text a human typed (the project name) is escaped for
Markdown before it goes into the template.

**Reason:** the page is the one document of the hub that mixes the
operator's template, values from the join record and text people type;
it must render without letting any of them become markup. markdown-it-py
escapes raw HTML when it is disabled and refuses `javascript:` links,
and it is a small pure-Python dependency.

**Rejected alternatives:**
- A hand-written converter for the few constructs the template uses —
  no dependency, but one more parser whose escaping the hub would own.
- The Markdown inside `<pre>` — safe and trivial, but the page is meant
  for a human who opened the link in a browser, and code blocks and the
  table become unreadable.

## The join page template lives in docs/ and is shipped into the wheel

**Id:** 93300fee-e6a7-442a-a21e-db8f3f1e6f20
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the join slice)

`docs/join-page.md` stays where the CLI's author wrote it, next to the
contract it follows. The wheel carries it as `maity_hub/join-page.md`
(hatch `force-include`); a checkout without a built wheel reads it from
`docs/`, and the image's build context includes that one file.

**Reason:** the template is written against `docs/api.md` §3.2 and
reviewed with it; one copy means the page an agent reads is the page the
contract describes.

**Rejected alternative:** a copy inside the package — no build-time
step, but two files that drift the first time someone edits the one in
`docs/`.

## The join host is a path rewrite in the middleware, not a second app

**Id:** 605569db-5baa-4fdf-ae94-d730590a354a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the join host (`docs/api.md` §1.1), 2026-10-22, PR #148

A request whose `Host` is the join host is handled by `maity_hub/join_host.py`,
called from the middleware after the body cap and the credential filter:
`GET`/`POST /{token}` get their path rewritten to the public join page and
exchange (`/join/{token}`, `/api/v1/join/{token}`), with `Cookie` and
`Authorization` dropped; anything else is answered there (`302` or
`not_found`) and never reaches a route.

**Reason:** the join on the join host must be exactly the public join, the
same code, rate limit, transport rule and answer; a rewrite reuses all of
it and adds one place that decides what the join host serves at all.
Running after the middleware's own checks keeps the body cap, the
credential filter and the request log (whose mask then sees `/join/…`)
for the join host too.

**Rejected alternative:** a second FastAPI app or a Starlette host router
mounted for the join host. It would need the join routes registered twice
or factored out, and every later route added to the main app would have to
be kept off the join host deliberately; with the rewrite, nothing but the
two token paths can be reached there by construction.

## The join host is matched on the hostname alone, failing closed

**Id:** 0db8ec23-5525-4884-9df4-369fcd3973c2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of PR #148, 2026-10-22

A request is on the join host when the `Host` header's hostname, lower
case and without trailing dots, is the join URL's; the port is not
compared. `join.example.`, `join.example:80` and `join.example:0443` are the
join host too, and a malformed port does not move a request to the public
app. The log masks the first path segment of anything on the join host that
was not rewritten to the join, since `HEAD /{token}` or `/{token}/` still
carry the token. The page for a link that no longer works is answered only
on the join host; the public host keeps the envelope's `not_found`.

**Reason:** an exact `host[:port]` match let every variant fall through to
the full public app, login cookie included, which the join host must
never serve (§1.1, §2.1); a trailing-dot host is even its own browser
origin. `MAITY_JOIN_URL` must already name another hostname than the
public URL, so ignoring the port cannot capture public traffic.

**Rejected alternative:** normalising the port (default ports dropped,
leading zeros parsed) and comparing `host:port` exactly — closer to the
URL, but every form it misses fails open, onto the public app.

## Removing a member also clears reports_to on unused join links

**Id:** c5fef6d5-5f79-439b-98f3-c342591ade76
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of contract #118 (docs/api.md §6.2), 2026-10-22

The contract clears `reports_to` on every member that reported to a
removed one, "so the chain never names a former member". A join link not
yet used carries its own `reports_to`, copied into the membership at the
exchange; the removal sets it to `null` as well, without an event (a
join link has none).

**Reason:** inferred from the contract's purpose — left alone, the
exchange would create a member reporting to someone no longer in the
project, the state the rule exists to prevent.

**Rejected alternatives:**
- Leave the link and check at the exchange — the agent holding the link
  would fail for something it cannot fix; the admin who removed the boss
  is the one acting.
- Revoke the link — the join itself is still wanted, only its boss is gone.

Placements proposing a new agent keep `reports_to` inside
`new_profile`; nothing creates a membership from it yet, so it is not
touched here.
