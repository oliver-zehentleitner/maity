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

## An invitation's link on the join host is answered by the join router with no lookup; its host is stored on the invitation

**Id:** 63ff4653-7a66-4c81-a178-1d5f8ce6bda0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of card tsk-nq3fjd1x6qb1 against `docs/api.md` §1.1, §3.4 (#675), 2026-10-30; the contract entry is `context/join.md` cb26f4f4
**See:** https://github.com/oliver-zehentleitner/maity — cb26f4f4-ac8a-4a65-889d-a45896810a0e — as of 2026-10-30
**Revisit when:** a second path is added to the join host, or an invitation is to be shown on the join host itself

`join_host.route` answers `GET /i/{token}` (`INVITE_PATH`, 22 characters of `[A-Za-z0-9_-]`) with
a `302` to the public `/invite/{token}` before anything else, in the same place that answers
every other join-host path, so the route is never reached and no statement is sent to the
database: a live, a used and an unknown token get the same answer by construction. The
request log masks the segment after `/i/` on the join host only (`_JOIN_INVITE` in
`middleware._logged_path`), ahead of the first-segment mask, which would otherwise print
`/…/{token}`. The invitation stores which host its link was built on (`invitation.via`,
migration 0098, `join` or `public`, default `public` for the rows that exist), because the
`GET` list is to tell the inviter which link went out and the `url` itself is not kept.

**Reason:** the contract says the join host looks nothing up and the page on the public host
keeps its one `not_found`; answering from the router that already decides what the join
host serves keeps that in one place and makes "no lookup" a property of the code, not of a
route that has to stay careful. The column is the same as `join_link.via`, for the same
reason.

**Rejected alternatives:**
- Rewriting `/i/{token}` to the public invitation page, as the agent join is rewritten: the
  page would then run on the join host, which has no session and is to set no cookie.
- Masking `/i/` with the other token patterns (`_TOKEN_PATHS`, every host): on the public
  host `/i/…` has no token to hide, and the join host's own patterns are the ones that
  apply only there.
- Deriving `via` from nothing and not listing it: the inviter could not see which link
  went out, which §3.4 asks for.

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

## An address-bound invitation is accepted by the account's verified or disabled address, never a pending one

**Id:** 310da1ed-b6ae-44bc-b6f3-bfc649186794
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** fix of the stub `invitations.account_address` (#662), docs/api.md §3.4, §18.4, §18.7, 2026-10-29
**See:** joins.md — 59c15f35-08fc-4bb9-abf6-ae0dc4ac8ea9 — as of 2026-10-29
**Revisit when:** the contract says in so many words whether a disabled address still counts as the account's address, or the accounts design adds a state of the address beyond none, pending, verified and disabled

`invitations.account_address` gives the account's `address_normalized`
when `address_status` is `verified` or `disabled`, and nothing
otherwise; accept compares it with the invitation's normalized address
(`routes/invitations.py`, `invitation_address_mismatch`).

**Reason:** §3.4 lets only the account whose verified address is the
invited one accept. A `disabled` address is still that account's
verified address: §18.7 only stops mail to it after hard failures, the
address keeps its place in the one-account-per-address constraint, and
setting and verifying it again enables it. The rest of the hub treats
`disabled` as verified too (`notifications/preferences.py`). A `pending`
address was never confirmed by its mailbox, so accepting with it would
let anyone bind an invitation to an address they only typed.
Both sides normalize with `strip().lower()` (`registration.normalized`
and `mail.address.normalized`), the comparison §2.6.3 uses.

**Rejected alternatives:** `verified` only, as e-mail sign-in and the
mailer use: those decide whether mail may go out, while accept asks
whose address it is, and a bounced mailbox would lock its owner out of
an invitation made for them. Reading `address` or `pending_address`
instead of `address_normalized`: the first is not normalized, the second
is unconfirmed.

**Workaround:** before this fix the stub returned `None`, so every
address-bound invitation refused with `invitation_address_mismatch`;
tests monkeypatched `account_address`. The monkeypatch is gone.

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

## A join's `takes_over` and `handover` are copied to the membership at the exchange as a snapshot and a pointer, never as text, and the packet drops them once the member has checked in

**Id:** fe6dfb86-42f3-4deb-a27e-f5deadc095ec
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §3.1, §5.2, §6.2, §8.1 (#896); the card tsk-k10qncwjra0q
**Verification:** corroborated
**Revisit when:** a hand-over needs more than a pointer to a card or a message, or an agent may continue the work of more than one other

`join_link.takes_over` holds the agent id the human named and `join_link.handover` the pointer `{kind, id}`, checked at creation (a first join only, an agent with an active membership of the project that is not the joining one, a card of the project or a message of it addressed to `all`). At the exchange `membership.takes_over` becomes `{member_id, handle, name}` as the profile has them then, and `membership.handover` the same pointer. The resume packet carries both only while `onboarded_at` is null, the member view always, and `member_joined` goes to the project's coordinator and to the lead of the member named as well as to `all`. `join_link.takes_over` has no foreign key.

**Reason:** the hub should tell who continues whose work and where to read the hand-over, and own nothing of the hand-over itself: the card or message is read like any other, so its readers and its history stay what they are. A snapshot of handle and name keeps the line "takes over from <handle>" true after the other member is removed or renamed, which the packet promises. A foreign key from a join to a profile would make an unused join block that profile's deletion (§6.3).

**Rejected alternatives:**
- Storing the hand-over's text on the membership: a second copy of something already readable, with its own readers to decide.
- Reading the member's handle at every packet: the line would change or vanish with the other member's removal.
- Moving the other member's cards and claims with the join: the contract leaves that to an admin or its owner (§6.19, §6.2); a join must never move work.
