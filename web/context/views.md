# Views

## The inbox is the first screen; board, agents, organisation and chat follow in that order

**Id:** a8f4ac34-b7be-47f0-aaec-dc494e6c2080
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's task brief and the maintainer's chat requirement, 2026-10-21
**Revisit when:** the first weeks of use show the human opening another view first
**See:** https://github.com/oliver-zehentleitner/maity — 6242e7ce-4c5c-42fc-b787-d506f1abc9ea — as of 2026-10-21

The dashboard opens on the inbox, and the navigation lists the views in
the order of their importance: inbox, board, agents and presence,
organisation, chat. The inbox works one entry after the other: the first
open request is expanded with its context (task, what the agent tried,
the options it sees) and its answers (prepared replies, free text,
"neither — let's talk"); answering moves on to the next. The chat with
an agent the human owns is the channel beside the inbox, reachable from
every inbox entry and every agent card, never the landing page. The
project state (build, freeze, fixes-only, accepted, archived) sits in the
header of every screen.

**Reason:** the root decision makes the inbox the human's primary
surface; the dashboard's order follows from it, and an entry has to carry
its context because the point is that answering does not require a chat.
The project state belongs on every screen because a freeze changes what
any answer means.

**Rejected alternative:** the board as the landing page, the default of
task tools — it shows what is happening, not what waits for the human.
The chat as the first screen — rejected at the root level; added as view
five on the maintainer's requirement, as a channel and not as the way the
project is run.

## The organisation tree is computed from reports_to and scope ownership, never stored

**Id:** 5fd2c906-3178-4b74-a1da-82a613302536
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's task brief, 2026-10-21
**Revisit when:** an organisation model needs a relation that neither `reports_to` nor scope ownership expresses

The organisation view builds an indented tree in the browser from the
members the API returns: each member sits under the member it reports
to; a member without `reports_to` sits under the owner of the narrowest
scope that contains its own; the rest are roots. Nothing chart-shaped is
fetched or kept.

**Reason:** set by the brief; the reason is inferred: a stored chart is a
second copy of the memberships and drifts from them the first time a role
changes, while a computed one shows exactly what the policy acts on.

**Rejected alternative:** a stored org chart edited on its own — the
drift above.

## Several projects: a switcher on every screen, and the cross-project inbox as the landing page

**Id:** b8378331-be5c-4349-96ab-ed44a8563c4e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's multi-project requirement, relayed by the coordinator, 2026-10-21; the dashboard's implementation, 2026-10-21
**Revisit when:** a human with many projects finds the switcher row too long, or asks to land on one project
**See:** views.md#the-inbox-is-the-first-screen-board-agents-organisation-and-chat-follow-in-that-order — a8f4ac34-b7be-47f0-aaec-dc494e6c2080 — as of 2026-10-21

One account holds many projects. The header of every screen carries a
project switcher: each project with its state and the number of open
requests waiting for this human, plus "All projects" with the total. The
cross-project view (`#/all`) is the inbox across every project, each
entry labelled with its project and that project's state, answered in
place. Opening the dashboard without a route lands there when the human
belongs to more than one project, and on that project's inbox when there
is only one. Everything else lives under `#/p/<slug>/...`.

**Reason:** the requirement is that the human sees from anywhere that a
project needs them; a count beside every project name does that on every
screen, and a landing page across all projects keeps "the inbox is the
first screen" true when there is more than one inbox.

**Rejected alternative:** landing on the last project used — it needs
remembered state, and it hides what waits elsewhere behind the switcher
on exactly the screen opened first. A project chooser as the landing
page — one click more before the first answer, and it shows counts but
not the requests themselves.

## A join's state comes from its fields and the hub's clock; Revoke stays a minute past expiry

**Id:** b8c3a4f4-1e21-4de1-9a82-7abe86456259
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report of an expired join still listed as open, relayed by the coordinator, 2026-10-22; web PR #107 and its review, 2026-10-22
**Revisit when:** the hub sends a join's state itself, or a join's lifetime becomes much shorter than a minute

Join an agent lists each join with the state its fields give, in the
hub's order: revoked, used, burned (three wrong codes), expired; open
joins first, the others muted and labelled. Expiry is judged by the
hub's clock: this browser's clock corrected by the `Maity-Server-Time`
of the last answer (docs/api.md §1.2), re-judged every 10 s while the
view is open. A join that expired less than a minute ago keeps Revoke,
and a Revoke the hub refuses (`invalid_transition`) is said and the list
re-read.

**Reason:** Revoke is the safety valve for a leaked line. A browser whose
clock runs ahead would hide Revoke while the hub still accepts the line;
the hub's time, and a minute's grace in which the hub decides, keep the
valve where it is needed. The order mirrors the hub's, so the page never
calls "expired" what the hub calls "used".

**Rejected alternative:** the browser's clock alone — wrong by the
client's skew, which on a laptop can be minutes. Hiding Revoke exactly at
`expires_at` — the second the hub and the page disagree is the second a
leaked line is pasted.

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
**Status:** active
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

## A membership is edited in one form and sent as one PATCH of what changed; a reports-to circle is refused before it is sent

**Id:** ae257555-b3a4-4ba7-add3-1ab051c1f621
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request to set reports_to and areas from the dashboard, relayed by the coordinator, 2026-10-22; contract PR #118 (cycle), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub offers the edit as separate endpoints, or a membership gains fields that need their own confirmation

Members → Manage holds one form for what docs/api.md §6.2 lets an admin
change: role (owner only for a human), reports to (nobody or another
member), areas (repository paths, the hub's pattern, never `..`),
capabilities (`tag`). The briefing has one editor, on the agent's card,
and is sent as typed. Save sends one `PATCH` with only the fields that
changed; edits not yet saved are kept per row across redraws (Done drops
them), and a 202 (a consent request, when a human's go is needed) is said
as waiting, the draft dropped and the form drawn from the hub's state, so a
second Save files no second request. A drafted boss who has left the
project since is dropped and said at the field: a select that silently
fell back to "nobody" would send `reports_to: null` and clear the boss the
member has. A
reports-to that would close a circle is refused before sending, in the
words the hub's `cycle` refusal also gets. Capabilities the page does not
offer are kept as they are.

**Reason:** one form keeps an admin's change atomic (the hub applies it
in one write) and the organisation view follows at once. Refusing a
circle in the page spares a round trip and says why; the hub refuses it
too. Keeping unknown capabilities means an older page never strips what a
newer hub added.

**Rejected alternative:** one control per field with its own Save — a
role and a reports-to change that belong together would land as two
writes, and a failure in between leaves half a change. Sending every
field every time — a stale form would overwrite a change made meanwhile.

## The chat's history: days apart, a sender's run grouped, and the line before what was unread when it opened

**Id:** abe93ad2-1a75-4abc-a5d0-70e074d17335
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's chat feedback relayed by the coordinator, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub gives a conversation a read marker of its own (then the line comes from it), or group chats need another grouping

The open chat draws its history with a separator per day ("Today",
"Yesterday", else the date), groups a sender's messages that follow
within five minutes (the picture and name only on the first), and puts a
"New messages" line before the first of the agent's messages that were
unread when the chat was opened. The history is read to its end, in
pages of 200, because the hub returns the oldest page first and the
unread messages are at the end. A button back to the newest shows when
the human has scrolled up, with the count of what arrived meanwhile;
someone else's message never moves the view, and the button hands the
focus to the composer when it goes. An unread count that cannot be read
draws no line and is said.

**Reason:** the hub marks a conversation read when its messages are
returned (docs/api.md §9), so the unread count has to be read from the
conversation list before the messages are; that count is "the agent's
last n messages", which is where the line goes. Five minutes keeps a
burst of an agent's replies together without merging separate exchanges.

**Rejected alternative:** a "new" line kept from the last visit in this
browser — it would disagree with the unread count the list shows, and
another device would never see it. Grouping by a fixed number of
messages — a long pause would hide that the agent came back later.

## Project → Runners is the project admin's tab; refreshes redraw in place, and a missing list fails loud

**Id:** 1cf107b2-991d-42e4-aa35-9dd8f84216eb
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §15.3 and §15.4; the review of web PR #96, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** humans other than the owner can join a project (then a runner's owner may not be its admin), or the hub sends events for runners' presence or placements

The tab is offered to owner and admin only (`members:admin`), although
the hub also lets a runner's owner detach it. In V1 the only human is
the owner, so nobody is left out yet. Allowing is the hub's grant; the
runner checks its own `[limits] projects` again. A runner the hub allows
but whose configuration does not list the project is therefore warned
about: it starts nothing here.

Presence and placements send no events, so the view re-reads every 30
seconds. A card is redrawn only when its data changed, the focus stays
on the same control, and the Allow form is rebuilt only when the set of
free runners changes, keeping the runner chosen. Detach reads the count
of agents again before it asks. A 404 on the list is an error like any
other: the dashboard ships with its hub, which has attachments.

**Reason:** a redraw every 30 seconds that rebuilds the form takes the
choice and the focus away from someone using a keyboard or a screen
reader, and an Enter after it could allow the wrong runner. A 404 that
reads as "not yet" would hide a broken route now that the hub has it.

**Rejected alternative:** the tab for every member, with Detach where
the hub allows it. In V1 that only adds a view nobody else can use, and
an Allow nobody but the admin may send. Treating a 404 as an older hub:
that was right before the hub had attachments, and today it only
covers a regression.

## In the cross-project inbox, the project's badge is a link beside the entry, and its name starts the entry's own name

**Id:** e356660d-570b-47ec-9ba1-70b5bad4224d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's feedback that entries of all projects were hard to tell apart, relayed by the coordinator, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the entry head is no longer one button, or the cross-project view gets a layout of its own per project

Every entry of `#/all` has its project's badge (logo or monogram, name,
state) before it, as a link to the project's inbox; the entry's head
button starts with the project's name, visually hidden, so that the
button's own name says which project it is. A project filter and an
optional grouping by project (sections in the switcher's order, each a
heading with its own list) sit in the toolbar; both are kept only for
this tab's session and apply to `#/all` only, never to a project's own
inbox. The entry opened first and the one opened after an answer follow
the order on screen, filter and grouping included.

**Reason:** a link may not sit inside a button, and the head is a button
(it opens the entry); so the badge stands beside it. A screen reader
moving by buttons would then miss the project, hence the hidden prefix.

**Rejected alternative:** the badge inside the button, as before — it
cannot be a link there, and its place after the priority read as just
another label. An `aria-label` on the button — it would have to repeat
the visible text word for word (axe label-content-name-mismatch).

## The overview is the second tab, redrawn in place, and its counts failing leaves the rest standing

**Id:** e585b67d-8a1a-4e68-8ea7-814ec4fbc251
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the overview contract (docs/api.md §6.11, PR #189) and its contract owner's rulings, 2026-10-22; the coordinator's card for the view (tsk-hha96xyqcpdd), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the overview gains merges from the change ticker (#180) or releases, or the inbox stops being the landing page

`#/p/<slug>/overview` gets the tab right after **Inbox**, while the inbox
stays the landing page. The view is five parts: links, members, board
counts, open requests and the latest reports. Links and members come
from what the header already holds. The counts come from one
`GET …/overview` with the board's window, read again on `task_*`,
`request_*` and `probe_observed` and redrawn in place, with no Reload
offer. A viewer who is neither owner nor admin is in few of those
events' audiences (§8.2), so for them the view also re-reads every 60
seconds and when the tab or its window comes back. A trigger that arrives during a
read causes one more read after it, and a redraw puts the focus back on
the same link. If that call fails, links and members still show, and the place
of the counts says why they are missing.

**Reason:** the inbox is where the human acts. The overview is where
they look first after a while away, so it sits next to the inbox
without replacing it. A summary is not read line by line, so redrawing
it does not pull text away from a reader, which is why the contract
asks for it in place. Links and members do not depend on the new call,
so one missing endpoint should not blank the page.

**Rejected alternative:** the overview as the landing page. The contract
keeps the inbox there, and what waits for an answer matters more than a
summary. The board's "changed, Reload" notice would interrupt nothing
worth protecting here. One error for the whole view: it hides what the
page already has.

## Group chats live in the chat view's own two panes; the hub says which kind a chat is, and the history before one joined is read on demand

**Id:** 46abbbf3-40b9-4802-a22f-1a85293a9b8f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the group-chat contract (docs/api.md §9.2, §9.3, §8.5; PR #153) and the coordinator's card for the dashboard's part (tsk-b2dv60tsexjf), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub sends live events to an owner who reads along, a chat gets more than twelve people, or the list needs filters by kind
**See:** views.md#the-chats-history-days-apart-a-senders-run-grouped-and-the-line-before-what-was-unread-when-it-opened — abe93ad2-1a75-4abc-a5d0-70e074d17335 — as of 2026-10-22

Group chats are in the same list as the direct chats, newest first, and
open in the same right-hand pane. A new one is made in that pane
(`#/p/<slug>/chat/new`), so Back and the URL work as for any chat. The
kind of a chat comes from the hub's list, never from the shape of its
id. The open chat names its people and everyone who reads along. It
shows the window since one joined; what came before is a button away,
read on demand. Choosing one's own agent alone for a new chat points
to the direct chat before anything is sent. Renaming, adding and
removing people sit behind a disclosure, for the creator and admins
only. Removing a message asks for a reason in the browser's own prompt,
as the page already asks with the browser's confirm before anything
destructive; the hub requires the reason, so an empty one is asked for
again. A removed message is recognised by its `null` body. Changes to
the chat, someone else's included, are drawn in place, and a removal
reaches the open chat through `event_redacted`. No message wakes an
owner who reads along, so the view re-reads every 30 seconds.

**Reason:** one list is one place to look for "where was that said",
and the chat view's sizing, drafts, quoting and Markdown work for both
kinds unchanged. The hub decides what a chat is, so a change of id
scheme cannot break the page. Starting at the window is the contract's
"fresh by default": a latecomer is not buried under talk from before
they came, and the button says the earlier part is there.

**Rejected alternative:** a separate tab for group chats: two lists to
search, and a mention could sit in either. A dialog for the new chat:
the page has no dialogs, and a pane route keeps the browser's
navigation. Loading the whole history on opening: it would bring back
the backlog the window keeps out.

## Reading along from outside a project is its own route on the chat view, found through one's agents; the blind removal sits in Project settings

**Id:** fe785529-88da-47be-927b-4b13924f2b46
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §9.2 (an owner outside the project) and §8.5 (blind removal); the coordinator's card for group chats part 2 (tsk-vz8e024wehde), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub offers such an owner a list of its readable projects, sends it events, or the accounts design gives humans a place for projects they are not in
**See:** views.md#group-chats-live-in-the-chat-views-own-two-panes-the-hub-says-which-kind-a-chat-is-and-the-history-before-one-joined-is-read-on-demand — 46abbbf3-40b9-4802-a22f-1a85293a9b8f — as of 2026-10-23

An owner whose agent is in a project the owner is not in reads that
agent's group chats at `#/observe/<slug>`. The page is the chat view
itself, run in a context without a project: no header, no member list,
no events. The projects come from the agents' memberships
(`GET /agents`), and everything waiting (`#/all`) names them. Names in
those chats are the hub's handles, except for one's own agents.

An owner or admin removes a reported message of a closed group chat by
its number in Project settings, without reading it. The form always
sends `expect: "closed_chat_message"`, so a mistyped number removes no
other event. The human party of a direct chat removes a message there
as in a group chat, when they hold `events:admin` (owner or admin).

**Reason:** §9.2 lets such an owner read those chats and nothing else.
Every other read of the project is `not_found`, so a project view with
its header would only fail; a context that asks for nothing else keeps
the page inside what the hub answers. The memberships are the only
place the human learns of such a project. The blind removal has no chat
to start from, because nobody who can open the chat is left, so it
belongs with the project's other admin tools.

**Rejected alternative:** these projects in the project switcher, like
one's own. They would promise inbox, board and members, none of which
the hub answers. A removal form inside the closed chat: the admin cannot
open that chat.

## The project's messages are read from the project's events until the hub has the message listing

**Id:** 8e483bb1-53be-4ce2-a139-561989db21af
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §8.3 (events), §8.4 (message types), §8.5, §8.7 and §8.8 (the listing, in the contract since #215, not in the hub yet); the coordinator's card for the project messages view (tsk-3s4an5p22v4j), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub implements `GET /projects/{slug}/messages` (§8.8), or projects outgrow a window of 5000 events
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-10-23

The Messages tab reads the project's latest 5000 events
(`wait=0`, 200 per page, from the head that `after=latest` names) and
keeps every message that is not a chat and not removed. When the log is
longer, the view says that older messages are not read. A cursor that
does not move stops the read with an error. The view shows the messages
newest first and filters them by type in the page. New messages, removals
and deleted files arrive through the project's feed and change the list
in place. A removed message leaves the list and is never shown as a
tombstone. Tombstones come with §8.8 once the hub serves it.

**Reason:** §8.3 is the only read the hub answers that returns project
messages, and its audience filter already decides what this reader may
see. It is not §8.8's set, though: §8.5 replaces a removed message's
whole payload, so a removed chat message looks like a removed project
message there, and §8.8 never lists the former. Showing no tombstone is
the one way the scan never lists a chat's. A stated window bounds the
requests per opening without hiding that something is missing.

**Rejected alternative:** waiting for the hub's message listing before
building the view: it would leave project messages unreadable in the
dashboard, the gap noted on the attachments change. Reading the whole log
from the start: one request per 200 events on every opening, with no
bound. Keeping tombstones whose audience is `all` or a role: it still
hides the removal of a message sent to one member, and guesses at what
the hub knows. Having the hub mark a conversation's message after
redaction: a contract change that §8.8 already makes unnecessary.
