# Messages

## The project's messages are read from the hub's message listing, a page at a time

**Id:** 8e483bb1-53be-4ce2-a139-561989db21af
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §8.3 (events), §8.4 (message types), §8.5, §8.7 and §8.8 (the listing); the coordinator's card for the project messages view (tsk-3s4an5p22v4j), 2026-10-23; the card that moves the view to the listing (tsk-0m6qx612y5px), 2026-11-04, and the agreement with lotse that only the Messages view moves (project message seq 69405); measured in web/tools/smoke.js: a message more than 5000 `seq` behind the hub's head, unreachable for the old window, shows after paging back; and a live read over empty pages with a cursor reaches the new message (reviews of #1348, project message seq 69640 and 69731)
**Revisit when:** §8.8 gains a `wait` of its own, or the listing's page or scan budget no longer fits one opening
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-11-04

The Messages tab reads `GET /projects/{owner}/{slug}/messages` (§8.8):
its newest page of 50 when opened or when the type filter changes (the
filter is the hub's `type=`), and the next older page with the
listing's `next_cursor` behind **Older messages**. There is no window:
however far a message lies behind the hub's head, paging back reaches
it, at one request per page. The project's feed is only the signal, as
on the Ticker: a message event there reads the listing forward with
`after=` from the newest message shown (or from just below the first
that arrived, when none is shown), oldest first, following the
listing's `next_cursor` on that same `after=` and type until it is
`null`, at most 20 pages per round (a round out of pages leaves its
cursor to the next signal's round), and puts what is new at the top. Removals (`event_redacted`)
put the listing's tombstone in place of the message, or drop it from a
list filtered by type, since §8.8 lists tombstones only unfiltered;
deleted files are marked in place, and the listing says `deleted_at` on
a later read. A removed project message shows as a tombstone without
its reason; a removed chat message is never listed, as §8.8 says.

A page of the listing examines at most the hub's scan budget (2000
project messages, `hub/src/maity_hub/routes/project_messages.py`), so it
may be short or empty while `next_cursor` is set. The live read follows
`next_cursor` on the same `after=` until it is `null`, and an empty page
with a cursor is not shown as no messages: the list says older messages
have not been read yet. Reason: §8.8 makes `null` the only end of the
history. On #1348's head, a live read that stopped on a short page left
a new blocker unseen behind 2100 notices until reload (reviews seq
69640 and 69731). Rejected alternative: stopping on a page shorter than
`limit`, which misses what lies past the budget.

**Reason:** the scan of `/events` within the hub's latest 5000 `seq`
(4c3f8949) lost every message behind that window in a busy hub and read
up to 26 pages on every opening. §8.8 is the read for exactly this
view: the hub's audience rules, its type filter and its tombstones, at
a cost of one page per request whatever the history. The feed stays the
live signal because §8.8 has no `wait`.

**Rejected alternative:** keeping the window scan beside the listing:
two reads that disagree on tombstones and on what a filter shows.
Reading new messages from the feed's own payloads: the feed's
audience and shape are §8.3's, not the listing's, and a filter would
have to be applied in the page again. Hiding tombstones as before: the
scan hid them only because it could not tell a chat's from a project's;
the listing can.

## A review result shows its verdict, head and cites in the Messages view; the dashboard does not compose one

**Id:** 2ca8d25f-79db-47ea-9108-3397ad03296e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §8.4 "A review result cites what it judged" (contract #745: `review` with subject, head, verdict and cites, required on `review_result`, shown by the dashboard under the verdict); the card tsk-c4dez2qc7dd0 (verdict badge, subject, short head linking to the commit, cites as path:line or removed with the quote in monospace, folded after five), 2026-10-30; the coordinator's ruling to take review_result out of the composer, 2026-10-30
**Revisit when:** humans write review results in the dashboard, or a chat or a card's thread shows project messages

In **Messages** a `review_result` shows above its text the verdict as a
pill, the subject, and the head's first seven characters, linked to the
commit on GitHub or GitLab (title: the whole head); then the cites, each
`path:line`, or the path and "removed" where `line` is `null`, with its
quote as code text, the first five shown and the rest in a fold. Every
part is text, never markup. The Messages view is the one place project
messages are drawn; chats carry only `chat` messages, and a card's
thread its notes. **Message the project** no longer offers "A review's
result": the hub refuses one without `review`, and a review's cites are
quoted from the diff by the reviewer's tools (`maity say
--review-file`). The fixture hub's check of `review` is a copy by hand of
`hub/src/maity_hub/reviews.py`, not a second source for §8.4: where
they differ (reasons, unknown keys, which characters break a line), the
hub is right.

**Reason:** the lead checks the cites against the diff before an
approval counts; showing them under the verdict lets a human do the
same without the CLI.

**Rejected alternative:** a form for verdict, head and cites in **Message
the project**: a reviewer quotes lines from the diff at its head, which
a browser form would have them copy by hand, for a message humans do
not send. Leaving the type in the composer: every send would be refused
for want of `review`.
