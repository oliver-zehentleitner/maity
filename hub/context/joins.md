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

## Removing a member also clears reports_to on unused join links and new-profile placements

**Id:** c5fef6d5-5f79-439b-98f3-c342591ade76
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of contract #118 (docs/api.md §6.2), 2026-10-22; contract #187, 2026-10-23

The contract clears `reports_to` on every member that reported to a
removed one, "so the chain never names a former member". A join link not
yet used carries its own `reports_to`, copied into the membership at the
exchange; the removal sets it to `null` as well, without an event (a
join link has none).

An active placement that will create a profile keeps the same field in
its stored `new_profile`; the removal sets it to `null` too, with no event
and no `generation` bump, since the runner never reads it. The exchange
applies a link's `reports_to` only if it still names an active member,
read after the project lock, so a removal that commits between reading
the link and inserting the membership still gives `null`.

**Reason:** first inferred from the contract's purpose, then written into
it (#187): left alone, the exchange would create a member reporting to
someone no longer in the project, the state the rule exists to prevent.
The check after the lock covers what clearing cannot: a removal racing an
exchange at READ COMMITTED.

**Rejected alternatives:**
- Leave the link and refuse at the exchange — the agent holding the link
  would fail for something it cannot fix; the admin who removed the boss
  is the one acting.
- Revoke the link — the join itself is still wanted, only its boss is gone.

## Invitations are voided when they are used, listed by their own end, and the page reads registration from the effective mode

**Id:** 59c15f35-08fc-4bb9-abf6-ae0dc4ac8ea9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of contract #360 (docs/api.md §3.4, §2.7.1), 2026-10-25; review of #378, 2026-10-25

Three choices in the invitation code (`routes/invitations.py`,
`invitations.py`).

**Voided lazily.** Nothing watches an issuer's role. Whether the issuer
still holds the authority an invitation needs is computed by one
predicate (`invitations.admits`), which the page, accept and
registration all read. Only an accept writes `voided_at`, under the
project's lock, and commits it before it refuses. The contract says the
invitation is voided "at that moment" of accepting. Rejected: voiding
every open invitation of a member whose role changes, in the member
PATCH and the removal. That means more write paths to keep complete,
and a promotion back would not restore what was voided. The reads give
the same answer either way.

**Listed by their own end.** The list shows open invitations, and ended
ones (used, revoked, voided, expired) for 30 days after the timestamp of
the way they ended. The contract row was widened to name voided and
expired as well. Rejected: one window on `expires_at` for all of them.
It kept a long-revoked invitation listed until its expiry ran out, and
the timestamp of an ended one is the time an admin looks for.

**Registration on the page.** It is `sign_in_only` without complete,
enabled mail, whatever the mode. Under the effective `open` it is
`sign_in_or_register`. Otherwise it is `sign_in_or_register` only for
an address-bound invitation that admits. Rejected: the stored mode
alone. Without mail no registration can complete, so the page would
promise a way in that the hub refuses.

**Reason:** each choice keeps the three readers of an invitation (page,
accept, registration) on one predicate and one view of the instance.
The voiding moment and the widened list row are written in the contract
(confirmed). The mail condition on the page is derived from §3.4's "Mail
must be complete and enabled as for every registration" and is not
stated for the page itself (inferred).

## A join remembers whether a member made it under "Bringing your own agent"

**Id:** 2dc81770-9572-4124-b59a-0b90aabb57ca
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (tsk-ma408933n5qd); the flag agreed with the coordinator, who asked for its reason here
**Revisit when:** the exchange needs to tell more kinds of join apart than an admin's and a member's
**See:** https://github.com/oliver-zehentleitner/maity — cef4255e-ae62-4699-aa86-f4f2c36f8d55 — as of 2026-10-28

`join_link.member_rule` is true for a join a human with trust `member`
created under §3.1 "Bringing your own agent", false for every join made
through `members:admin`. The exchange (§3.3) checks the creator, the
target's limits and the count again only for a join with the flag.

**Reason:** the contract has the exchange re-check "what may have changed
since the join was issued" for a member's join, but a join row did not
record which rule issued it. Reading it back from the creator's trust at
the exchange is wrong in one direction: an admin who made a join and was
lowered to `member` before the exchange would have an admin's join
judged by a member's limits. The flag keeps the decision the creation
made.

**Rejected alternatives:**
- Infer the rule from the creator's current trust at the exchange: wrong
  for a creator whose trust changed in between, as above.
- Infer it from the join's values (trust `member`/`guest`, no areas):
  an admin's join can have the same values, so the two cannot be told apart.
