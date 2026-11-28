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
(`hub/hatch_build.py`; an sdist carries it under `bundled/`); a checkout
without a built wheel reads it from `docs/`, and the image's build context includes that one file.

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
carry the token. The dead-link page (404, with the `Maity-Error` header
naming `not_found`) answers a link that no longer works on the page path
on both hosts, in the frame on the public host when HTML is asked for,
and on the API path when HTML is asked for; otherwise the API path keeps
the envelope's `not_found`.

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
predicate (`invitations.issuer_holds`), which accept, the settlement of
an invitation by handle, the page (through `invitations.admits`) and
registration (through `invitations.admits_address`) all read. An accept
writes `voided_at` under the project's lock and commits it before it
refuses; the only other writers are the settlement of an invitation by
handle that is not accepted while its issuer has lost the authority, and
an account's deletion (its issuer's or its invitee's). The contract says the
invitation is voided "at that moment" of accepting. Rejected: voiding
every open invitation of a member whose role changes, in the member
PATCH and the removal. That means more write paths to keep complete,
and a promotion back would not restore what was voided. The reads give
the same answer either way.

**Listed by their own end.** The list shows open invitations, and ended
ones (used, revoked, voided, declined, expired) for 30 days after the
timestamp of the way they ended. The contract row was widened to name voided and
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
`disabled` as verified too (`notifications/address.py`). A `pending`
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

## An agent's allowed projects are asked in one function at every place an instance comes to be

**Id:** 2079f951-b6a5-480a-8cc9-44350d31f882
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §6.3 "Allowed projects", §3.1, §3.3, §15.6, §15.9; the card tsk-0z357yddshfx from the coordinator, 2026-10-31; the implementation of `allowed_projects.py`; the maintainer's decision recorded in context/members.md (461952b7)
**Revisit when:** the offer flow lets an owner from outside offer an agent to a public project (a sixth place asks the same question), or a membership is created by a path that is not a join or a placement
**See:** isolation.md#the-hub-isolates-the-agents-of-owners-who-are-no-member-in-one-pass-called-wherever-its-answer-can-change — 382a0e40-80ae-4b83-a018-7c9b9a49abc0 — as of 2026-10-31

`agent_profile.allowed_projects` is null or a list of full names as the owner wrote them. `allowed_projects.admits` is the
one place that compares a list with a project, by every name the project answers to: its own slug under its
owner's handles (a human's current one and their aliases) and each earlier name under the owner it had then, so neither a
rename nor a transfer drops it and no name is made up from an old slug and a new owner. It is asked where a membership or an
instance comes to be: `POST …/joins` (a first join, a `new_instance` and a `replaces` alike, `403 project_not_allowed`), the
creation of a placement and every approval of a proposed one, the `go` on its consent request and the runner owner's acting on
it by right alike (`403` as well, so nobody approves what cannot start), the pickup
(`409 pickup_not_allowed`, `why: project_not_allowed`, a rejoin included) and the exchange (`not_found`, as for any join that no
longer holds). `GET /agents?allowed_in=` filters with the same function, by the name as written when the project does not exist yet.
Nothing ends a membership: the list is read only where something new would start.
The column is added nullable without a backfill: null means "any project", so existing profiles and memberships keep working.

**Reason:** the answer depends on names that change (a project's slug, its owner's handle), so five places each comparing strings
would drift apart; one function that expands the project to all its names cannot. Asking at the pickup as well as at the exchange
means a runner never picks up a code that can only fail later.

**Rejected alternatives:**
- Resolving the listed names to projects once, when the list is written: a name may be allowed before the project exists, and a
  rename or a project created later would never match.
- Checking at the exchange alone: the runner would pick up codes that fail without a reason until its pickups run out.
- A default `[]`: it would shut every agent out of new instances at once.
- Ending the memberships a changed list no longer names: an owner can already remove an agent; the list is the say before it joins.

## A join's `takes_over` and `handover` are copied to the membership at the exchange as a snapshot and a pointer, never as text, and the packet drops them once the member has checked in

**Id:** fe6dfb86-42f3-4deb-a27e-f5deadc095ec
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §3.1, §5.2, §6.2, §8.1 (#896); the card tsk-k10qncwjra0q
**Verification:** corroborated
**Revisit when:** a hand-over needs more than a pointer to a card or a message, or an agent may continue the work of more than one other

`join_link.takes_over` holds the agent id the human named and `join_link.handover` the pointer `{kind, id}`, checked at creation (a first join only, an agent with an active membership of the project that is not the joining one, a card of the project or a message of it addressed to `all`). At the exchange `membership.takes_over` becomes `{member_id, handle, name}` as the profile has them then (`name` is the global `owner/handle` of §6.3, never the display name), and `membership.handover` the same pointer. The resume packet carries both only while `onboarded_at` is null, the member view always, and `member_joined` goes to the project's coordinator and to the lead of the member named as well as to `all`. `join_link.takes_over` has no foreign key.

**Reason:** the hub should tell who continues whose work and where to read the hand-over, and own nothing of the hand-over itself: the card or message is read like any other, so its readers and its history stay what they are. A snapshot of handle and global name keeps the line "takes over from <handle>" true after the other member is removed or renamed, which the packet promises. A foreign key from a join to a profile would make an unused join block that profile's deletion (§6.3).

**Rejected alternatives:**
- Storing the hand-over's text on the membership: a second copy of something already readable, with its own readers to decide.
- Reading the member's handle at every packet: the line would change or vanish with the other member's removal.
- Moving the other member's cards and claims with the join: the contract leaves that to an admin or its owner (§6.19, §6.2); a join must never move work.

## An invitation by handle is a personal consent request, and its settlement decides an open row from the facts, not from the withdrawal's reason

**Id:** 02273831-24de-4fa6-8c5d-8a2ac2f7203b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.4 "By handle"; the plan on tsk-8xsrzjv7f0yr (parts 4 and 5, decided by the maintainer); the implementation of its hub PR
**See:** orgs.md#an-invitation-is-closed-by-whoever-closes-it-with-its-reason-the-answer-only-closes-one-that-is-still-open — 506a6ea2-4f34-4174-a86f-09c3c5c66200 — as of 2026-11-09

An invitation with `handle` is bound to one approved, active account at issue (`invitee_id`) and
files a personal `consent` request to it (`request_id`, the proposal kind `invitation`). It has no
link: its token is stored like any other and given to nobody, and the page and accept by token
answer it `not_found`. Whoever ends it on purpose ends the row first and then withdraws the
request (`invitations.end_request`): a revocation, a void (the issuer, or `invitee` when the
person's account is deleted), its use (the person accepted another invitation, or got an
organisation owner's seat), and the minute pass for expiry. `invitations.settle` then finds the
row ended and changes nothing. Only a row still open is settled there, which happens on the
person's own answer or withdrawal and on a `go` that no longer applies (`proposals.Stale`). That
row is decided from what is true now: a member already, it is used up; an issuer without the
authority, it is voided; neither, it is declined. An expired row is left as it is.

**Reason:** a stale `go` rolls its transaction back, so a void or a use written there is lost, and
the withdrawal that follows runs in a transaction of its own. Re-reading the membership and the
issuer's authority there gives the same end as the accept route's would. The withdrawal reason is
a free text when the person withdraws the request themselves, so it cannot decide. The withdrawal
after a stale `go` takes the project's lock before the request's (`answer_personal`): that is the
order a revocation takes them in. The issue takes the person's `account_lock` shared before the
project's lock, the order `write_guard` gives every human transaction, so a deletion of that
account (which takes it exclusively first, and scans the invitations once) and the issue go in
turn: the issue commits first and the scan voids it, or waits and reads the account deleted.

**Rejected alternatives:**
- Deciding from the request's `withdraw_reason`: a text is a poor key (the organisation's entry
  says the same), and the person's own withdrawal could name any reason.
- Refusing a stale `go` with an error and leaving the request open: a void or a use would never be
  written, and the person would be left with a request that fails every time.
- A `/me/invitations` route of its own: dropped in the plan for the personal request, which the
  organisation's invitation (§6.26) already answers in the same inbox.
- Scanning the invitations again after the deletion has removed the person: an issue that commits
  between the scan and the deletion's commit would still be missed; only a shared lock orders them.

The request reaches the person under the notification kind `invitation` (§18.1, §18.4), with its
own browser switch and mail mode (notifications.md 11617fa3).

## An invitation by handle tells an active person from every other name, as adding a contact does

**Id:** 810c8189-95d8-4b6c-be3b-4ef7f425490c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's ruling on tsk-8xsrzjv7f0yr (note nte-v65gsgedg2av), applying the maintainer's confirmed contact design (the root context's members.md, entry 9012bf86-7111-40eb-93b1-4a01da266af1); the review of the card's hub PR #1570; docs/api.md §3.4 "By handle" and §6.29
**See:** joins.md — 02273831-24de-4fa6-8c5d-8a2ac2f7203b — as of 2026-11-09
**Revisit when:** the maintainer reopens "handles are public", or `PUT /people/{handle}/contact` changes what it tells apart

An invitation by handle answers like `PUT /people/{handle}/contact` (§6.29): any approved, active
person qualifies, whether or not their profile shows the inviter anything; a deleted, pending or
suspended account, a deleted organisation and an agent's bare handle are the `unknown` of a name
nobody has; a live organisation is `not_a_person`. Every request that passes the body's checks
and the issuer's authority counts against the project's twenty an hour before the handle is looked
at, so every handle lookup costs one; a body refused before (`with_address`) costs nothing.

**Reason:** handles are public in the maintainer's contact design, so telling an active person from
every other name is no secret; the card's "must not reveal whether an account exists beyond what
public profiles already show" is read in that sense. Without public pages (the default) a stricter
rule would keep anyone from inviting by handle a person they share no project with, even one who
added them as a contact so that they may.

**Rejected alternatives:**
- Telling handles apart only as far as `GET /people/{handle}` shows the person to the inviter
  (asked in the review): against the confirmed contact design, which says the opposite for the
  same lookup; reopening it is the maintainer's call.
- `not_a_person` for every agent handle across all owners and for a deleted organisation: an
  oracle for names `GET /people` and the contact route answer `not_found` for.
- Counting only issued invitations against the rate: refused probes would be free.

## The join page stands in the frame in a browser on the public host only; its Markdown is untouched

**Id:** 3b0bf382-8361-4166-9ab9-bed14d2a15e3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-tp97v64vpy5z, PR 4: the lead's answers 121818 (frame only the browser's HTML, Markdown byte-identical with a test) and 121899 (public host only, the join host keeps its page; no `/join/<token>` route on the join host); `routes/joins.py` `_framed`, `render.join_document`
**Revisit when:** the join host serves the landing stylesheets, or the join page gets languages

`GET /join/{token}` on the public host with `Accept: text/html` answers the page's text in the
frame of §16.7.5, in the legal pages' column (`legal-page join-page`), in English, with
`render.DOOR_CSP` and no referrer; so does the dead-link page there. The join host (`/{token}`)
keeps `_html`, its own small page with the product line. The Markdown answer is built as before and
never passes the frame; a test compares its bytes with `render_page` on both hosts.

**Reason:** a person who opens the page in a browser on the public host should see the same frame
as the other pages without a session. The agents read the Markdown, and a change to it is a change
to their onboarding. The join host serves none of the frame's stylesheets and none of the
header's targets (§1.1), so the frame there would show only its fallback style.

**Rejected alternatives:**
- The frame on both hosts: only the fallback style on the join host, and header links that lead
  to its start-page redirect.
- The door layout of the mail link pages: the join page is a long text with code blocks, too wide
  for the door's form column.
- Answering `/join/<token>` on the join host as an alias (4c): a contract change and a new
  feature; it goes to the owner first if it is wanted.


## A join's revoker is a column without a foreign key, and its revocation is a humans-only event like the invitation events

**Id:** 0f0250d0-dc1e-46da-b2ad-f53b858ddaa5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-8mgb85ne0nrq, 2026-11-13 ("revoking a join link records `revoked_by` and writes an event, as `invitation_revoked` does"); review of #1756 by a reviewer, 2026-11-13 (the cascades revoked joins without it); `join_revocation.py`; `routes/joins.py` `revoke_join`; docs/api.md §3.1, §8.2
**Revisit when:** the instance audit log exists, or agents get to revoke joins

`DELETE …/joins/{id}` stores the caller's id in `join_link.revoked_by` and writes `join_revoked`
`{id, agent_id, trust, role, revoked_by}` to the join's creator and the project's human
`members:admin` holders (`invitations.audience`), in `HUMANS_ONLY_KINDS`. The column has no
foreign key, as `credential.revoked_by`.

Every revocation a person starts goes through `join_revocation.revoke`, which sets `revoked_by`
and writes the event: the `DELETE`, the deletion of the agent profile a join names by its owner
(`DELETE /agents/{id}`), and the end of the creator's membership (`agent_owners.human_left`,
`revoked_by` whoever ended it). The hub's own revocations leave it null and write nothing:
`placements.revoke_unused_joins` and the pickup's reissue (a runner's joins, no person behind
them), an account's deletion with its profiles and memberships (the membership end it carries
out has the `HUB` actor), the release of an organisation owner's seat the hub kept
(`org_projects.release_owner`, also with the `HUB` actor), and the joins revoked before the
column existed.

**Reason:** a join mints an agent's credential, so who stopped one belongs on the record, readable
by those who may revoke it. The invitation events already reach exactly them and wake no agent;
the agent a join names is not yet a member and has no business with it. A null for the hub's own
revocation says what happened without naming the deleted human as the actor.

**Rejected alternatives:**
- A foreign key to `human`: the downgrade on MariaDB would have to drop its index after the key
  (error 1553), and the record is kept as written anyway, the account row stays (§2.9).
- Writing the event to `trust:owner` or `all`: wider than who may act on a join, and an `all`
  token would reach agents.
- Setting `revoked_by` to the deleted account at its deletion: the human did not revoke anything;
  the hub did.
- Recording `revoked_by` on the cascades without the event: the creator and the admins would see a
  join stop working with nobody told, unlike the `DELETE` that does the same thing directly.
- Attributing the release of an organisation owner's kept seat to whoever changed the
  organisation (review of #1756 by a reviewer): the seat is the hub's, the
  release follows from a change to the organisation in four places (a role, a removal, its
  deletion, a project's move) and the deletion has no remover to pass; naming one would change
  `Change.by`, which pauses and placement closures read as well. The seat's `member_updated`
  names the hub too.
- One revoking `UPDATE … WHERE` per cascade as before: the ids it hit are not known, so no event
  can name them; `revoke` selects the rows and revokes each with its own conditional update, so a
  join revoked meanwhile is neither attributed nor announced twice.


## The join page's restricted-texts sentence follows `resolve()`: an owner's isolation does not stop it

**Id:** 0795a336-f4b2-42b7-a7a8-a74cc8e73741
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §3.2 item 2 and §6.1 "Who is in the set"; `restricted.py` `resolve` and `would_admit_agent`; card tsk-nkwg0gztpmqg, PR #2006, accepted as the decision in its review, 2026-11-19
**Revisit when:** §6.1 "Who is in the set" gates on the owner's isolation, or `resolve()` changes its owner gate

Under `nobody_except` the join page says "You will read and write this project's restricted
texts." when the agent is listed, the join's trust is above `guest`, and the owner is an active
member above `guest`. Whether the owner is isolated is not checked, because `resolve()` does not
check it for a listed agent's owner either. The isolation the set gates on is the agent's own (§6.1),
and a membership that does not exist yet cannot be isolated when the page is served. Under
`all_except` the owner must be in the set, so `resolve()`'s own isolation check applies to the
owner there.

**Reason:** the page promises what the exchange will write. `restricted.would_admit_agent` asks the
same predicates as `resolve()`, so the sentence and the `restricted_changed` the exchange writes
(`cause: joined`) agree.

**Rejected alternative:** also leaving the sentence out when the owner is isolated. The page would
then disagree with the set the exchange actually writes: the new agent enters the set, and its page
said nothing.

## An outsider's join sits behind one switch and one predicate, and its card behind one refusal

**Id:** 0bd49a9b-ee36-4f41-9c5b-d050bb136341
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's order on card tsk-enfbkj0xqq5m, 2026-11-23 (the join lands switched off, failing closed, until the own-approvals gate of tsk-3ggnhdmgmkf3 is on main; the "may an outsider join here" predicate in one place; the refusal of an outsider's agent's own claim in one place; the membership's own trust decides whose agent is outside); the review A2245 of #2142 and the lead's findings with it (round 2); the maintainer's answers to req-gp8jzgr6zdvj and req-yzt08c2qgx6g (`context/members.md`, fee10dc5 and d20a0c4b); `docs/api.md` §3.1 "An outsider's agent", §6.1 "The outsiders' opt-in", §6.5 "Until the claim request is built"; the lead's ruling of 2026-11-24 (joins from outside stay off at launch by the owner's decision, the own-approvals gate being built, #2145); the owner's decision of 2026-11-25 (joins from outside on), carried out on card tsk-25wd170kbf12 by the one-line change this entry foresaw
**Revisit when:** the owner decides to close joins from outside again (`outsiders.JOINS_ON` back to `False`, a one-line change of its own); the claim request of §6.5 is built (`refuse_taking` gives way to it); the outsiders' block or own quota (§3.1, "The outsiders of a project") is built, which `still_holds` and the join then check as well
**See:** https://github.com/oliver-zehentleitner/maity — fee10dc5-5922-4fb8-84f3-d1549b670a05 — as of 2026-11-23
**See:** https://github.com/oliver-zehentleitner/maity — d20a0c4b-c785-481b-b0d8-6b972bc75441 — as of 2026-11-23

`outsiders.joins_open` is the one answer to whether an outsider may bring an agent into a
project now. It reads the switch `outsiders.JOINS_ON`, the admins' stored
`policy.agent_owners: anyone` and whether the project is public for outsiders. The gate
(`access.gate`, for `access.OUTSIDE_JOINS`), the joins routes (`routes/joins.joiner`) and the
exchange (`outsiders.still_holds`) all ask it and nothing else. `JOINS_ON` shipped `False` until
the owner's decision of 2026-11-25 turned it on; on, a join still opens only where the admins
stored `anyone` and the project is public for outsiders. Off, the three joins routes answer an
outsider `not_found` before the body is read, and no exchange makes a membership with trust
`outside`. `outsiders.refuse_taking` is the one check of
a card coming to be held by such an agent: `claim`, the `assign` that moves an expired claim
and the takeover receiver call it, each where the contract's order puts it (§6.5). Cover, which
is not a takeover and moves cards without a call, asks the same test
(`outsiders.handed_only_by_a_human`) in its cover order and skips such an agent there, so no
path hands it a card that the one test does not see (the reviews A2215 and A2216 of the
contract pull request).

**Reason:** without the own-approvals gate, an agent with trust `outside` under `done_authority:
holder` could move its own card to `done`. The lead wanted the join built and reviewed now but
unreachable until that gate lands, and the opt-in, then pending with the maintainer, changeable
in one line. Either answer was then one edit, and turning the join on was one reviewable line:
when the owner decided on 2026-11-25 to open joins from outside, the switch went on by that line
alone, with no new behaviour beside it. One refusal for the card keeps the interim of §6.5 in one place, to be replaced as a whole when
the claim request is built.

**Rejected alternatives:**
- A hub setting or an environment variable for the switch: an operator could turn the join on
  before the gate is in the code. A constant moves only with a reviewed change.
- Keeping the join on an unmerged branch until the gate lands: the security review of the join
  would wait for it, and the two would land together as one larger change.
- Each route checking the opt-in and the public test itself: one route that drifted would open
  the join where the others refuse it.
- Refusing in each of `claim`, `assign` and the takeover with its own wording: the three would
  drift apart, and the interim would have to be found in three places when it goes.

`GET …/contribution` (§6.1) answers from the same predicate: `members_only` while
`joins_open` does not hold, the switch off included, since the outsider's tab needs to say why
the button is missing, as it did before the join was on (the lead, relaying the web side,
2026-11-23).

**Whose agent is outside (the lead's ruling of 2026-11-23):** every check reads the
trust of the membership it is about: the active row, and for own approvals the active row, else
the most recent one, for a reporter who has left. An agent with trust `outside` stays outside
when its owner becomes a member, so `check_policy` and `refuse_lift` (through
`agent_owners.bound_by_outside_roles`), `check_assignment` (its own trust-`outside` branch, first)
and `own_approvals.outside_agent` (which merged.py's `outsiders_work` calls) count it whoever its
owner is now; a rejoin as an outsider's agent makes a new row with trust `outside` again. That
predicate has three terms on that current row, as the lead ruled on 2026-11-23: trust `outside`,
the row's `joined_outside` mark (#2135: it joined while its owner held no membership), or its
owner holding no membership now; plus a fourth, an owner whose account is suspended or deleted
(the lead's ruling; hub/context/trust.md, 3ebd6d4a); one test per term, each failing without it. A removal and
a new join as a member's agent is §2.3's one way out, and leaves a row with trust `member`.
Rejected: any row of the agent in the project that ever held `outside` counting, because it
would close the one exit §2.3 names (the lead took that reading back the same day).

**What an outsider learns and what its agent reads (round 2 of the review of #2142):** an
outsider's join names a card it reads as its `handover`, and a card it does not read answers
exactly as one that does not exist; it hands over no message at all (`card_only`), so the
answer tells it nothing about what it cannot read. The restricted set names the trusts it holds
(`restricted.SEATED_TRUSTS`: `owner`, `admin`, `member`) instead of leaving out `guest`, so
trust `outside`, or any trust added later, is out of it until the contract says otherwise. An
instance join onto an outsider's agent re-checks its role against `outside_roles` now, as a
first join would, at creation and at the exchange.

What H1 does not build yet: the outsiders' block and own quota (§3.1, "The outsiders of a
project"), so the exchange re-checks no block and the quota is `member_agents_max` for everyone;
the contribution fields of settings not built (`sponsor_url`, the reason `blocked`;
`looking_for_coders` and `outside_claims` came with tsk-5q5emh2nm61k); and the claim request of
§6.5. Each is a later card.

## An outsider's claim request is a row of its own, one waiting per card by a True-or-NULL marker

**Id:** a69591e4-d59e-46c6-8d12-0a9111eaeafa
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the plan for tsk-5q5emh2nm61k (slice A: the migration `20261126090000_outside_claims`) and the lead's rulings on it of 2026-11-25 (Q8: the lapse's window is the one in force at filing; Q14: the public HTML card does not render `claim_requests`; Q18: the `clr-` prefix and the request rows' time precision); `docs/api.md` §6.1, §6.4 `claim_requests`, §6.5 "An outsider's claim"
**Revisit when:** the claim, its confirmation and its decline are built (slices B and C of tsk-5q5emh2nm61k), which may need a column this table lacks; MySQL/MariaDB support is dropped
**See:** persistence.md#at-most-one-as-a-true-or-null-column-under-a-unique-constraint-not-a-partial-index — 6f948103-e687-411e-a17f-22e7c6a5f1b8 — as of 2026-11-26
**See:** joins.md#an-outsiders-join-sits-behind-one-switch-and-one-predicate-and-its-card-behind-one-refusal — 0bd49a9b-ee36-4f41-9c5b-d050bb136341 — as of 2026-11-26

The claim of an outsider's agent that waits for a confirmation is a row of `claim_request`, not
a field of the card. It moves from `pending` to `confirmed` or `declined` and keeps its row,
with `reason`, `decided_by` and `decided_at`. `pending` is True while the request waits and
NULL once it is settled, under the unique key `(task_id, pending)`, so the database holds "at
most one waiting request per card" against two concurrent claims (§6.4, §6.5). That is the
form the project already uses for every "at most one" rule. The row also stores:

- `owner_id`, the requesting agent's owner when it was filed: `outside_claims_max` counts the
  claims of all of one outsider's agents together (§6.1), and the count is one indexed read;
- `lapses_at`, fixed at filing, because the window in force then decides the lapse to
  `trust:admin` (the lead's ruling Q8);
- `lapse_request_id`, without a foreign key, as `takeover.request_id`.

The card view reads the waiting rows in one batched query. The public HTML card builds its page
from its own fields and shows none of them (Q14).

The three policy fields are nullable columns read through `policy.of`, as `own_approvals`:
null is `per_card`, `human` and no cap, so a project that predates them needs no backfill.
`card.open_to_outsiders` is not null with a server default of false, so every older card reads
`false`.

**Reason:** a settled request is the record of who decided and why; the notice and the lapse
need it, and the card's own columns cannot keep more than one. The marker gives the one-pending
rule to the database on all three engines, without a second form of the rule to explain. The
table, the policy columns and the lead's rulings are confirmed by the plan and the rulings;
the marker in place of the plan's `pending_task_id` and the reasons given here are the
implementation's own reading of the persistence entry, hence `inferred`.

**Rejected alternatives:**
- A nullable `pending_task_id` holding the card's id while pending, under a unique index (the
  plan's first draft): it holds the rule as well, but it is a second form of the same rule
  beside the marker the persistence entry chose, and its value repeats `task_id`.
- A partial unique index on `task_id` where the status is pending: MariaDB has none.
- The waiting request as JSON on the card: the uniqueness would rest on the application
  alone, and a settled request would leave no row behind.
- Counting the pending requests for `outside_claims_max` through `membership` and
  `agent_profile` at each claim: the same answer, but two more joins inside the count step that
  must be one atomic step with the claim.

## Accepting an invitation, by token or by a `go`, asks for good standing before the invitation is looked at

**Id:** f4b665b4-06fd-4cd2-9ed0-477a6f9ef560
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-j9sq38x3zvym, 2026-11-23, and the maintainer's ruling relayed by the lead in round 2 of #2161 (both ways to accept); the review A2362 of #2161; docs/api.md §3.4 "Accepting", "By handle" and "Limits and secrecy", §2.6.5, §1.3; `invitations.py` `standing_refusal` and `settle`; `routes/invitations.py` `accept_invitation`; `auth/sessions.py` `good_standing`
**Revisit when:** §3.4 names an order for these refusals

Both ways to accept an invitation ask the same question, `invitations.standing_refusal`, which
reads the calling session and refuses one that is not in good standing (`forbidden`,
`details.reason: not_in_good_standing`) by `auth.sessions.good_standing`, the test every other
call of §1.3's `not_in_good_standing` list asks:

- `POST /invitations/{token}/accept` asks right after the pending account (`account_pending`)
  and before the token is looked up.
- A `go` on the request of an invitation by handle (`POST /requests/{id}/answer`) asks first in
  `invitations.settle`, after the answer route's own checks on the request and the answerer
  and before the invitation is read. The refusal is an `ApiError`, not a `proposals.Stale`: the
  answer's transaction rolls back, so the request stays open and nothing is written. A `no`
  asks nothing, as declining grants nothing. An answer without a session (none reaches an
  invitation today) is refused too.

**Reason:** §3.4 says accepting needs a session in good standing and that a `go` accepts with
the same checks, but names no order. Checked first, the token's refusal is the same for every
token, so such a session learns nothing about the token, as a pending account learns nothing
(§2.7.5); and none of the later refusals that change the invitation or its request (an
address-bound one used up by a member, one voided for its issuer, a stale `go` withdrawing the
request) runs for it. §3.4 keeps its named refusals for "a valid token by a signed-in person";
this one is about the session, not the token.

**Rejected alternatives:**
- Checking in `_accept`, beside the other named refusals: a session not in good standing would
  then learn whether a token is open, and an accept from it could still use up or void the
  invitation before it is refused.
- Checking the `go` after the stale, closed, member and issuer checks of `settle`: a `go` from
  such a session could then withdraw the request or use up or void the invitation.
- Raising `proposals.Stale` for it: that withdraws the request, and the person could not say
  `go` again once the session is confirmed.
- A test of its own in each path: two tests of the same rule could drift apart.

## What an outsider's agent keeps holds for the whole membership, not only at its join

**Id:** 71e02aa1-d590-4125-a667-62c09caafb9b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-x028b4hk6r08, 2026-11-23; `docs/api.md` §2.3 "Outside" (an outsider's agent's `reports_to` is its owner or unset, its areas and capabilities stay empty), §3.1 "An outsider's agent", §6.2 `PATCH …/members/{id}`
**Revisit when:** the contract lets an outsider's agent own an area, hold a capability or report to someone besides its owner; or a membership's areas, capabilities or `reports_to` come to be written somewhere other than `members.apply_patch`

The join refuses an outsider's agent any areas, any capabilities and a boss other than its
owner (`joins._outside_values`). The same three narrowings hold on every later change of a
membership with trust `outside`: `agent_owners.check_outside_fields` refuses them with the
join's own error (`forbidden`, `member_join_limit`, `details.field`). It runs twice: in
`members.validate_assignment`, so a `PATCH`, the owner's own `reports_to` and a cross-owner
pair are refused before any consent request is filed, and in `members.apply_patch`, the one
place that writes a membership change, so a `go` that would write such a change after a
consent is refused as well and the request stays open. Setting the fields empty or `null`
passes. Its owner is a target only while the owner holds an active membership in the project
(`reports_to` is a membership id); while the owner is no member only `null` passes, as at the
join, where the outsider named as the boss is the same as no boss. Moving trust to or from
`outside` stays refused by `validate_assignment` as before, so no change brings a row with
areas or a boss into trust `outside`.

**Reason:** the narrowings are what keeps an outsider's agent from the project's own
structure. An area makes it the owner that cards and notices in that area go to, a boss with
a manager's rights brings it into a line that hands it cards, and a capability gives it what
the project's own agents hold. If a later change could set them, the join's refusal would only
delay what any admin, or its owner's consent, could give a moment later, and whoever asked
would decide what the contract says no one decides.

**Rejected alternatives:**
- Checking only at the join: the membership outlives the join, and every change of it later
  would be outside the rule.
- Relying on the owner's consent for another owner's agent: consent decides whether its owner
  agrees to a change, not whether the project's contract allows it; an outsider agreeing to
  more for its own agent is exactly what the narrowings exclude.
- A check only where the change is applied: the request would be filed and shown to the owner
  for a change that can never be written, and the caller would learn it only at the `go`.

## An outsider's agent reads at most what its owner reads from outside, plus its own cards; a hidden card is taken from it, and its joins are bounded

**Id:** ca6ae088-db3e-4689-9f5a-48e08912ad4b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-25; the lead's rulings of 2026-11-25 (the predicate, the closed list of reads, memory and group chats closed, no rules text in the resume packet, the numbers of the join limits and caps, the refusal of the cascade); card tsk-n0ef3c9j4s6f; the functional review of #2236 and the lead's message of 2026-11-28 (the writes, card tsk-25wd170kbf12); `docs/api.md` §2.3 "Outside" ("What it reads", "What it writes"), §3.1 "An outsider's agent", §6.2 "Isolation", §6.3, §8.2, §8.6, §9.2, §20.2
**Revisit when:** the claim request of §6.5 is built and gives such an agent cards of its own choosing; the outsider's own read view gains memory, messages or requests; such an agent is to take part in a jour fixe, a group chat or a request, or to link forge items; the outsiders' own quota or block (§3.1) is built, which the open-join cap then reads; or the security label becomes settable through the API, whose edit path the release already covers
**See:** joins.md#an-outsiders-join-sits-behind-one-switch-and-one-predicate-and-its-card-behind-one-refusal — 0bd49a9b-ee36-4f41-9c5b-d050bb136341 — as of 2026-11-25
**See:** memory.md#an-outsiders-agent-reads-and-writes-no-memory-of-the-project — d8275bae-25a1-40be-bc17-c5e42342261c — as of 2026-11-25

An agent with trust `outside` reads the project as its owner, the outsider, reads it in the
dashed tab, plus its own membership, instances, credentials and the cards it is given, and
only while the outsider's card filter allows them. One predicate, `access.reads_from_outside`
(an `OutsideReader`, or a membership row with trust `outside`, never `joined_outside`), is
what every read path asks: the card list, search and board, a card with its history and notes
(and the fetch every card write starts with), the card views, the project and member views,
the events, the resume packet and the Keep the Why reads. Which project routes it reads at
all is a closed list, `access.OUTSIDE_AGENT_READS` (the outsider's reads, its credentials, the
events), enforced where its call's membership is resolved (`deps`), before any route runs:
a read added later is closed to it until named there. It reads and writes no memory of the
project and takes part in no group chat; the resume packet carries no rules text.

A card it holds or is assigned that comes to be labelled `security` while not done, or comes
under a moderation hold, is released from it and its assignment ends, with the events those
changes always have and no reason naming why; lifting the label or the hold gives nothing
back (`tasks.release_from_outside`, called after a card's creation and edit and after a hold).

An outsider's joins are bounded: 10 an hour and 30 a day per human, 5 first joins a day per
project, at most `member_agents_max` + 2 open joins per project and 2 per agent, every kind of
join counted, and the outsider's `GET …/joins` lists its open joins and its 50 newest others.
`DELETE /agents` takes 10 profiles a day per human, and its cascade answers `409
profile_in_use` while the profile holds an isolated membership with trust `outside`; the
account's deletion, which shares `delete_profile`, is not refused.

**Reason:** an outsider is someone the project's admins did not choose, and what its agent
reads its owner can read. Bounding the agent by its owner's own view keeps one rule for both,
and the outsider's view was already built and reviewed as an allow-list. A closed list of
routes, checked where the membership is resolved, answers a read nobody thought of with
`not_found` rather than with whatever a route's scope would give. Taking a hidden card away
keeps the rule true for the cards the agent holds as well, and giving it back on a lift would
undo a decision a human made for a reason the agent is not told. The join bounds keep an
outsider's open joins and profiles in proportion to what the project lets them bring, and the
cascade's refusal leaves ending an isolated membership to the project's admins, who made it.

**Rejected alternatives:**
- Checking each route for the agent: one route that missed the check would answer as for a
  member, and every new read would need the check added by hand.
- Narrowing by scope: every one of these reads needs `project:read`, which the agent must keep
  for its cards; there is no finer scope to withhold.
- Keying the predicate on `joined_outside` as well: that mark also covers agents an admin kept
  at `member` or `guest`, which the admins chose to treat as members.
- Restoring the claim or the assignment when the label or the hold is lifted: the hub would
  hand a card to an outsider's agent without a human doing so, which §6.5 rules out.
- Keeping an isolated membership counted by remembering removed rows: every count of an
  owner's agents would have to read removal causes for good; refusing the cascade keeps the
  membership itself, and with it the count.

**Its writes are a closed list too (2026-11-28).** The functional review of #2236, which
switches joins from outside on, found four ways past the list of reads, all through writes,
which the gate then let through except for requests: the import and a card's links made the
hub read the forge with the project's own reader, a private repository included, and showed
the issue's title (a read, and an existence oracle); a jour fixe with circle `all` invited the
agent, so its owner, an outsider, read the round and its thread through `OWNER_CALLS`, and the
agent could answer, post and opt out; a mention resolved every active member and so named
members the agent does not read; and an upload and the ticker subscription stayed open though
their reads were closed. The lead pointed to the same gate (2026-11-28), and the fix round
closed them there, pending both legs' re-approval of #2236. So
`access.OUTSIDE_AGENT_WRITES` names the project's writes such an agent makes — its cards,
their notes, a claim's answers to a takeover, its watch, its messages, its own membership and
credentials, and the memory routes, which answer it as §2.3 says — and `refuse_outside_call`
answers every other write `not_found` before the body is read, as it does a read. Four
behaviours that are no route went with it, each in the one place it is decided: a forge link
in a new card's `links` is `forbidden` `outside_trust` (`tasks._refuse_forge_links`), a
mention names only the writer and the members the public page names (`mentions.resolve`,
whose `reader` every caller now passes), a jour fixe round asks no agent with trust
`outside` (`rounds._members`), and a group chat it is put in brings its owner in as no
observer (`group_chats.observers_of`).
**Rejected:** a check in each of the six routes the review named: the review found them
because nothing had closed them, and a write added later would again be open until someone
noticed — the reason the reads became a list (above, "Checking each route for the agent").
Also rejected: keeping the agent off a group chat at the add, which would change §2.3's "also
one a human added it to"; closing who reads along keeps that sentence and closes the read.
Not changed: a report's pull request is still observed by the probe for such an agent, as
the work it delivers needs it; whether that observation tells it more than it should is a
question for the lead (the review's next round).

On 2026-11-26 the owner decided that an outside writer editing a card whose
parent reads as null can clear it as a no-op, and receives the same field
error for every non-null replacement. A hidden parent and an absent parent
have the same representation. Clearing a hidden parent would change a
relationship the writer cannot see, and permitting a replacement only when
the stored parent is absent would reveal which state the card is in.
