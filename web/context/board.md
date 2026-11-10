# Board

## Cards move by a Move menu and by dragging, only where the hub's transition table allows; nothing is drag-only

**Id:** c285771a-0b3a-4867-b66b-a1c7faa837de
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request for card management and drag and drop, relayed by the coordinator, 2026-10-22; web PR #126 and its review, 2026-10-22; re-checked by the coordinator after card order arrived (its revisit condition), 2026-10-22: the Move menu and the transition rule still hold, the order within a column is its own entry
**Revisit when:** the hub exposes the moves a caller may make
**See:** views.md#cards-are-placed-within-a-column-by-a-place-menu-and-by-dragging-over-a-card-and-the-order-changes-only-once-the-hub-answered — 3785a685-e976-400f-b088-9321804d29fc — as of 2026-10-22

Each card a human may move has a **Move** menu with exactly the moves the
hub allows them, mirrored from its transition check (proposed ↔ open for
the creator, holder or an admin; review → done or back with done
authority; cancel for an admin or an open card's creator). A pointer may
drag the card instead: while dragging, the allowed columns are outlined
and the others dimmed; a card let go over a refused column is said in
words on `dragend` (a browser fires no drop there) and nothing is sent.
Placing a card within its column is a separate move with its own menu
(see the entry linked above). The board's filters (member, area)
work on the cards already loaded.

**Reason:** a drag-only board leaves keyboard and phone users without a
way to move a card; the menu is the path for both, and dragging is a
shortcut over the same rule. Mirroring the table means the page offers
no move the hub would refuse, and the hub still decides.

**Rejected alternative:** offering every column and letting the hub
refuse — every refusal would be a round trip and a surprise. Filters as
query parameters to the hub — the board already holds every card of the
window, so filtering there is instant and needs no new contract.

## Cards are placed within a column by a Place menu and by dragging over a card, and the order changes only once the hub answered

**Id:** 3785a685-e976-400f-b088-9321804d29fc
**Type:** decision
**Status:** superseded
**Superseded by:** 6f06c1b3-656b-4631-aa2f-c9dff1f86556
**Evidence:** inferred
**Source:** the coordinator's card for card order (tsk-9cxxnmr3srx1) and docs/api.md §6.4, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub answers a move with the column's new order, or closed cards get a reason to be ordered
**See:** views.md#cards-move-by-a-move-menu-and-by-dragging-only-where-the-hubs-transition-table-allows-nothing-is-drag-only — c285771a-0b3a-4867-b66b-a1c7faa837de — as of 2026-10-22

The board draws each column in the hub's card order (§6.4). With
`tasks:admin` an open card has a **Place** menu next to **Move**, built
the same way: a select with only the moves its place allows (Move up,
Move down, To the top, To the bottom) and one button. A pointer can drag
the card over another card of its column instead; the pointer's half of
that card decides above or below, and a marker shows it while dragging.
Either way the page sends one `POST …/move` and shows the new order only
from the board read after the hub's answer. When a `not_found` or
`invalid` comes back, the board is read again: if the card and its
neighbour are still where they were, the hub has no endpoint; otherwise
the neighbour moved meanwhile. Done and cancelled cards are not placed.

**Reason:** the menu gives the keyboard and the phone the same way the
pointer has, as for Move. Waiting for the hub keeps the board from
showing an order the hub refused or changed, because the hub may rank
other cards of the column as well. Reading the board again after a
refusal is the only way to tell a race from a missing endpoint.

**Rejected alternative:** four buttons per card. They add four tab stops
to every card on a long board, and the menu already says which moves
exist. Reordering at once and rolling back on a refusal: a card that
jumps and then jumps back is worse than a short wait, and the card's
brief asks for the order only after the answer.

## A board card ends in one row of controls: a status menu, an assign menu and four Place arrows

**Id:** 6f06c1b3-656b-4631-aa2f-c9dff1f86556
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's board screenshot and his ask for Place as arrow buttons (tsk-jxexcfadmh54), 2026-10-23; the designer's layout for it, 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** a card gets an action that fits none of the three, or the board gets a card view of its own

Move, Place and Reassign were each a select with a button: three forms per
card. They are now one row at the card's foot: the status as a menu
button showing the card's column ("Move to <column>" items, only the
moves the hub allows), Assign as a menu of members by @handle, and Place as
four arrow buttons in a group ("Place in column"), disabled where the
card's place allows no such move. The assignee moved into the header as a
picture and @handle (the full name as tooltip and accessible name, a link
to the member). Picking a menu item acts at once; after a move or place
the focus returns to the same control, or to an arrow of the card that
still works. As before, dragging a card over another of its column places
it above or below that card, and the order changes only once the hub
answered (the Place menu's entry, which this one replaces).

**Reason:** three forms made a card about twice as tall as its content and
repeated the same three labels on every card; one compact row keeps the
board scannable. Arrows say the four places at a glance, where a select
hid them behind a second click. The header is where the eye looks for
whose card it is.

**Rejected alternative:** keeping the selects, only tighter: still two
steps per action and still three labels per card. A single overflow menu
for all actions: Place is used repeatedly while ordering a column, and a
menu per press would make that slow.

## A card opens as a panel on the board, not as a page of its own

**Id:** 254c3ddf-d7be-4e70-ad71-384a6eb3d36b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report of 2026-10-25 that a board card could not be opened on a phone (tsk-1tva2482j90b), and the coordinator's ruling the same day on the proposal; the dashboard's implementation, 2026-10-25
**Revisit when:** a card needs more than one screen of its own (sub-cards, a long discussion), or the board stops being the place where cards are worked on

A card's title links to `/<owner>/<slug>/tasks/<id>`, which was already the
board with that card marked. The board view now also opens the card
there as a panel: beside the columns on a wide screen, full width above
them on a phone. The panel holds the card as the board draws it,
controls included, and what the board leaves out: the description, the
links, the open notes with a form, the history. Close, Escape and Back
return to the board with the card marked and its title focused.

**Reason:** until then the dashboard had no way to open a card at all;
the description, notes and history were nowhere to be read, which on a
phone looked like a card that would not open. In place, the card keeps
the board's controls and their reload and focus handling, the columns
stay in view on a desktop, and the existing deep link and its marking
need no second route.

**Rejected alternative:** a page of its own per card: it would need its
own copy of the board's move, assign and place handling, and Back would
lose the board's filter and scroll. Expanding the card inside its
column: a column is too narrow for a description and a history, and
every board reload would close it again. A modal dialog: on a phone the
same as the panel, on a desktop it hides the board the card belongs to.

## A note is edited in place in the card panel; Remove asks its reason as a chat removal does

**Id:** 5260ca07-539c-40fb-bdcb-5cd21d3c181e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** PR #1227 (tsk-bj9yb4d8f2cg), part 3 of editing a note, and its review; PR #1243 (`base_version` and the conflict in the panel); PR #1268 (tsk-dprnjakk3ykh) and its four review rounds; PR #1391 (tsk-wvf8s7f44vz7, an open edit kept across a redraw of the list, with its focus and caret restored); contract in `docs/api.md` §6.16, §8.5
**Revisit when:** the dashboard gets a dialog of its own for reasons, or the list is drawn per note
**See:** https://github.com/oliver-zehentleitner/maity — 0e6b3b31-1656-4744-841d-d48f1899a7fd — as of 2026-11-03
**See:** https://github.com/oliver-zehentleitner/maity — 09c47db5-75b7-4636-8c49-0cc46c8c9d46 — as of 2026-11-03

Edit stands under a note for its author and for an owner or admin, Remove
for an owner or admin only; neither under a tombstone, and Edit not in an
archived project, where removal stays allowed. The edit replaces the text in
place; the reason field is required for someone else's note, optional for
one's own, and sent only when it holds text; a missing reason is said at the
field. Remove asks its reason with the same prompt loop as removing a chat
message. The tombstone says who and when, and the reason only when the hub
gives it. Each button names the note's author and date in its label, an
Escape the mention picker has taken leaves the edit open, and Add a note
is drawn once per panel and stays while the list above it is drawn
again: the field keeps its text, focus and caret, a post's busy state and a
refusal stay in sight, also after a later read fails (when the first read
fails there is no form yet, as before). The list stays as drawn while it is
read, only the latest read replaces it, and its Edit and Remove wait
meanwhile (`aria-busy`). On a post's success exactly the text sent leaves
the field; anything typed since stays. After an edit, a removal or a post
the focus moves on only if it is still where that action left it. An edit
already open keeps its row across that redraw (a post, a removal, another
edit ending): the same form and the text typed into it stay, and when the
edit held the focus at redraw the same field and caret come back, so a post
does not move them into Add a note; a reader who moved focus elsewhere
during the read is left alone. Cancel or a successful save drops the form
before the next read; a note gone as a tombstone ends the edit. An edit and a removal name the
version they were made on (`base_version`); a conflict shows the note as it
is now and keeps the writer's text for the next save, and a note removed
meanwhile ends the edit, says the text was not kept, and puts the focus on
its tombstone, as a removal of one's own does. The public card page shows an
edited note's mark as the hub's own page does (§16.9): the editor named as a
holder, the date and the reason, never the old text, none on a removed note.

**Reason:** the buttons follow who the hub lets act, so nobody meets a
refusal for a button that should not have been there; an empty reason is not
sent, so the edit mark of one's own note stays without one, as §6.16 has it;
one way of asking a removal's reason in the whole dashboard; a note is posted
once, however the list is drawn again around its post; an open edit is the
writer's draft of that note, so a redraw of the list must not throw it away.

**Rejected alternatives:**
- Showing Edit to every reader and letting the hub refuse: a button that
  always fails for most readers.
- Clearing Add a note after every post whatever it holds: text typed while
  the post was on its way would be lost.
- Drawing Add a note again with the list and carrying its text over: each
  variant reviewed on #1268 lost something, the text sent came back into a
  free form (a second post one click away), the focus and caret went, a
  refusal vanished with a failed read. A form drawn once has none of it.
- Keeping an edit begun on the list being read: the list drawn after the read
  would have to merge it in; Edit and Remove waiting for the read is simpler.
  That lock covers only an edit begun during a read; an edit already open is
  kept by holding its row across the redraw (tsk-wvf8s7f44vz7).
- Making Edit wait while a post or a removal is in flight: disabling Edit
  only stops a new edit from beginning — it does not stop typing in an
  already open textarea, and that open edit would still lose its row on the
  redraw. Keeping the open row lets both run, and restores its focus when it
  still held it.
- Always sending `reason`, empty for one's own note: an empty reason would
  read as a given one.
- A dialog of its own for the removal's reason: a second pattern beside the
  chat's prompt for the same act.

## A report's why links its entry's file at the reported head; the dashboard builds the link

**Id:** bae95d1f-f84a-4261-ae51-6a0f7f51296a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.23 and the maintainer's card for the web side of the Keep the Why commitment (tsk-bq6q65910g13), 2026-10-25; the dashboard's implementation, 2026-10-26
**Revisit when:** the hub sends a URL for the why, a forge other than GitHub is supported (§11), or the probe reads the entry at the head

A code report's `why.ref` (`<path>#<id>`) shows under the report as a
link to `<repository url>/blob/<head>/<path>`, with the entry's `#<id>`
beside it as text; `why.none` shows as "No why: <reason>". The link is
made only for an https repository, a 40-hex head and a relative `.md`
path without `..`; anything else stays as code text.

**Reason:** the contract carries the reference, not a URL, and the hub
reads no repository for it. At the report's head the file is the one
the review saw, not whatever the default branch holds later. The
entry's Id is no heading anchor on the forge, so a fragment would point
nowhere; it is shown for the reader to find.

**Rejected alternative:** linking the default branch: the entry may move
or change after the merge. A fragment with the Id: no forge renders it as
an anchor. Waiting for a hub-made URL: none is in the contract.

## A subtask stands folded under its parent, whatever its column

**Id:** 23a3cfe8-e3ca-461b-b1a5-58ec070f4366
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.4 ("the board shows children collapsed under their parent with the open/total count and a child whose parent is outside its window as a card with a parent id") and the card for the web side of subtasks (tsk-cgsrvvk0qx9p), 2026-10-25; the dashboard's implementation, 2026-10-26
**Revisit when:** the tree gets deeper than two levels, or columns need to count children (the designer's pass on the folded row)

A child whose parent is on the board in the current view is drawn only
under its parent, behind a toggle with the hub's `children` counts,
and not in the column of its own status; it is not counted in that
column's number nor placed in its order. A child whose parent is not
shown (outside the board's window, or filtered away by column, member,
area or search) stands in its column with "Subtask of <id>". A link to a
folded child unfolds its parent and marks the child's row.

**Reason:** the contract asks for children collapsed under their parent;
a child also shown in its own column would be on the board twice, and
the column order (Place, dragging) is about cards that stand there. The
counts are the hub's, so a child closed outside the window still counts.

**Rejected alternative:** children in their own columns with a parent
badge: no folding, and a parent's open work spread over four columns.
Folding only children of the same column as the parent: a parent in
review with an open child would hide nothing, the common case.

## Reading again only what changed: a card opened on the board, a stream answer without a chat

**Id:** c5a75e7f-8c0e-443a-a7b3-874044713f60
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the performance measurement on tsk-a5pxwgkgr73e (step 1, item 7, 2026-11-08: the members read about every 0.6 s beside an opened card, `/me/conversations` every 0.4–3 s); the plan on tsk-d61rvjm6gteh, approved by the coordinator the same day; reproduced in the fixture hub
**Revisit when:** the board reads its cards per column or keeps them across renders, or the hub offers a per-user chat stream
**See:** https://github.com/oliver-zehentleitner/maity — 254c3ddf-d7be-4e70-ad71-384a6eb3d36b — as of 2026-11-08
**See:** https://github.com/oliver-zehentleitner/maity — dc0a02f8-c657-406a-8f63-f260b588e7e8 — as of 2026-11-08

Opening a card on the board changes the address, and every change of the
address was a full drawing: the whole card list again (six pages of 200 in
a project of 1,135 cards), the roles, the event head, the counts, and
behind it the session, `/me`, the project and its members. Clicking
through cards read the members once a card. Now the board follows a card
opened or closed on itself (`ctx.followRoute`, as `/chats` does): it swaps
the panel, and only the panel reads (the roles, the card's notes and
history, and where they apply its watched updates and restricted text);
closing it reads nothing. A hub answer to an edit made there is written
into every copy of the card the board holds, matched by its id, so the
next card opened or closed draws it as it is now, and an answer that comes
after another card was opened changes its own card only. A card the filters hide, or one outside the board's window, is still
drawn afresh: that drawing shows it whatever the filters say, as a link
from elsewhere always did.

The global chat read every project's chats and the open conversation again
on every answer of the notifications stream. That stream answers for every
item in every project (a request, a sign-in, a long-poll that only timed
out), and the counts were read every 15 seconds too, which also nudged
it. Now it reads only for an answer with a chat or mention item in it, or
one that moved the chat counts. Everything else waits for the 30-second
round, which was there already, with one exception: a group chat read
along as an agent's owner brings no chat item and moves no count (§9.3),
so while one is open, the 15-second counts read refreshes it as before
(web roll-up 3, a post-merge review of #1527). One's own message sent from
another tab comes with the round.

**Reason:** each of these reads costs a round trip and hub statements for
data that did not change. On the measured hub they added up to the
repeated reads beside every opened card and in the chat.

**Rejected alternatives:**
- Keeping the board's list in `kept`, as the project and its members are
  for a switch: a list of a thousand cards held across views, and stale
  after any move made elsewhere; the event feed already offers a reload.
- Slowing the chat's nudge (a longer settle time): fewer reads per burst,
  but still a full round for an answer that is about no chat at all.
- Dropping the stream nudge and keeping only the 30-second round: a new
  chat message would wait up to 30 seconds in the open conversation.

## The board reads its column groups side by side

**Id:** 145f0bf3-3024-414a-8026-19dad1960ff7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the performance measurement on tsk-a5pxwgkgr73e (step 1, 2026-11-08: six serial pages of 200 for 1,135 cards, 1.37 s, 2.8 s with gaps); the plan on tsk-d61rvjm6gteh (PR B), approved by the coordinator the same day
**Revisit when:** the contract gains a card status, the hub serves a larger page or the whole board in one answer, or the board reads only the open columns at first

The board asked for every card of its window in one list (`status=all`
with `closed_after`), page after page, each page waiting for the one
before. It now asks five groups at once: `proposed`, `open`,
`in_progress`, `blocked,review`, and `done,cancelled` with the closed
window. Each group follows its own pages. The board orders every column
itself, so the groups may answer in any order. Five reads are not one
snapshot: a card moved from a group not yet answered into one already
answered would be in neither, and one moved the other way in both. So once
all five have answered, the board reads the cards changed since a minute
before the reads began (the start taken on the hub's clock, the minute a
margin for its skew): `status=all` with the window and `order=updated`,
newest first, pages of 50, until the first card older than that. Each card
it returns replaces or adds its card. That read pages by an `updated_at`
keyset, and a card changed again between two of its pages moves ahead of
the cursor. So a pass that followed a cursor is followed by another from
the first page, taking every card at least as new as the newest the pass
before saw. The comparison includes that time itself: a card changed in
the same second as the newest one is recovered too. A pass of one page has
no gap and ends the reading. After three passes that each followed a
cursor, one list of every status in the window (`status=all` with the
window, all its pages) is read instead and replaces the cards.
What is guaranteed: every card that did not change during the reads is
shown as its group read it, and every card that did is shown once, as the
last pass, or the one list, has it. The one list has the gaps between its
own pages that the board always had. A change after the last read is the
board's usual news, offered as a reload. The reload after a write reads the
same way; the hub search still asks one list over every status
(`status=all&q=`).
When the board falls back to the one list: when all three passes followed
a cursor, that is, when cards keep changing while the passes read, or when
the cards at or after a pass's start fill its first page and more cards
follow in the window (for example many cards changed in the same second).
The cost: one request per group, each following its own pages, then the
changed-cards read, whose passes each read pages until a card older than
their start or the end of the window, and where all three passes followed
a cursor, the one list with all its pages. At most five requests are in
flight at once. The wait is the longest group plus the changed-cards
read's pages, one after the other, not the sum of every page.

**Reason:** the pages were the board's longest wait, and nothing in one
page depends on another. Side by side, the wait is the longest group,
not the sum.

**Rejected alternatives:**
- A larger `limit`: fewer pages, but a contract change, which this card's
  boundary excludes.
- The open columns first and the closed window after them: the board
  would draw twice, and its closed columns and counts would change under
  the reader.
- One request per status: seven instead of five, for groups (`blocked`,
  `review`; `done`, `cancelled`) that are small next to the rest.
- Reconciling from the project's event feed (the cards a task event names
  during the reads): a reader who is neither owner nor admin is in few
  events' audiences (§6.11), so a move could stay unseen. The changed-cards
  read depends on no audience.
- One list again whenever the board fits a page: the first page decides,
  so every larger board waits for it before its groups start.
- Falling back to the one list whenever the changed-cards read pages: more
  than 50 cards changed during the reads is rare, and when it happens the
  first page read again finds what moved ahead of the cursor for one more
  request instead of a whole list.

The group lists name the contract's seven statuses (§6.4). A status the
contract adds would not be read until the board names it; the board's
column for an unknown status stays for a hub that sends one anyway.

## On a phone an opened card is a page of its own; the panel is the card

**Id:** 54f93a4f-7e91-4d69-9b51-ca562daaa9a3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's pass part 2 (#6473, tsk-qk24j4ebxdwg), 2026-10-27: on a phone the panel opened above the whole board, making the page about 6,700 px long; the panel showed a frame and the card's id twice
**Revisit when:** a card gets a route that is no board at all, or the board is drawn differently on a phone

At 600 px and below, while a card is open, the board's columns are
hidden and the panel stands alone; **Close**, Escape and Back return to
the board at the card. On every width the panel is the card: one id, in
the bar beside Close; the title is the panel's heading, where the focus
goes; the card inside has no frame of its own; its controls stand right
under the claim line.

**Reason:** a panel above a long board turned an opened card into an
insert in a page nobody could find the end of; as a page of its own it
reads like one.

**Rejected alternative:** a separate card route without the board: the
board's filters and scroll, kept for the way back, would be lost. The
panel above the columns, as before: the length of the page.

## A watch in the opened card: the toggle, and the updates read from one page

**Id:** 7a86a9ca-fd3b-472f-b54d-486f5a82a70f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.4 and §8.8 (contract #458); the card tsk-hvgggzkf08rj; how the dashboard shows it is this entry's reading
**Revisit when:** `GET …/messages` gets a card filter, or a watcher misses an update older than the newest page

The opened card has a Watch button for every member. The answer to `PUT`
or `DELETE …/watch` is the card, which the board draws with a Watching
mark. `invalid` with `reason: implied` keeps the watch and says why. While
the reader watches, the panel lists the card's `update` messages from the
newest 100 of `GET …/messages?type=update`, filtered by `task_id`, and an
empty list says "among the latest messages" while the page has a
`next_cursor`. The status changes a watch brings are in the history already.

**Reason:** only the hub knows a card's dependents for this reader, and
the view has one `watching`, so the implied case shows when it is refused.
§8.8 has no card filter, and one page bounds the read. The page has a
second limit: the hub examines at most `SCAN_BUDGET` events (2000) for it,
so a sparse filter can end a page early with a cursor. An older update of
a busy project can be missing from the list; the event reached the watcher
when it was written.

**Rejected alternatives:**
- Paging through every update for each opened card: the hub scans a
  project's messages for it, for each card opened.
- A card filter on `GET …/messages`: a contract change, not part of this
  card.
- Merging updates and status changes into one list: the history has its
  own shape and pages, and already holds the status changes.

## A card's needs is a tag, a field in the two card forms and a filter over what the board has loaded

**Id:** 053b2259-181f-4545-a58c-fe2cb27ed5a9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.4 ("shown on the card and filtered on"); the hub's #1025; tsk-10ptyz8kf63p

The card shows `Needs: <role>` beside its label. It is set in the new-card form and, for whoever may edit the card, in the opened card's form with parent and related cards. The board's filter offers the roles its cards name now and works on the loaded cards, as Area does; it does not call `needs=`.

**Reason:** the filter sits with Member and Area, which read the same loaded list, so one rule says what the filters see. A list of every role would offer choices that match nothing.

**Rejected alternatives:** a server filter with `needs=`: a board redraw would have to merge a second list for one of its filters. A form of its own for needs in the opened card: the card has one edit form, and two would each need a Save.

## Under two signatures the board's Done is a signature, and only the menu can say which one

**Id:** 2668871f-769c-445b-94e1-f8802fa8e57e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.1, §6.4 (`approvals`, `approve`); the hub's #1028; tsk-tx9qcehevfnk

A card in review under `done_authority: reviewer_and_tester` lists both places, signed or not. The Move menu offers the signatures the caller may still give, named as signatures rather than "Move to Done". A caller with one signature left may also drop the card on Done, which sends that signature. A caller holding both, such as an owner, cannot drop it there. Someone who has signed one place is offered neither, and rework still is.

**Reason:** the hub refuses a call holding both scopes without `approve`, and a drop cannot ask. "Move to Done" would also be untrue, because the first signature leaves the card in review, so the status line says the signature was saved and the card waits for the other one.

A place another member filled is not offered, though the hub would answer `200` with the signatures unchanged: a menu item that does nothing would mislead.

The project's Settings offer every `done_authority` of §6.1 to a human admin, with a reason as for every policy field, so the rule can be set where it is read.

**Rejected alternatives:** a dialog on drop that asks which signature: a second way to do what the menu does. A separate Sign button on every card: the card already has one menu for what can be done with it. Settings only through a preset: the rule would not be settable where it is read.

## Before a way into the restricted-access set, the page says who will read, and no more than it knows

**Id:** c6ad8006-f67b-4cfe-a383-7141ca7dfb8b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-g8ts5vxhj1md, Web 2 (2026-11-07): the plan with three questions to the lead and the lead's answers on the card; docs/api.md §6.1 "Every way into the set" and "Reading the setting"; the review of #1450 (2026-11-07) for the returning accepter and the agents a transfer seats; `hub/src/maity_hub/restricted.py` `resolve`, which reads the list by member id
**Revisit when:** the hub serves a reader without `members` more of the set, an organisation's invitation carries what its go would bring into a set, or an owner change of an agent profile is built
**See:** refresh.md#the-restricted-access-sets-notice-is-a-projects-setting-read-by-a-read-mark-though-its-target-says-settings — aefe70f5-509b-47ea-9768-02623c68016a — as of 2026-11-07

Where the dashboard creates a join or a project invitation, raises a guest, ends an isolation,
transfers a project into an organisation, promotes a human to an organisation's owner, or shows
an organisation's invitation or transfer for its go, it says beforehand who will read the
project's restricted texts (`M.restricted.ahead`, `aheadOrgOwners`, `aheadOrg` in
`js/restricted.js`). The set before and after the action comes from the same resolution as the
setting's own widening preview. The join and invitation forms show it as a line that follows the
form. A raise, a lift, a transfer and a promotion ask with `window.confirm`. Nothing is said
while the set names nobody.

The wording follows what the reader is served:
- A human with `project:admin` gets the list, so the page names who enters, with the count of
  cards with a text.
- A reader served `{mode, included}` alone sees no list (§6.1 "Reading the setting"). Under
  `all_except` the page says "unless the restricted-access list leaves them out". Under
  `nobody_except` it says "may read, if the list names them". The reader's own place on the list
  comes from `included`.
- An organisation's invitation and a promotion to owner reach projects whose settings the page
  does not read. There the page says one general sentence: an owner may enter a project's set.
- Whoever accepts a project invitation is not known beforehand and may be a former member: the
  same id comes back, and the list, never pruned, may still hold it. While the list names
  someone who is no member now, or the reader sees no list, the line says "if the list names
  them" or "unless the list leaves them out" for the accepter; otherwise the accepter is new
  and treated as on no list. The accepter may also be the owner of an agent that stayed a
  member after its owner left (not isolated, §6.1 "Every way into the set"), which comes back
  into the set with its owner. The page names such agents the setting would let in, "if their
  owner is the one who accepts", rather than marking the accepter as listed, which would name
  the wrong reader.
- A transfer into an organisation seats its owners, and with them their agents: an agent of the
  project that is out of the set only because its owner is a guest or no member may enter. The
  page knows those agents and names them, "if their owner is one of the owners".

**Reason:** the contract asks for the sentence at each of these places, and a sentence the page
cannot know to be true would be a false one. A reader without the list cannot tell whether an id
is listed, so the wording says exactly that.

**Rejected alternatives:**
- Treating whoever accepts an invitation as a new id that no list names: wrong for a former
  member whose id the list keeps, who would enter under `nobody_except` with no word said.
- Leaving agents out of the transfer's sentence: a listed agent whose guest owner becomes an
  owner enters the set unannounced.
- "Will read" under every mode for a reader without the list: under `nobody_except` it is false
  for anyone the list does not name.
- Saying nothing where the list is unknown: the contract asks for the sentence, and under
  `all_except` the member does enter unless listed.
- A hub field on an organisation's invitation counting the sets its go would enter: a hub change
  for a sentence the general wording already gives honestly. It can follow as a card of its own
  if wanted.
- Reading every project of an organisation before a promotion: one request per project for one
  confirmation, and its owners are not always admins in each of them.
