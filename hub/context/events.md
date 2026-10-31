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
and come back on a later join. The places where access ends are few and already central.

**Rejected alternatives:**
- A pin valid while its `pinned_at` is after the start of the current access: every list would need
  each chat's access start, which the entries do not carry, and the 20 would still count dead rows.
- Pruning while reading a list: a `GET` that writes, and a list without `observed` cannot tell a
  chat read along from one no longer read.
- Keying by membership: an owner outside the project holds none, and the limit is per human.

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

`conversation_meat_proxy(human_id, project_id, conversation_id, meat_proxy)` holds a human's own choice for one chat, `true` or `false`; `null` deletes the row and the chat follows the profile. `chat_meat_proxy.shown` adds `meat_proxy`, `meat_proxy_chat` (only for the human reading) and, while on, `meat_proxy_note` to every human entry of the participants lists it is given, in the conversation view (`group_chats.view`), the direct item and both lists; the resume packet's `conversations[].meat_proxy` is read from the same entries. `PUT …/meat-proxy` emits no event. The account's deletion and export name the table.

**Reason:** a direct chat has no participant row (its id is the agent's), and the choice must work there as much as in a group chat, so a column on `conversation_participant` would cover only half. The same agent's direct chat exists once per project under one id, which is why the project is part of the key: a choice in one project must not switch the mode on in another. One function over the lists keeps the fields from drifting between the four places participants are built.

**Rejected alternatives:**
- A column on `conversation_participant`: no row for a direct chat, and a stay per join in a group chat that would lose the choice when the human leaves and comes back.
- Keying by conversation id alone: the same agent in two projects would share one choice.
- Emitting an event on a change: the contract has the agents read it on their next resume and wakes nobody; an event would reach every reader of the chat for what is context about a person.
