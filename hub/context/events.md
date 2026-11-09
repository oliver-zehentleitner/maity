# Events

## The long-poll waits on an asyncio event, never on the database

**Id:** 6310ef59-6010-4fa5-95d5-30f20bc00117
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the hub skeleton, 2026-10-21 (to be recorded before the first long-poll); implementation session, 2026-10-21 (the events slice)
**See:** https://github.com/oliver-zehentleitner/maity — 3dacd29b-bd09-4757-80bb-7f3cfbd9af91 — as of 2026-10-21
**Revisit when:** a second replica runs, or waiting sessions outnumber what one process can hold

`GET …/events?wait=N` is an `async def` endpoint. It reads in the thread
pool, holds no database connection while it waits, and waits on an
`asyncio.Event` of its own in the event loop. `events.transaction()`
announces every committed event to an in-process registry
(`maity_hub.longpoll`), which sets the events of the waiters on that
project with `call_soon_threadsafe`. A woken waiter re-reads; a two-second
re-read is the fallback for anything the signal missed. The registry also
holds "one open long-poll per credential" (a second call supersedes the
first) and the `listening` flag of §5.3.

**Reason:** a waiting agent costs the hub nothing but a coroutine and an
event, so dozens of sessions can listen at once without a connection pool
or a thread each. The signal comes after the commit, so a woken reader
finds the row (`events.transaction`). The project decided against
database-specific notifiers (LISTEN/NOTIFY) to stay portable, so the wake
is in-process, which fits the one replica V1 runs.

**Rejected alternatives:**
- A synchronous endpoint sleeping in the thread pool: every waiter would
  hold one of the pool's 40 threads, and the pool would run out long
  before the sessions did.
- Polling the event table every second for each waiter: simple and
  replica-proof, but a query per waiter per second for nothing in the
  common case.
- PostgreSQL `LISTEN/NOTIFY`: the natural cross-replica signal, refused for
  V1 by the database-agnostic decision; it is the first candidate when a
  second replica comes.

## A runner's stream reads every project it was ever attached to

**Id:** 96643c34-fc6f-4279-8a89-39882e3ab3d8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of the runner stream, 2026-10-22; accepted by the contract owner the same day, `docs/api.md` §15.8 (PR #84)

`GET /runner/events` (`docs/api.md` §15.8) scans the events of every
project the runner has an attachment row in, active or detached, and
delivers those whose audience names `runner:<id>`. What the runner
otherwise reads — the projects in the hello packet, its placements —
stays on the projects it is attached to now.

**Reason:** `runner_detached` is written into the project being detached,
at the moment the project leaves the runner's set. A stream limited to
the current set would never deliver it. Reading the old projects as well
exposes nothing: an event names the runner only while it concerns it.

**Rejected alternative:** the stream on the current set only, as the
contract's first text read. The runner would learn of a detachment only
by noticing that a project is missing from its next hello.

**Rejected alternative:** writing the detachment somewhere outside the
project. Every event belongs to exactly one project (§15.10).

## Mention pings are counted in process and given back when the write does not commit

**Id:** 8a5e4c45-edcd-4c23-89c6-2b784b9d3e14
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of mentions (`docs/api.md` §8.6), 2026-10-22, PR #151 and its review

The limit of 30 pings per membership in 10 minutes is a sliding window in
memory (`mentions.PINGS`, a `ratelimit.Limiter`), charged inside the write's
transaction just before the event is emitted, all pings of one write at
once. A write past the limit is refused as a whole and stores nothing; its
`Retry-After` is the time until every one of its pings fits. A write that
is charged and then does not commit (a later error, a `retrying` attempt,
a lost idempotency race) gives its pings back through
`events.on_rollback`.

**Reason:** like the nonce window and the long-poll registry, it is state of
the one replica (`docs/api.md` §8.3), cheap to check and lost harmlessly on a
restart. Charging before the emit is what lets the over-limit write fail
whole, as the contract asks; giving back on rollback keeps a failed write
from spending budget it never used.

**Known imprecision:** the give-back drops the newest entries of the
member's window, which under two concurrent writes of the same member may
be the other write's; both were charged within the same instant, so the
window's timing is off by that much at most.

**Rejected alternatives:**
- Counting pings from the event table (`mentioned` events and message
  audiences of the last 10 minutes). Exact across restarts and replicas,
  but a query over the event log on every write that mentions someone, for
  a spam guard.
- Charging after the commit. Nothing to give back, but the over-limit
  write would already be stored when the limit refuses it.

**Revisit when:** the hub runs more than one replica.

## Shared environments are computed from live sessions; only announcements are stored

**Id:** 158a2300-873a-41eb-8888-205157b844e6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the shared-environment warning (`docs/api.md` §5.3, contract #132), 2026-10-22

Who shares an environment with whom is computed whenever a member view
asks, from the live agent sessions and the ids their resumes declared.
`environment_overlap` holds one row per pair only to remember what was
announced: when the overlap started, the highest level announced, and
since when the two no longer share an id (`quiet_since`). The rows are
brought up to date when one member's sessions change: on its resume and
on a credential's revocation (which member removal goes through), under
the project lock, so that two members' changes cannot both read the pair
before either writes it. A pair
that shares again within 10 minutes of `quiet_since` continues its
overlap; later, it is a new one and is announced again.

`shared_environment_detected` names only humans in its audience (the
owners and the human `owner`/`admin` members, never `role:admin`), and
`events.readable_by` refuses it to every agent before the see-all rule of
owners and admins, and before the actor's own events. Its redaction
inherits that: an `event_redacted` whose subject is of a humans-only kind
is refused to agents the same way, decided per batch of the scan with one
query for the redacted events' kinds, so the payload stays `{seq, reason}`.
A redaction's `reason` is shown only to the human owners and admins and to
the redactor; every other reader gets `reason: null`, in the notice and in
the tombstone. Without a known reader (a runner's or a placement's list, a
replay that cannot place its caller) the reason is hidden: forgetting the
reader shows less, never more. A chat message's notice carries the chat's
`conversation_id`, so see-all does not reach it, as it does not reach the
message; and a redaction first checks that the caller can read the event at
all, so no answer but `not_found` tells anyone else that it exists.

**Accepted:** the `seq` an agent sees has a gap where such an event is,
right after the resume that caused it, so an admin agent can tell that a
resume was followed by an event it may not read, and when; never which
members or which level. This is accepted because only humans act on the
warning, and emitting it later than the resume, in a background pass,
would still leave a gap, only a less telling one.

**Reason:** the field must be current on every read. The live sessions are
the source of truth, and they are few per project. Storing the overlap
itself would need a writer for every way a session ends. The 10-minute
rule only matters when the next resume decides between "continues" and
"new", so it is evaluated there, without a timer. An agent with the
`admin` role sees every event and would otherwise read the warning about
itself and its peers, which the contract keeps from agents.

**Rejected alternatives:**
- A stored overlap kept current by a background sweep. Exact at any
  moment, but one more worker for a warning, and the view would lag it.
- Audience `role:admin`. It also reaches admin agents, which may not read it.


## The project message listing reads the events through the one read rule, in Python

**Id:** 56027d65-883a-4c87-a000-081c7fd236d1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (docs/api.md §8.8); the contract fixes the result, not the way the hub gets there
**Revisit when:** the scan budget makes pages too short to read comfortably in a busy project, or the read rule gains a clause that cannot be applied to a row alone

`GET /projects/{slug}/messages` takes the project's `message` events that
belong to no conversation and keeps those `events.readable_by` lets the
caller read, in batches of 500 by `seq`, until the page and one more are
found or 2000 events have been examined. The one more tells whether a next
page exists; when the budget runs out first, the page is short or empty and
its `next_cursor` goes on after the last event examined, so a sparse filter
never costs more than the budget and never skips a message. The conversation is
read off the event row, which a redaction leaves, so a redacted chat
message is never listed. A `type` filter is applied in Python too: a
tombstone has no type in its payload, and it is listed only without a
filter. The cursor is the last `seq` shown, bound to the `after`, `before`
and `type` it was handed out with, so it is refused under any other query.

**Reason:** the contract says nothing listed here may be unreadable through
`GET /events`. Using the same function makes that true by construction,
today and whenever the rule changes, instead of by two copies kept equal.

**Rejected alternatives:**
- A filter on `audience` in SQL: the audience is a JSON list that three
  engines query differently, and the rule is more than the audience (the see-all
  roles, instance tokens, humans-only kinds, redactions of hidden events).
- A table of project messages kept beside the log: one more write on every
  post and on every redaction, to speed up a read nobody has measured.

## An episode of not listening lives on the session, checked by a minute worker

**Id:** 0cbc3037-5834-4a6d-b518-ae640fb47046
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §5.3 "Not listening" (contract #498, the maintainer's decision of 2026-10-28); the card tsk-43r1yqwjq3pg from the coordinator, 2026-10-28
**Revisit when:** the hub runs more than one process (the open long-poll is known in process only), or the contract counts other calls than /events as listening

A session's last call for events (or its resume) is stored as
`events_at`; `last_seen_at` counts every call and cannot tell. An
episode is three columns on the session: when the 10 minutes ran out,
the oldest event that waited, and the notice filed to the profile's
owner. A worker checks every minute, per session under its project's
lock: it starts an episode when the oldest event that waits for the
instance (`events.wakes`, and, where the team's wake rule chose no
instance, the lead or every instance) is 10 minutes old and the session
made no call for events in that time, and it ends one when the
acknowledged cursor reaches that event, the session ends or an exclusion
begins. A session with an open long-poll is listening. The start of
`member_not_listening` wakes only an agent the event names by
`member:`, the reports-to; the end wakes nobody.

A resume counts as a call for events through the fallback `session.events_at or
session.started_at` (`not_listening.py`): a resume sets `events_at` to its own moment, and a
session that never called `/events` is measured from its start. Removing the fallback
because `events_at` seems always set would drop a session that only resumed out of the check;
the tests of #685 (resume after 8 minutes restarts the 10, the sent cursor becomes
`acknowledged_seq`, without a cursor the event keeps waiting) hold it.

**Reason:** the episode must survive restarts and be ended by whoever
notices first, so it is stored; on the session, since an episode belongs
to one session and ends with it. A minute's delay to notice the end is
what the contract's own check interval allows.

**Rejected alternative:** ending the episode inside the /events call that
acknowledges the event: faster, but that call would then take the
project lock and file or withdraw requests on the long-poll's hot path;
the worker keeps the read path cheap. A table of episodes of its own:
more than one row per session is never needed.

## A supervised session is left out of not listening only while an active placement names its credential

**Id:** cb4184b4-d420-4205-b0d9-d8338e92ec65
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §5.3 "Not listening", §15.11 and §15.13 (the runner local-mode contract, #1294); the card tsk-mcd2xwwa2fzv from the coordinator
**Revisit when:** something other than a placement's runner reports a supervised agent's stopped runs, local mode gets a placement of its own, or §5.3 says what happens to a placed session after its runner is revoked under `keep`

`not_listening._excluded` leaves out a session opened with `supervisor` only while a
placement with `active` true has the session's credential as its `credential_id`. A
supervised session no placement names, local mode's (§15.13) or one whose placement was
closed, is checked like any other session; a placement that starts to name the credential
during an episode ends it as an exclusion that begins. The lookup runs in the minute worker
only for a session with `supervisor` (the condition short-circuits before it), under the
project's lock it already holds. A credential whose revocation after a runner's stop is due
but not yet written (`runner_revoke.due`) counts as revoked: the hub cannot end the process
(§15.3), so the agent may never call again to have it written, and if it still runs and calls,
the revocation is written then and the session stays left out; the views already show it as revoked.

**Reason:** a placed agent does not wait by design, and until its runner is revoked that runner
reports each stopped run (§15.7), so an episode would only repeat what the runner says. After a
runner revoke under the default `keep` the placement stays active, no runner can report, and the
session stays left out; that gap is in §5.3, not new here (Revisit when). Local mode has no
placement and its stop sends nothing to the hub (§15.13): without this check its lead sees only
the presence go `away` and `offline`, and an event nobody reads waits silently.

**Rejected alternative:** leaving out every supervised session, as the hub did until this
card: a stopped local mode was then never reported. Matching the placement by membership
rather than by credential: a member can have several instances (§6.17), and a placement names
only one of them, so local mode beside a placement of the same member, or any instance while a
placement waits for its first pickup, would be left out although no runner reports on it;
§5.3 names the credential.

## The conversation list is built for all chats at once, not one chat at a time

**Id:** 0b23275f-9dc4-44fe-8258-bd41cd8408e0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-ggza5m1nwtzh; Traefik access log of 2026-10-28 (`GET /projects/O/S/conversations` p95 1.2 s); the local measurement in the pull request
**Revisit when:** a list needs a count that no grouped query can give, or `GET /me/conversations` needs a different shape than `conversation_list` returns

`GET /projects/{owner}/{slug}/conversations` (and the resume packet's list) built each entry
with about ten statements and the whole list before it cut a page of 50, so a caller with 30
chats paid 592 statements, 1.2 s on SQLite with 18,000 messages. `maity_hub.conversation_list`
reads the same data for all chats in a fixed number of statements: the newest message of
each chat after its window in one grouped query, the unread count in one grouped query
joined to the read marks, the stays, owners and people of all rooms in one query each. A
message is checked for a mention of the caller only when its payload text has a `member_id`
and the caller's id (a chat message names its addressee in `to`, so the id alone matches
everything); the exact test stays on the rows read. 38 statements and 0.15 s for the same
data. The entry for a single chat (`GET .../conversations/{id}`) keeps its own code in
`routes.conversations`, and `tests/test_conversation_list.py` holds the one-chat-at-a-time
list as a reference: every caller kind, `observed`, page sizes and cursors give the same
pages, and the statements stay the same when more chats are added.

**Reason:** the cost was the statements per chat, not the data; building all entries in
few queries keeps the page cut after the fact simple (the sort is by `_activity`, which
needs every chat's newest message anyway) and gives `GET /me/conversations` one function to
call per project. Deriving only the page's chats would have kept ten statements per chat
for a default page of 50.

**Rejected alternatives:**
- Building only the entries of the page after sorting by a cheaper key: the key is the newest
  message of each chat, which is most of the work, and a page of 50 is most callers' whole list.
- A cache of the list: a read mark, a message or a rename would have to invalidate it.

## `GET /me/conversations` is the per-project list built for all memberships at once, ordered by activity, project name, id

**Id:** a7fca6c0-d692-4a54-9f92-666073c5faf4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §9.3 "Across projects"; tsk-45vs1hdzswjs; the dashboard's `#/chats` read one list per project (p95 7.8 s, finding D of 2026-10-28)
**Revisit when:** a human has more chats than one request can hold in memory, or `counts.chat` and `totals.unread` are made to count by different rules again

`conversation_list` takes the caller's memberships as a list and keys every lookup by
(project id, chat id), because a direct conversation's id is its agent's and one agent in two
of the caller's projects has two chats of one id. `GET /me/conversations` reads the
memberships in two statements, the owned agents in one, and then the same grouped
statements as the per-project list for all projects together; a project more costs no
statement. The sign-in itself renews a lease per project and is not part of that count. Items
are sorted by activity, newest first, and where the moment is equal by `project.full_name`
and `id` ascending (the contract's wording; the per-project list breaks a tie by `id`
descending, which it cannot do across projects without making the same agent's two chats
swap places). The cursor carries (activity, `full_name` + `id`) and the list's scope, so it
is valid for one `observed` only. `totals` are summed over all items, not the page, and an
observer's `null` counts add nothing. An archived project's chats are listed, a project the
caller left is not.

**Reason:** one read for the overview is what the dashboard needed; looping the per-project
list would have kept the cost proportional to the projects, which the contract excludes.
Reusing the per-project builders (the same statements, with a list of memberships) keeps one
place where a chat's window, unread count and observer rules are decided.

**Rejected alternatives:**
- Calling the per-project list for each membership and merging: simple, but a statement set per
  project, the shape the contract rules out.
- Sorting ties by `id` descending as the per-project list does: a total order across projects
  needs the project name, and the contract names it.

**Resolved (same change):** §9.3 says `totals.unread` is the number §18.2 gives as
`counts.chat`, but the bell counted only the direct conversations, so a room with unread
messages made the two differ. Decided by the lead on 2026-10-28: both count the direct and the
group chats the human takes part in, observers nothing, through one function,
`conversation_list.unread_chats` (per project, from the same direct-chat and window helpers
the list uses). #556 meanwhile added the groups to the bell with `listing._unread_groups`, two
statements per stay; that and the per-agent direct count are replaced by `unread_chats`.
`tests/test_me_conversations.py` holds the bell and `totals.unread` equal, also after a read
mark.

## A pin belongs to the human, lives while it reads the chat, and is dropped where access ends

**Id:** cc8d2f9e-a34c-4d3c-8008-8619dcc77b72
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §9.3 "Pinned" (contract #914) and the card tsk-9a3ph3jvhhrb; the contract fixes the routes, the 20 across projects, the four bands and that a chat left keeps no pin; how the hub keeps that is this entry's reading
**Revisit when:** a way to lose access to a chat appears that neither ends a stay nor removes a membership (a trust change that ends reading a round's thread along is one today), or the lists move into SQL

`conversation_pin` is keyed by human, project and chat id, not by membership: an owner outside the
project reads its agents' chats along without a membership (§9.2) and may pin them, and the 20 are
counted across projects. `pins.prune(project)` runs where a stay in a group chat ends
(`group_chats.remove`, which a membership's removal and an isolation pass through) and after a
membership's removal (its direct chats), and drops every pin of the project its holder no longer
reads; `PUT …/pin` prunes the holder's own pins before it counts, under the human's row lock, so a
pin lost some other way never blocks a new one and two projects cannot both take the 21st. A chat
left and joined again therefore comes back unpinned. The lists add `pinned` after the entries are
built and sort in Python, a stable sort per band; the cursor carries the band, and the cursor scope
changed so a cursor from before the bands is refused instead of read wrongly.

**Reason:** the contract says a chat left keeps no pin, and a stale row would count against the 20
and come back on a later join. The places where access ends are few and already central. The
downgrade only drops the table, and the index goes with it: MariaDB refuses
`DROP INDEX ix_conversation_pin_project` while the foreign key on `project_id` needs it (error 1553).

**Rejected alternatives:**
- A pin valid while its `pinned_at` is after the start of the current access: every list would need
  each chat's access start, which the entries do not carry, and the 20 would still count dead rows.
- Pruning while reading a list: a `GET` that writes, and a list without `observed` cannot tell a
  chat read along from one no longer read.
- Keying by membership: an owner outside the project holds none, and the limit is per human.
- A downgrade that drops the foreign key and then the index before the table: dropping the table
  already removes both, so the extra steps would order nothing.

## A review result's `review` is checked for its shape and stored as given; the repository is never read

**Id:** d6ea47d4-3ad6-435e-8806-f1faa96a6360
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §8.4 ("A review result cites what it judged", contract #745) and §8.8; the card tsk-9cmn9xy8zcqt from the coordinator, 2026-10-30. The contract fixes the fields, the limits and the reasons `required`, `too_few`, `too_many`, `too_long` and `format`; the points below it leaves open are this entry's reading and inferred
**Revisit when:** the coordinator's check of a cite against the diff moves into the hub, or the contract names the unnamed cases (an unknown key, an empty text, a line break other than `\n`)

`reviews.check` returns the `review` as it is stored, or every problem found, each at its own path (a
cite's by its index: `review.cites.2.line`), and `post_message` raises them together as one `invalid`.
A `review_result` without `review` is `required`; any other type with one is `not_allowed`. The
payload carries `review` as posted except that a cite's absent `line` is stored `null`; the
messages listing (§8.8) returns it on the item, `null` for every other type and for a tombstone (the
redaction replaced the payload, so nothing of it is left). The export of a person's own messages (`GET /me/export`, §2.9) carries it too, `null`
for every other type: a review result is a message they wrote, with what it judged and read. A
redacted review result exports no `review`: the redaction replaced the payload, and the export follows the
messages listing (§8.8). Rejected: keeping `review` despite the redaction, which would undo what the
redaction is for.

The contract leaves some malformed cases without a reason; they are all `format` at their own path:
an unknown key of the review or of a cite, an empty `subject`, `path` or `quote`, a `line` that is not
a positive integer (a boolean is not one), a quote with a line break (`\r`, `\n`, U+0085, U+2028,
U+2029). Lengths count characters, not bytes. `review_result` without `review` has no compatibility
path (alpha, `context/messages.md`).

**Reason:** the lead checks a cite against the diff before an approval counts; the hub's part is
that the shape is there to check and that a reviewer learns at once, with the field, what is wrong,
instead of one problem per attempt.

**Rejected alternatives:**
- Reading the repository to verify a cite: the contract says the hub does not, and the hub holds no
  checkout of any project.
- Stopping at the first problem: a reviewer would fix and resend up to five times for one review.
- Keeping `review` optional for a while: nothing posts a review result without it that is not about
  to be changed, and alpha keeps no layers for the old shape.

## The meat-proxy choice per chat is a row of its own, keyed by human, project and conversation, and one function adds it to every participants list

**Id:** ab4caa81-c57d-418f-a664-7ff498f1e6e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §9.3 "Meat proxy per chat", §5.2 (contract #922); the card tsk-2yqm0gebktrk
**Verification:** corroborated
**Revisit when:** a chat may carry more than the human's own on/off choice, or the participants lists are built in one place

`conversation_meat_proxy(human_id, project_id, conversation_id, meat_proxy)` holds a human's own choice for one chat, `true` or `false`; `null` deletes the row and the chat follows the profile. `chat_meat_proxy.shown` adds `meat_proxy`, `meat_proxy_lead`, `meat_proxy_hands`, `meat_proxy_chat` (only for the human reading) and, while on, `meat_proxy_note` to every human entry of the participants lists it is given, in the conversation view (`group_chats.view`), the direct item and both lists; the resume packet's `conversations[].meat_proxy` is read from the same entries. `PUT …/meat-proxy` emits no event. The account's deletion and export name the table.

**Reason:** a direct chat has no participant row (its id is the agent's), and the choice must work there as much as in a group chat, so a column on `conversation_participant` would cover only half. The same agent's direct chat exists once per project under one id, which is why the project is part of the key: a choice in one project must not switch the mode on in another. One function over the lists keeps the fields from drifting between the four places participants are built. The migration's primary key and foreign keys must be the same as in `tables.py` (human, project, conversation; foreign keys on human and project): the tests build the schema from the migrations, so a key only in `tables.py` is never checked. A first version had `(human_id, conversation_id)` in the migration, and a second project's direct chat then failed with a unique violation.

**Rejected alternatives:**
- A column on `conversation_participant`: no row for a direct chat, and a stay per join in a group chat that would lose the choice when the human leaves and comes back.
- Keying by conversation id alone: the same agent in two projects would share one choice.
- Emitting an event on a change: the contract has the agents read it on their next resume and wakes nobody; an event would reach every reader of the chat for what is context about a person.

## A chat's meat-proxy choice decides the lead part only; the hands part stays the profile's

**Id:** 5f1c4bef-59da-4382-a2d5-a65de2958052
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-rznymp9hb1qm (the owner: the mode in a chat means being told what to do, and a profile with only the hands part must not read as active there); `docs/api.md` §9.3 "Meat proxy per chat"
**Verification:** corroborated
**See:** events.md#the-meat-proxy-choice-per-chat-is-a-row-of-its-own-keyed-by-human-project-and-conversation-and-one-function-adds-it-to-every-participants-list — ab4caa81-c57d-418f-a664-7ff498f1e6e7 — as of 2026-11-01
**Revisit when:** a chat should offer or withdraw a human's hands on its own

`chat_meat_proxy.parts` takes the lead part from the chat's value (the profile's while it is `null`) and the hands part from the profile, always. The participant entry carries both as `meat_proxy_lead` and `meat_proxy_hands`. `meat_proxy` stays "at least one part", as in §5.2, and the note and the resume packet follow it, so agents keep reading the hands part in every chat.

**Reason:** the entry used to carry only the derived value, so a profile with only the hands part showed the chat's switch as on. Asking to be led is about one conversation; being the first person to ask for a click is about the person, whichever chat an agent reads. Before this, `true` over a hands-only profile changed nothing, so nobody with that profile could be led in one chat, and `false` hid the hands from the agents as well. Two results change on purpose: `true` over a profile that is off now gives the lead part alone (it gave both), and `false` over a profile with the hands part keeps that part (it gave none).

**Rejected alternatives:**
- Redefining `meat_proxy` on the entry as the lead part: one field would mean two things between §5.2 and §9.3, and the resume packet would need another filter so as not to lose the hands.
- Changing only the page: the entry had no part fields, so the page would have had to parse the note's sentences.

## A watch reaches an event through a list fixed at write, added where every event is written

**Id:** 036f7df6-94c3-47e3-8852-17984b326859
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.4 "Audience" and §8.2 (contract #458), which fix the token, the private list and the per-reader `wakes`; the card tsk-9rbf4xt4ggzg; how the hub keeps that is this entry's reading
**See:** https://github.com/oliver-zehentleitner/maity — 95001efe-eb05-4bd0-af03-ffa42b6dbe9e — as of 2026-11-01
**Revisit when:** a new way to move a card's status appears, or the events move into a store that cannot join a second table

`events.emit` adds `watchers:<card>` to a `task_updated` with `status` among its fields and to an
`update` message, whether anyone watches or not, and writes the memberships watching then into
`event_watcher`. A read turns the rows of its batch into `watching:<seq>` beside the batch's other
hidden facts, and `wakes` takes the set as an argument. `_wakes` in `views.py` serves only the
reader's own entries of such an event, and nothing to a view without a reader. A claim, a release, a
report, a request that blocks or unblocks the card, and a holder's isolation or removal write a `task_updated` when they move the
status, after their own event, which never carries the token: a reader takes one event at a time
(`maity wait --one`) and sees what happened before what followed from it. A merge remembered while
the card was blocked is told after the `task_updated` of its return to `review`. A refresh writes none. The contract
names the report; the claim and the release are the coordinator's reading of §6.4's "a status
change" (2026-11-01), and a blocking request is this entry's reading of the same words. A redaction
and a deleted attachment take over the list of the event they are about, so they stay readable as
that event is (§8.5, §8.7). `event_watcher` is neither deleted nor exported: it references memberships,
whose rows stay, a member gone reads nothing more, and like a `member:` token in an audience it is
the history of whom an event reached.

**Reason:** the token must be there when nobody watches, or its presence would say that someone
does, and one place in `emit` covers every site that writes `task_updated`. A reader's watches
are read per batch, so an event without the token costs nothing and no card lookup runs at read.

**Rejected alternatives:**
- The token at each site that writes `task_updated`: a new site that forgets it silently reaches no
  watcher.
- The private list as a column of `event`: every read of the row would carry it, one serialization
  away from being served, and the contract keeps it apart.
- Resolving watchers at read: a watch begun later would reach earlier events, which §6.4 excludes.

## `member_updated` is read by everyone and wakes the member and the coordinators

**Id:** 67c594b0-ca9e-4ef6-a3d7-e684c38a1085
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** jour fixe of 2026-11-01 (round jfx-1h88k3dgtfy3), accepted by the owner; card tsk-7n4yx3yqj84d
**Revisit when:** a team needs to react to another member's change without being the coordinator

The audience stays `all`, so everyone reads the change; `member:<id>` and the coordinator's token
are added in `events.emit`, the one place all writers pass, and `events.wakes` ignores `all` for
this kind unless `changed` names `reports_to` or `owner_id` or the member was removed. A merge
ticker wakes a member named only as a card's holder at the holding instance.

**Reason:** every instance of every team woke on each bridge, dormant or team-rule change of anyone,
and each wake is a model run. A change of who reports to whom, an owner or a removal keeps waking
everyone, since addressing depends on them. The removal is this implementation's reading: the
round named owner and supervisor changes, and a removal ends an address too, and moves the reports.

**Rejected alternatives:**
- Narrowing the audience: others would no longer read it in the stream, which everyone agreed to keep.
- A list at each of the fifteen writers: a new writer that forgets it would wake everyone again.
- Waking the whole project on a rename: the old handle stays an alias, and a ticker item says it.

**Known limit:** `changed` is what decides; a writer that moves `reports_to` without naming it would
wake too few. `reports_to` moves through `members.apply_patch` and a removal today, and tests hold
both. Nothing changes an agent's owner yet, so `owner_id` holds the rule for when something does.

## A holder that stops is reported from the three places that stop it and a minute pass, and nothing is released

**Id:** 483be046-dbf5-4c2f-a9d4-cc18dfb09469
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.5 (contract #1292); card tsk-ehs8abh1arwg
**Revisit when:** a fourth way for a holder to stop appears, the hub starts releasing claims itself,
or a closed card can be reopened

`holder_stalled` is emitted in `hub/src/maity_hub/holder_stalled.py` from three hooks:
`auth.leaks.revoke`, the one function every revocation passes, when its update won and its
caller does not say `holder_moves`: a replacement (the claims move to the new instance) and a
member's removal (it releases them in the same transaction, so nobody is left to re-route) say
so. The removal is the hub's reading of §6.5, which names only the replacement. The replacement
moves the claims before it revokes (`_move_to_replacement` in
`hub/src/maity_hub/routes/joins.py`), so the old instance holds no open card by then and its
`holder_moves` guards against a reordering; this is why `hub/tests/test_holder_stalled.py` tests
`leaks.revoke` with the flag directly. The reason text never decides: the revoke route passes
the human's own words, which can be `replaced` too;
`availability.set_agent_limit`, only when no limit ran before (a moved `until` is no start);
and `not_listening.check`, in the transaction that starts the episode. `claim_expired` is a pass
the not-listening worker runs after its sweep, under the same worker claim: one event per holder
and instance for the leases that ran out, each lease once, held by `card.lease_expiry_reported`
(the `lease_until` the last event named; a renewed lease that runs out again differs and counts
again). Only open cards count, as for the lease renewal and the resume packet's `claims`: a
`done` or `cancelled` card keeps `claim_holder`, `claim_instance` and `lease_until`. The
migration marks the leases already expired as reported, so the first pass after a deploy does not
report every old lease at once. It leaves closed cards alone on purpose: the pass never reads
them, and the transition table of §6.4 (`cards.check_transition`) has no way out of `done` or
`cancelled`. A reopening would bring the holder's columns back with a lease that ran out
unreported, and the next pass would report it once; hence the Revisit line. The audience is
the one in §8.2: the member the agent reports to, else `trust:admin`, the owner when a member,
and the holding instance. `events.wakes` checks these two kinds before the dormant rule: only
the agent the holder reports to wakes, a dormant boss not (as for `member_not_listening`), and
the holding instance's `instance:` token never.
The session's columns are read through an outer join: an instance can hold a claim before its
first resume, and its revocation still decides `session_ended`.

**Reason:** a hook at each stopping point says it in the transaction that stopped the holder, with
nothing to poll; a lease runs out without any write, so only a pass can see it, and the minute
worker already runs per project under a claim. A column on the card keeps "once per expiry" across
restarts and replicas without a table.

**Rejected alternatives:**
- Hooking each revoke route: a new path to revoke would forget it; `leaks.revoke` is where all end.
- Deciding the silence by the reason (`replaced`, `member_removed`): a human revoking by hand can
  write either word, and the holder then stops unreported.
- A table of reported expiries: more than one row per card is never needed.
- Reporting every expired lease on the first pass after the deploy: a burst of old news.

**Known limits:** the lease renewal (`hub/src/maity_hub/auth/caller.py`) takes no project lock,
so a renewal can commit between the pass's read and its mark: the event then names a lease that
was just renewed, the column keeps the old value and the next expiry counts again; never a double
or a missed event. A lease renewed before the next pass is never reported (the minute is §6.5's
grain). The pass filters closed cards in its query, but no index serves that filter, so the
database scans every card with a holder, closed ones included, each minute; not measured, and no
index added (a partial index on open cards is not portable to MariaDB).

## The unread nudge scans each stay incrementally in process memory; exactness against a concurrent redaction is not promised

**Id:** 56357b6b-ff4b-40a2-b9d9-e1a073db80fc
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** the reviews of #1490 (tsk-xemkg9x1kwt8), 2026-11-08; the team lead's boundary decision for the redaction race and its later go for the one-statement check, the same day; the team lead's card tsk-tgh0st6p2zag (bounded database work and catch-up, the P3s left by #1490) and its go, the same day; `hub/src/maity_hub/chat_unread.py`; contract `docs/api.md` §9.2 "The unread nudge"
**Revisit when:** agents act on a nudge's `unread` or `oldest_seq` rather than reading the chat, the hub runs the minute worker on several replicas at once, a path redacts a project event without writing `event_redacted` in the same transaction, or another route by which a redaction stays counted turns up
**See:** https://github.com/oliver-zehentleitner/maity — f257b1f9-2af2-4d86-a7be-7277ae27b5e7 — as of 2026-11-08

The minute pass keeps, per agent stay in an open group chat, how far that stay's unread
messages have been read and the counted ones' number, first and last (`_Scan`), in this
process's memory and nowhere else. Each call reads only rows after the last one read, at most
`SCAN_BUDGET` (2000) event rows of the chat per stay, in batches of `SCAN_BATCH` (500),
selecting only seq, time, kind, the redacted flag, the author's human id and the mentions
projected from the payload. The nudge goes out only once a read reached its bound, so
its counts cover every message up to it. A moved read mark, or a redaction of a message in the
range already read (found through its `event_redacted`, below), starts the read over; entries of
stays that ended are dropped each pass.

**Updated 2026-11-08 (tsk-tgh0st6p2zag):** the two limits below that were left as P3s are
closed, and the paragraph after this one describes the state before. The database work of a
pass is now bounded per stay and call by the budget, not by the unread history: at most
`SCAN_BUDGET` of the chat's event rows of any kind, at most `SCAN_BUDGET` of the project's
`event_redacted` rows, at most `SCAN_BUDGET` events about the chat for the open cycle (both of
the last as corrected by the R1 note below), and one-row index reads (the read mark, the
chat's newest seq, the project's newest redaction); the aggregates `_counts` and `_oldest_human` are gone, and the delay is checked on
the oldest counted message the read found. A redaction is found through the `event_redacted`
event every redaction path writes in the same transaction: a read keeps a cursor on the
project's redaction events, and one that names a message of this chat inside the range already
read starts it over. A read's bound grows only once a call has reached it, and the call under
the project lock only confirms the range the pass found due, so a read covers a fixed range and
finishes at any arrival rate; the messages that came meanwhile are the next bound. Both are
tested, the first by counting the event rows a pass touches on PostgreSQL (`EXPLAIN ANALYZE`):
as many at 400 unread messages as at 10, where the aggregates touched 20 and 800. Who gets a
nudge, when, and its payload are unchanged, as is the boundary on concurrent redactions.

**Updated 2026-11-08 (review of #1512, R1):** two gaps in the update above are closed. The
read's limit counted human messages after filtering, so a range of agents' or redacted messages
was scanned in full for nothing, and the open-cycle check read every `chat_unread` above the
mark and filtered the recipient in Python. Now the limit counts every event row of the chat's
range, whatever it is, and the caller decides what counts; the open-cycle check reads on from a
cursor per stay (`_Cycle`) over the events whose subject is the chat, at most `SCAN_BUDGET` a
call, so another agent's nudges are read once. And a full batch of redactions used to stop the
message read before it moved; a stream of later redactions before each pass kept the read from
ever finishing. The redaction look now has a bound of its own that grows only once the look has
reached it, the read's bound grows only in a call whose look began and ended caught up, and the
nudge waits only for the look to catch up, so neither starves the other. The price: when the
project writes `SCAN_BUDGET` or more redactions between two calls, the look catches up over
several calls, and a redaction committed meanwhile may stay counted, the concurrent case this
entry already leaves open; the call under the lock after such a call confirms without looking
further (`lagging`), or it would fall behind again. Tested on PostgreSQL: with a budget of 5,
the first pass over 50 and over 400 events touches as many event rows for mentions, agents'
messages, redacted messages and another agent's nudges (the PR head before: 6/9, 52/405,
53/403, 103/803); later redactions at 2 and 3 a pass no longer keep the nudge back.

**Updated 2026-11-08 (review of #1512, delta 1):** the open-cycle check counted a full batch
as open, so two title changes a pass (`conversation_updated` shares the chat as subject), or
other agents' nudges, held it open forever and no nudge came. It now has the same bound as the
other reads: the chat's newest subject event when the check had caught up, growing only once
the check reached it, with the cycle counted open while it is behind, and the `lagging` rule
for the call under the lock. A nudge this process wrote lies below the next bound it takes;
that held for one process only, as the next note says. And the contract's exactness sentence
promised more than the code: after a call whose redaction look began behind, a redaction
committed before the pass may stay counted. The sentence in `docs/api.md` §9.2 is narrowed to
that, in the same separate commit as the budget sentence, so both go to the maintainer
together; removing the exception instead would bring back the starvation under a stream of
redactions.

**Updated 2026-11-09 (review of #1512, delta 2):** the caches are per process, and the worker
lease keeps a second worker out for cost, not for correctness (`hub/src/maity_hub/worker_runs.py`),
so a second worker's nudge can lie above this process's bound. After a lagging check the call
under the lock took no new bound and wrote a second nudge for the same messages (reproduced
with two processes on PostgreSQL). The call under the lock now also reads the events above the
bound, at most `SCAN_BUDGET` (as first written: the project's nudges, corrected in the next note),
and counts the cycle open on a nudge for this agent and chat; tested with a real second process.
And the exactness sentence said "between two of the hub's passes" where the code
counts the redactions between two of the read's calls, which can be several passes apart
while the open-cycle check is behind; it now says the hub's reads of the chat.

**Updated 2026-11-09 (review of #1512, delta 3):** the re-check read the project's nudges above
this chat's bound and counted a full batch as open; once other chats of the project had written
`SCAN_BUDGET` nudges above it, this chat never got one again. It now reads this chat's subject
events above the bound, newest first, at most `SCAN_BUDGET` by the subject index, and a full
batch without a nudge for this agent does not hold the nudge back. A second process's nudge is
committed just before this call takes the lock, so it is among the newest; a second nudge for the
same messages would need `SCAN_BUDGET` events about the chat between the two, which is left
open. Holding back on a full batch was rejected: a stream of title changes would then starve the
nudge, the case the delta-1 note closed.

**Updated 2026-11-09 (review of #1512, delta 4):** that residual was real: with the production
budget, 2000 title events between another worker's nudge and this lock pushed it out of the
window and a second nudge counted the same messages (reproduced with two processes). The open
cycle is now stored, the one exception to "nothing stored" above: per stay,
`conversation_participant.unread_nudged_through` holds the `newest_seq` of its last nudge,
written in the same transaction as the nudge under the project lock, and read with the stay by
`_candidates`, again under the lock before a nudge is written. The cycle is open while the read
mark is below it: exact across processes, one row the pass reads anyway, no read of the event
log. The cursor, its bound, the `lagging` rule and the re-check of the delta-1 to delta-3 notes
are gone with it, and their starvation cases with them. The migration
(`20261109140000_nudged_through`) fills the column from the nudges already written. The
EXPLAIN test now runs `ANALYZE` after cloning its backlog: without fresh statistics the planner
walked the index (project_id, seq) back over other chats' events instead of the chat's index.
The bound therefore assumes statistics as autovacuum keeps them on a live database; right after
a bulk insert, before it runs, a pass can read more rows than the budget.

What is guaranteed: no message body is read; the message rows read are bounded (`SCAN_BUDGET`
per stay and call), while the one-row aggregates go over the stay's unread range in the database
each minute, a cost that grows with unread history; every unread human message without a
mention leads to one nudge once the read has caught up. Each call moves the read's bound up to
the newest message and reads at most `SCAN_BUDGET` rows, and a read finishes only on a short
batch: while `SCAN_BUDGET` or more new human messages arrive in the chat between passes it may
never finish; with fewer, each pass gains on the backlog until a call reaches the end. A
redaction committed before a pass starts is left out. Bounded
database work and a catch-up that holds under any arrival rate are P3s for the hub roll-up. Beyond that, the check of the range already read, the bound and the
redaction count for an extension come from one statement (`_counts`, one snapshot even under
READ COMMITTED), taken before the rows under the bound; the call under the project lock compares
again, and a redaction takes the same lock. That closes the two routes the review found (a
redaction during a first read, and one while an earlier read's bound grows), each tested on
PostgreSQL. Exactness against a concurrent redaction is still not promised: the lead set that
boundary, since the nudge only wakes the agent, which then reads the chat, and the chat shows a
redacted message only as its tombstone (`docs/api.md` §8.5), never its body. Another route, should one turn up, is a P3 for the hub roll-up.

**Reason:** an offline agent's growing backlog, and a backlog that all mentions the agent and
so never leads to a nudge, were each read in full every minute (the first reviews); reading
only what came since, within a budget, removes that without a table or a migration. A restart,
or the worker moving to another replica, costs one fresh read per stay. Further rounds on the
race would have held the PR back for a count the agent does not rely on.

**Rejected alternatives:**
- Excluding the mentions in SQL, with JSON queries per dialect, so one aggregate gives the exact
  counts: a SQLite and a PostgreSQL branch for the first read only.
- A row limit with counts exact up to the bound: the contract would have to weaken its counts.
- Storing the scan in a table: a migration for state that one fresh read rebuilds. (The open
  read cycle is stored since the delta-4 note: unlike the scan, no bounded read rebuilds it
  exactly across worker processes.)
- Finding the open cycle in the event log with a bounded read (deltas 1 to 3 of #1512): a cursor
  over the chat's subject events could be starved by title changes, a window over the newest
  could miss a second worker's nudge behind enough of them, and a project-wide read could be
  filled by other chats; the recipient sits in the audience JSON, which no index reaches.
- Taking the extension's count in a second statement after the check: a redaction committing
  between the two was adopted into the new count while its message stayed counted (review of
  #1490, delta 3).
- Keeping the one-statement aggregates for the redaction check and the delay (tsk-tgh0st6p2zag):
  exact, but their cost grows with the unread history on every pass; the redaction events give
  the same check over redactions only.
- Moving the bound to the newest message on every call (tsk-tgh0st6p2zag): with the budget or
  more new messages a pass, the read never finished and the nudge never came.
- Filtering the recipient of the open cycle in SQL (review of #1512): the audience is a JSON
  list, so a per-dialect predicate, and without an index on it still a filter over the other
  agents' nudges each minute; the cursor reads each of them once.
- Reading every redaction before any message progress, in a loop within the call: exact, but
  unbounded under a stream of redactions; the bounded look with its own bound trades exactness in
  that case, which the entry already leaves open, for a read that always finishes.
