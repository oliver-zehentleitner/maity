# Trust and role

## A proxy keeps the single role's scopes until the owner's go per call is in place

**Id:** 75d1458d-83a0-46b4-b478-f95be80d0453
**Type:** decision
**Status:** superseded
**Superseded by:** 0f3b8a52-6c1e-4d7a-9b24-7e1c5d90a3f6
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (trust × role, first of the stacked pull requests for #419; the split agreed with the coordinator)

`scopes.py` gives a member with the role `proxy` the coder's scopes and
`requests:answer`, whatever its trust, and nothing else of the governance
scopes, until the hub checks the owner's go per call (`Maity-On-Request`,
docs/api.md §2.3 "The proxy").

**Reason:** the migration turns every old `proxy` into trust `admin`, role
`proxy`. Read literally, trust `admin` adds every governance scope, so a
proxy would gain `tasks:admin`, `agents:propose` and the rest on the day
the model lands, before the rule that binds each such call to the owner's
decision exists. maity.team runs on real data; a proxy must not hold more
than it held under the single role while the guard is missing.

**Rejected alternatives:**
- Grant the full trust `admin` scopes now and add the guard later: the
  contract's order, but for the time in between a proxy acts as an admin
  without the owner's go.
- Land trust × role and the proxy go in one pull request: one change of
  roughly fifty files plus the signed header and the action binding,
  too large to review as one piece.

## A request's `to_role` holds the whole token

**Id:** e4aab1dd-1c04-420e-aa09-59760ef88bc9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-28 (migration 0067)
**Revisit when:** a request needs to address something that is neither a member, the owner, a trust nor a role

A request filed `to: trust:admin` or `to: role:designer` is stored with
`to_kind: role` and `to_role` holding the token itself (`trust:admin`,
`role:designer`); migration 0067 rewrote the bare old values (`admin` →
`trust:admin`, `owner` → `trust:owner`, `member` → `role:coder`, the rest
`role:<role>`).

**Reason:** the addressee is compared with the tokens a membership answers
to (`scopes.tokens_of`) everywhere else (event audiences, onboarding,
messages); storing the token lets requests use the same comparison, and
`String(16)` holds the longest token.

**Rejected alternatives:**
- A new `to_kind: trust` with the bare trust in `to_role`: the table's
  `to_shape` check constraint names every `to_kind`, so the migration
  would rebuild that constraint on SQLite, PostgreSQL and MariaDB for a
  distinction the token already carries.

## The 0067 downgrade removes a guest instead of making it a member

**Id:** 3de05927-0c2d-4452-af37-14477aa945e3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the first trust × role pull request, 2026-10-28 (the reviewer's decision, relayed by the coordinator)
**Revisit when:** the single role is gone for good and no downgrade below 0067 is supported

Downgrading below migration 0067 removes every guest membership, revokes
its credentials and closes its placements, and ends unused guest
invitations and joins. The single role has no trust below `member`, so a
guest cannot be mapped to anything it held.

**Reason:** a downgrade that turned a guest into `member` would hand a
read-only member the coder's scopes, a quiet escalation on the way back.
Losing the guest is the safer failure, and an admin can re-invite them.

**Rejected alternatives:**
- Map `guest` to `member`: the first version of 0067, rejected in review
  as fail-open.

## Every built-in role is one entry of `scopes`, and a security team counts as the role it is built on

**Id:** 6624a4bf-0aca-4338-b8fb-d12639ab7474
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §2.3 ("The security teams", the table of roles) and the coordinator's order on the card tsk-g62vwd7bqztk
**Revisit when:** a built-in role gets scopes no existing one has

`scopes._ROLE_SCOPES` holds the twelve built-in roles with their scopes, `red-team` with the tester's,
`blue-team` with the coder's and `purple-team` with the reviewer's. `ROLES`, `WORK_ROLES`,
`MEMBER_RULE_ROLES` and `SENSITIVE_ROLES` are derived from it, and the role of an invitation is checked
against `ROLES`, so a new role cannot be added to one list and forgotten in another (the invitation list had
no `writer` and the join list no security team). `cards.NEEDS`, the built-in roles a card may be for, is
derived too: `ROLES` without `proxy`, `manager` and `expert`, which §6.4 leaves out. Where the hub resolves a built-in role by name (the
audience of a merge that wakes the done authority, the members whose change waits for a human's go),
`scopes.counts_as` gives the role whose scopes a security team has; `cover.cover_order` resolves a
`role:<role>` entry in `substitutes` the same way, so that a substitute is found among the holders of a
role as the done authority and the wakes find them, while `role:<team>` names only the team itself. The
project roles (§2.3) came later and count as their base through `role_base`, not `counts_as` (entry
25a99503). The audience of the events that
wake the holders of a role (`task_merged`, `task_reported`) is built with `scopes.role_tokens`, which adds
the teams' tokens (`role:reviewer` and `role:purple-team`): the audience is what lets a member read the event
at all, so widening only the check of who holds the done authority would leave the purple team blind to it.
A `role:` token in an address a person writes is not widened, so a request or a message to `role:reviewer`
does not reach the purple team.

**Reason:** the contract names the roles in a dozen places and each of them had its own list, which is how
the three roles and `writer` went missing from some.

**Rejected alternatives:**
- A `Literal` per model, kept in step by hand: that is the state that lost `writer`.
- Widening the `role:` tokens too, so that `role:reviewer` also reaches the purple team: the contract keeps
  addresses exact, and a request meant for a reviewer would reach a role that only counts as one for scopes.

## A membership keeps its role's base, and an unknown role has no scopes

**Id:** 25a99503-c0df-436b-a0b2-7b1d0b1a966f
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** `docs/api.md` §2.3 "Project roles"; the coordinator's go on the card tsk-chvx53e55hmg
**Revisit when:** a card's `needs`, the role memory store or `membership.guide` in the packet is built

A project's own roles live in `project.roles` (`[{name, base, description, guide, guide_by}]`, null for
none), and every membership carries `role_base` next to `role`: the role itself for a built-in one, the
base for a project role. Scopes (`has_scope`, `listed_scopes`) are always asked with `role_base`, and
`scopes.tokens_of` gives a membership both `role:<role>` and `role:<base>`, so a request, a wake or an
audience naming `role:reviewer` reaches a project role on `reviewer` with no change where it is resolved;
a security team stays its own base and is not widened (entry 6624a4bf). The done authority's wake takes
`counts_as(role_base)`, and `cover.cover_order` matches `role:<role>` against the role or what its base
counts as. A `PUT …/roles` that moves a role to another base rewrites the `role_base` of its members in
the same transaction. `scopes._granted` raises for a name that is not a built-in role: before, any
unknown role silently got the coder's scopes, which would have given a project role on `reviewer` too
little and hidden every caller that forgot the base.

`role_in_use` counts what exists in the hub today: an active membership, an open join or invitation, an
open request to `role:<name>`, a placement that has not made its membership yet, the onboarding's
`check_in_with`, an entry in a `substitutes` list. An assignment or invitation of a project role reads
the role list under the project's lock, the lock `PUT …/roles` holds while it checks these, so a role
cannot be removed between the check of a new join and its insert (a join exchanged later would
otherwise meet a role with no base). A card's `needs`, the role memory store
and `membership.guide` in the packet are in the contract but not built; the pull request that builds one
adds it to `project_roles.uses` (and, for the guide, takes it from `project.roles` as the rules text
does). The 0112 downgrade turns a project role into its base in memberships, joins, invitations and a
placement's profile, so
the older code meets no name it does not know.

**Reason:** about 25 places read a member's scopes or tokens from a membership row, most without the
project at hand; the base on the row lets each of them stay a one-line read.

**Rejected alternatives:**
- Looking the base up in `project.roles` at every read: each of those places would need the project, and
  one that forgot it would fall back to a wrong answer without an error.
- A nullable `role_base` read as `role_base or role`: the same silent fallback in another place.
- Keeping the coder fallback in `_granted` for names it does not know: it is what made a missing base
  invisible.

## The owner's go opens a scope per call, and the proxy's listed scopes stay without it

**Id:** 0f3b8a52-6c1e-4d7a-9b24-7e1c5d90a3f6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of `action` on a request (docs/api.md §2.3, §7)
**Revisit when:** a route splits its membership check and its effect over two transactions

`scopes.py` still gives a proxy the coder's scopes and `requests:answer`; that it
answers only as a relay, naming an owner in `on_behalf_of`, is checked in the answer
route, so `has_scope` keeps meaning the same for every reader. The relay opens no
scope: a request needing `project:admin` or `members:admin` stays refused with it.
`Membership.may` and `require` open any other governance scope when the
call's signed `Maity-On-Request` holds (`proxy_go`), and the first such
check spends the go on the route's connection.

**Reason:** `has_scope` also answers who holds a scope for others (done
authority, cover, inbox), where a proxy must not start counting as an
admin; only the calling membership knows the call. Spending at the check
puts it in the transaction of the effect, so a failed call rolls it back
and a racing call finds it used.
The call remembers its spend only as the event's `seq`, and counts it only while the
request's row shows that `seq`: a retried transaction (`db.retrying`, the idempotency
key's race) has rolled the spend back and has to spend again, or its effect would commit
with the go unused.
This holds because PostgreSQL and InnoDB never give a rolled-back `seq` to another call.
SQLite does reuse one, which is harmless today: `retrying` treats nothing there as transient,
and a taken idempotency key replays instead of running the call again. A new path that runs a
call again on SQLite needs another proof, such as an id of the call in the event.

`action.path` is stored as the proxy sent it, in the `<owner>/<slug>` form of
the call, and is compared bytewise: no later rename rewrites it. After a
rename the go still matches a call on the old name, which resolves as an
alias, and any other spelling is a `mismatch`, so the proxy asks again.

**Rejected alternatives:**
- Grant the governance scopes in `scopes.py` and filter per route: the literal
  reading of "holds trust `admin`", but it widens every `has_scope` reader.

## An event's actor shows the author's standing as it is now, to members only

**Id:** 5d1c7e20-9a34-4f68-b2e1-83c0f6a4d719
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** prompt-injection audit, finding F1; `docs/agents.md` rule 4
**Revisit when:** a sentence's authority has to be judged as of when it was written, or trust stops being readable by every member

Rule 4 binds a sentence only as far as its author's trust and role allow, so the reader has to
see them: `actor.trust`, `actor.role` and `actor.cross_owner`. They are read when the event is
shown, null once the author has left. `cross_owner` is relative to the reader, because "another
owner" only means something to one reader's human.

**Reason:** the question an agent asks while reading is how far this author can bind it now;
someone since lowered or removed should not keep their old weight. Trust, role and `owner_id` are already
in the member list for `project:read`, so a member learns nothing new from them. A reader who is no
member, such as an agent's owner reading along in a chat, cannot read that list and gets none
of the three.

For an event made through a bridge the standing is what the hub ran the call with: trust capped to
`member` as in `Membership.trust`, and `cross_owner` also when the bridge's owner is another than
the reader's. The text comes from the bridge, so the served agent's full weight would make a
bridge's sentence bind as an admin's.

**Rejected alternatives:**
- The served agent's own trust on a bridged event: what the member list shows, but it hands
  another owner's bridge an admin's weight under rule 4.
- A copy of trust and role on each event row: exact for the moment of writing, but a column on
  the busiest table, and it shows a removed author at full weight.
- `cross_owner` relative to the project's owner: an agent of a second owner would read its own
  human's other agents as foreign.

## `GET …/roles` describes a built-in role with the contract's table, word for word

**Id:** 9f0cef12-062a-4fcd-ae05-0afde1dfad91
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's approval of the plan for tsk-g83nf2q1j728 (docs/api.md §2.3 "Project roles", §6.28)
**Revisit when:** the briefings bring the project's and the account's `guide_role` texts (tsk-k0k3jzrkpza2), or the dashboard needs the descriptions without the contract's markup

Each built-in role in `builtin` carries the "What the member does" column of the §2.3 role
table as its `description`, copied into `guide.DESCRIPTION` in the table's order with its
markup ("(§7)", "(below)", backticks), and a test holds the two equal, as for the guide texts.
Its `scopes` are the role's own (`scopes.role_scopes`), which no trust widens: a proxy shows
the coder's, as the table does. Its `guide` comes from `guide.role_guide`, the same function
the resume's `guide_role` layer uses; today that is the hub's default for every project, and
the project's and the account's texts belong there when the briefings exist.

**Reason:** the hub had no description text of its own, and the card asked for none to be
invented; the contract's column is the only text there is. One function for the guide keeps
the role list and the resume from saying two things once the layers arrive.

**Rejected alternatives:**
- Strip the section references and "(below)" for the dashboard: changes the contract text's
  form, which is not this card's to decide.
- `scopes_for(trust, role)`: depends on the caller's trust and adds `requests:answer` to a
  proxy, which the table does not list.
- Build the project and account guide layers here: they are the briefings card's.

## Own approvals are counted at each move to done, in one module, from the review results and signatures on the card

**Id:** 3ebd6d4a-8923-4899-becc-84476a1c6b7a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3ggnhdmgmkf3 (2026-11-23), the lead's go on the four-PR plan (seq 201341) and the acceptance for PR 2 after a security review of the merge path (seq 201604: every path to done, under every `done_authority`, a test per path); docs/api.md §2.3 "Own approvals", §6.4, §6.6
**See:** isolation.md#an-agent-that-joined-while-its-owner-was-no-member-stays-outside-a-mark-set-at-the-exchange-never-cleared — 28c600cc-2b4e-4be0-ab48-00a49441c138 — as of 2026-11-23
**Revisit when:** a move to `done` gains a path that does not pass `routes/tasks.py`'s status change, the report or `merged._blocked_by`; or review results get a table of their own

`own_approvals.py` holds the whole rule: who is an outside agent, which
cards are outsiders' work, and `counted`, which reads the card's review
results and its `approvals` when a move to `done` is asked for and stores
nothing. The status PATCH calls `gate` where it would set `done`, after
every other check, so the three moves to `done` and the signature that
completes `approvals` pass through one place. A report with `done: true`
is stored first, then asks `missing`, and goes to review instead (on a
`blocked` card it stays `blocked`, with `review` as the status its answer
restores). The merge path asks `missing` in `_blocked_by`. A human's own
move or signature is passed in as one approval before the count.

What counts (the lead's ruling of 2026-11-23): an author's latest review
result on the card, kept per author (agent or human), not per membership
row, a redacted one included, so a later `changes`, `comment` or redacted
result withdraws an `approve`. That `approve`, on exactly the reported
head, counts only if it was not sent through a bridge, the hub recorded
its author as a signer when it stored it, it came from the author's
current active membership, and its author stands now: an agent the
project's own (active, not isolated, `tasks:review` or `tasks:test`, its
owner a live member picked by `own_agents`), a human of the project with
that standing and a live account. A human's signature counts while it
stands (`cards.standing`) and only on the current report's `revision`.

The standing at the time of sending is recorded, not reconstructed: when
the hub stores a `review_result` it writes `event.review_signer` (own,
active, not isolated, the scope, not bridged, a human's or an agent's
owner's account live), and `event.review_pr`, the pull request number
its subject `#<n>` names. A result without the record (stored before
the column) counts as none. The card's results are read through
`subject_id` and `review_pr` with the card's current pull request, so
those event reads are bounded by the card's own results, not the
project's chat; whether that pull request is this card's is resolved
exactly, once per count, by one scan of the project's reported cards,
and only when a result tied only by `#<n>` exists (Cost, below).

An outside agent is read on the membership the check is about: its
active row, else its most recent (a reporter who has left). Trust
`outside` and the `joined_outside` mark count on that row only, so §2.3's
one way out of `outside` (removal, then a member's fresh join, a new row
without either) works; the same reading as trust `outside` in H1
(tsk-enfbkj0xqq5m), by the lead's ruling of 2026-11-23 (seq 202963). An
owner who is no member now makes its agent outside too, and so does an
owner whose account is suspended or deleted, so that agent's work is
gated (failing closed; the lead's ruling of 2026-11-23, seq 203828).

**Reason:** the contract judges outsiders' work "as the card and its
members stand then", and an approval stops counting when its author
stops standing or a later result withdraws it. A count computed at the
check follows all of that without an invalidation path. One module keeps
the three callers from drifting apart. Gating at the point where the
status is set covers every way the PATCH can reach `done`, including any
added later through `check_transition`.

**Rejected alternatives:**
- A stored counter on the card, raised by each review result: it needs
  undoing on every withdrawal, demotion, removal, isolation and new head,
  and a missed path leaves a wrong count that opens the gate.
- A check inside `cards.check_transition`: it does not see the signature
  that would complete `approvals`, which is decided after it.
- Gating only the holder's moves: suqj's review showed every
  `done_authority` value reaches `done` for outsiders' work some way.
- An `approve` judged only by its author's row now: an outsider's
  approval would turn into an own one after a fresh join, and a
  promotion in place would make an earlier `approve` count (the lead's
  ruling of 2026-11-23: a signer when sent, recorded, and the same row
  standing now).
- Reconstructing the standing at sending from the rows: trust, role and
  isolation change in place and keep no history.
- Trust `outside` or the mark on any of the agent's rows: fails closed,
  but closes the way out §2.3 names (docs/api.md, "Outside": the owner
  removes the agent and joins it again); briefly ruled so and taken back
  the same day.

**Cost:** review results are message events, recognised by their own
columns (`review_signer` set), never by a payload a redaction replaces.
They are read in two queries, merged by seq, each seeking its own index:
a result tied to the card by `task_id` through `ix_event_subject`
(`project_id`, `subject_type` `task`, `subject_id`), and one tied only
by a subject `#<n>` through `ix_event_review_pr` (`review_pr`,
`project_id`) with the card's current pull request. These two event reads
are bounded by the card's own results. Every result named by its pull
request names that one pull request, so whether it is this card's is
resolved once per count, and only when such a result exists: that
resolution reads the project's reported cards (`cards.naming_pr`) once,
where once per result would repeat it (#2145 reviews A2429, A2442). One
query with an `OR` across both would leave neither index usable. The
index leads with `review_pr`: led by `project_id`, PostgreSQL's planner
took it for reads filtered on the project alone (the chat sweep) and
walked every event. A report naming a pull request beyond the column's
range looks none up. This runs only on a move to `done` of outsiders' work.

## A new head takes outsiders' work from done to review with its claim, and an outside agent's role gives no done authority

**Id:** b02a8fef-a30e-4f59-803c-724666683e27
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-nvsxwd4tzzg9 (2026-11-24) and the lead's ruling on it (seq 209840): `review`, not `open`; the claim stays and the own approvals decide again; a trust-based rule. docs/api.md §2.3 "Own approvals", §6.4, §6.6. It replaces, for the way back from `done`, the claim's check and the release to `open` of the lead's decisions of 2026-11-18 recorded in the root context (members.md, dab6ae4a-3f6b-4431-8945-80e5956a38a8)
**See:** trust.md#own-approvals-are-counted-at-each-move-to-done-in-one-module-from-the-review-results-and-signatures-on-the-card — 3ebd6d4a-8923-4899-becc-84476a1c6b7a — as of 2026-11-24
**Revisit when:** a card can reach `done` of outsiders' work with no holder (a claimless `done` card under `done_authority: holder` then waits in `review` for a takeover); or a done authority is resolved for a role somewhere other than `cards.has_done_authority`, as `task_merged` still does: its role tokens reach an outside agent (docs/api.md §2.3 "not built yet", tsk-4bfgr4q6zz3x)

A report with a new head on a `done` card of outsiders' work, while its
pull request is open, sets `status: review` and clears `closed_at` in the
same write that stores the report; the claim the closed card kept is left
as it is. Whether the card is outsiders' work is asked on the card before
the write: the reporter must be the one whose report it replaces, so the
workers (holder and reporter) are the same either way. Own work and the
same head stay `done` as before.

`cards.has_done_authority` returns no authority under `reviewer`,
`tester` and `reviewer_and_tester` to a caller that
`own_approvals.outside_agent` counts as outside, and `cards.sign`
refuses such a caller as it refuses a missing scope. A stored signature
is held to the same eligibility wherever it is read (`cards._stands`,
under `standing`): an agent's signature counts only while it is no
outside agent, so one given before this rule, or by a signer that later
became outside, counts nothing. All three ask the same function the gate
uses, so trust `outside`, the `joined_outside` mark and an owner who is
no member all count; the holder's authority under `holder` is untouched
(it passes the gate of 3ebd6d4a).

**Reason:** the lead's ruling: with the claim kept, the card is where it
was before its last close, and the own approvals decide again on the new
head, since every move to `done` passes the gate. Nothing about the
claim is re-decided, so no release, no `task_released` and no second rule
of who may hold a claim. A stale holder is handled as on any card in
`review`: by takeover and cover, whose definitions stay as they are. For
done authority the rule is the agent's standing, not its role: the
policy bases only keep reviewing roles out of an outsider's join, while a
`joined_outside` agent, or one whose owner left, can hold any role a
member's agent can; reading the same `outside_agent` as the count keeps
the two from drifting.

**Rejected alternatives:**
- The contracted claim's check with a release to `open` (2026-11-18):
  replaced by the lead's ruling for `review` with the claim kept; it
  needed a second reading of who may take a claim and a hub-made release.
- Keeping the card `done` and relying on the gate: the gate only guards
  moves to `done`, so a head nobody approved would stay `done`.
- Withholding done authority by role list (no reviewing role for an
  outsider): the list only governs the join, and an agent marked
  `joined_outside` or whose owner is no member holds a member's roles.
- Refusing the signature only through the done-authority check: `sign`
  would still give a signature to any other caller path; it refuses on
  its own too.
- Checking a signer's eligibility only when it signs: a signature stored
  earlier, or one whose signer's owner later left or whose row was
  marked, would still complete `approvals`; eligibility is checked when
  a signature is counted, as a demotion or removal already is (the
  lead's scope for the second round of #2179, 2026-11-24).

## `PUT …/roles` refuses a guide and keeps the one a role already has

**Id:** 66b19935-0440-4a76-9ebd-3ef6df9fbe94
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's approval of the plan for tsk-m15sg396s947 (docs/api.md §2.3 "Project roles", §6.28)
**Revisit when:** the briefings take the project roles' guides over (tsk-k0k3jzrkpza2)

A `guide` in any entry of a `PUT …/roles` is `invalid` with `custom[].guide: "moved"`,
unindexed as the contract names it, next to any other field's error. A role that stays
under its name keeps the `guide` and `guide_by` it has stored, a new role gets none, and a
removed role takes its guide along; the resume and `GET …/roles` still show a stored guide.

**Reason:** the contract moved the guides to the briefings, but those routes do not exist
yet, so nothing else writes a project role's guide. Rebuilding the list from the body alone
would erase every stored guide on the next `PUT`, a change of stored data the card ruled out.

**Rejected alternatives:**
- Drop the stored guides with the next `PUT`: loses texts admins wrote, before there is a
  place to write them again.
- Keep accepting `guide` until the briefings exist: the contract already refuses it, and no
  client in the repository sends one.
- Move the stored guides into the briefings now: there are no briefings to move them to.

## A trust the hub does not know gives no scopes

**Id:** 483172a9-4079-4415-b3cd-2e63deda672b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's approval of the plan for tsk-aqw1kqh8h12t (docs/api.md §2.3)

`scopes._granted` grants scopes only for a trust in `TRUSTS` or `OUTSIDE`. Any other trust,
null or a name the hub does not know, gets no scopes at all, whatever the role, a proxy
included: `scopes_for`, `listed_scopes` and `has_scope` answer an empty list and `False`.
The role is still checked first, so a name that is not a built-in role stays the caller's
fault (entry 25a99503).

Every caller reads trust from a membership row, whose `trust` column is not null and is only
written from `TRUSTS` or by the outsider's join (`OUTSIDE`), so no stored membership changes
its scopes. The stand-ins without a trust (`attachments.reader_row`, the chat `Outsider`)
never ask `has_scope`.

**Reason:** a check on scopes must refuse what it cannot place. Before, every trust other
than `guest` and `outside` fell through to the role's scopes, so a trust added later, or a
row a future join wrote wrongly, would have acted as a member's without anyone deciding so.

**Rejected alternatives:**
- Fall back to the role's scopes for a trust the hub does not know: the default this replaces;
  it gives work rights to a membership no rule describes.
- Raise for an unknown trust, as for an unknown role: a request would end in a server error
  instead of a refusal, and the read paths that list scopes would break for the whole page.
