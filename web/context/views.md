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
project state (plan, build, review, launch, archived) sits in the
header of every screen.

**Reason:** the root decision makes the inbox the human's primary
surface; the dashboard's order follows from it, and an entry has to carry
its context because the point is that answering does not require a chat.
The project state belongs on every screen because a review changes what
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
fetched or kept. Each agent's node lists its live instances as links to
their Sessions on the member's page, the target an instance has everywhere
else; a dormant one says so beside its link.

The Agents page's Organisation tab (`agents/organisation`, the maintainer,
2026-11-02, tsk-q989pagmk2x9) is the same tree built from one's own agents
in the project alone, under oneself: a boss or an area owner of someone
else's places none of them, and an own agent that reports to someone
else's shows that as a stub with the boss's handle, as text (the
qualified `owner/handle` where another member shares the short one,
`M.dom.handleOf`, docs/api.md §6.3), and nothing more of the other side:
no name, no link to its page, no tooltip. Where the member list gives no
handle, the stub is the neutral sentence "reports to someone who is not
yours", never an id or a name. Its instances are dots in their presence's
colour, the lead ringed. Each state also has a shape of its own, so that colour is never the only
cue (WCAG 1.4.1; a review of #1485, nte-s2dqhn1n4bez; the coordinator chose these shapes, batch 3c of
tsk-tsb8528rank1, 2026-11-10): online a filled disc, away a ring half filled, offline a smaller
disc, dormant a hollow ring. In forced colours, where the browser drops gradients, background
colours and shadows, the same four shapes and the lead ring are drawn with borders, size and an
outline alone, in the user's system colours (#1598 review). The state stays in each dot's name and
tooltip as well.
Built from the same member list, so no second tree and no hub field.

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
**Source:** the maintainer's multi-project requirement, relayed by the coordinator, 2026-10-21; the dashboard's implementation, 2026-10-21; re-checked when the tabs became the browser's own (card tsk-p6aye59z0k7g), 2026-11-06
**Revisit when:** a human asks to land on one project
**See:** views.md#the-inbox-is-the-first-screen-board-agents-organisation-and-chat-follow-in-that-order — a8f4ac34-b7be-47f0-aaec-dc494e6c2080 — as of 2026-10-21
**See:** views.md#the-project-tabs-are-the-browsers-own-moved-by-dragging-by-altshiftarrow-or-from-the-tabs-menu — cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6 — as of 2026-11-06

One account holds many projects. The header of every screen carries a
project switcher: each project this browser has open as a tab, with its
state and the number of open requests waiting for this human, plus "All
projects" with the total. A switcher row too long is answered by closing
tabs (cd4fe2ba). The
cross-project view (`/all`) is the inbox across every project, each
entry labelled with its project and that project's state, answered in
place. Opening the dashboard without a route lands there when the human
belongs to more than one project, and on that project's inbox when there
is only one. Everything else lives under `/<owner>/<slug>/...`.

**Reason:** the requirement is that the human sees from anywhere that a
project needs them; a count beside every project name does that on every
screen, and a landing page across all projects keeps "the inbox is the
first screen" true when there is more than one inbox.

**Rejected alternative:** landing on the last project used — it needs
remembered state, and it hides what waits elsewhere behind the switcher
on exactly the screen opened first. A project chooser as the landing
page — one click more before the first answer, and it shows counts but
not the requests themselves.

## The project tabs are the browser's own, moved by dragging, by Alt+Shift+Arrow or from the tabs menu

**Id:** cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision of 2026-11-06 on request req-6zp8zjwabmds, relayed on card tsk-p6aye59z0k7g; the dashboard's implementation, 2026-11-06
**Revisit when:** the account keeps the open tabs too, or the tab row gets groups or pinned tabs
**See:** https://github.com/oliver-zehentleitner/maity — 6e21a45a-26a7-46a0-b7c4-f7213718225b — as of 2026-11-06

Which projects the header shows as tabs, and in which order, is kept in
this browser per viewer (`js/tabs.js`); without storage it holds for the
visit. A browser with nothing kept starts from the account's
`start_tabs`, or with every project when that is `null`. A project the
browser has not seen yet opens as the last tab; one opened by its
address gets its tab back. A tab moves by dragging, by Alt+Shift+Arrow
on the focused tab, or by Move this tab left/right in the tabs menu
beside the row, which also opens and closes each project (switches that
keep the menu open) and keeps the current row as the start set. Each
move is announced with the new place. A project's start-set switch also
sits in its own settings (Mine). The cross-project inbox can be filtered
to projects with an open tab; personal requests always stay.

**Reason:** the split between browser and account is the maintainer's
(the contract entry above). The rest is inferred from the dashboard's
existing rules: nothing is drag-only (the board's Move and Place menus),
so a single pointer or a keyboard reaches every move a drag makes; and
a filter that hides personal requests would hide requests with no tab
to open them from.

**Rejected alternatives:** unknown beyond the contract entry's.

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
second Save files no second request. The line names who is asked and, where
part of the change took effect at once, which part (the entry on consent
lines below). A drafted boss who has left the
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
**Revisit when:** a runner's owner who is no admin asks to detach from the dashboard, or the hub sends events for runners' presence or placements

The tab is offered to owner and admin only (`members:admin`), although
the hub also lets a runner's owner detach it. A runner's owner who is no
admin of the project is left out of this tab. Allowing is the hub's grant; the
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

Every entry of `/all` has its project's badge (logo or monogram, name,
state) before it, as a link to the project's inbox; the entry's head
button starts with the project's name, visually hidden, so that the
button's own name says which project it is. A project filter and an
optional grouping by project (sections in the switcher's order, each a
heading with its own list) sit in the toolbar; both are kept only for
this tab's session and apply to `/all` only, never to a project's own
inbox. The entry opened first and the one opened after an answer follow
the order on screen, filter and grouping included. The filter stays over
a reload of the list and says what it hides, with one click to lift it;
resetting it at each reload was rejected, as it would undo a choice the
person just made.

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

`/<owner>/<slug>/overview` gets the tab right after **Inbox**, while the inbox
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
(`/<owner>/<slug>/chat/new`), so Back and the URL work as for any chat. The
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
agent's group chats at `/observe/<slug>`. The page is the chat view
itself, run in a context without a project: no header, no member list,
no events. The projects come from the agents' memberships
(`GET /agents`), and everything waiting (`/all`) names them. Names in
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

## Sessions say what this session may not do before it is tried, and This was me is the only way a sign-in is confirmed

**Id:** 561b77f6-2a12-4352-aa50-36a8aa773fbe
**Type:** decision
**Status:** superseded
**Superseded by:** 0d50b2d4-2841-4510-a204-90d3aa574927
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 (good standing, who may end which, the banner), §2.6.3 (a held address change), §2.6.7 (the dashboard's part) and §18.3; the coordinator's card for the sessions view (tsk-s5yq94v758g4), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub serves the session list (the view is built against the mock), or the session view gains a field that says what a session may do
**See:** refresh.md#a-sign-in-or-address-alert-is-never-marked-read-by-opening-it-or-by-mark-all-read — 4c95abfb-95af-4c4d-85e0-6fb1cddfd79f — as of 2026-10-23

The account's Sessions section works out from the list itself what this
session may do: whether it is confirmed (`good_standing`), how old it is,
and how old the other session is. From that it disables **End**, **End
all other sessions**, **Approve** and **Reject** with the reason next to
them, and offers **This was me** only from a confirmed session older than
the sign-in it confirms. The hub's refusals are still said in words when
they come. **This was me** marks the alert read by its id, the one way
§18.3 confirms a sign-in. The held address change sits in the same
section, and the mail sign-in banner is shown at the top of every page of
every other session. The banner stays while the reported session or one
it approved is active, applies the list's rules to its End, and is built
again on every round of the `/me` read while a sign-in alert is unread.
"Confirmed" is said only when the alert is no longer unread afterwards,
because the hub answers 200 for an id it skipped; when the list cannot
be read again the result is said to be unknown. A check each minute
redraws the section when this session crosses an hour or a day of age.

**Reason:** the rules are the hub's, but a button that can only fail
teaches the human nothing about why, and §2.6.7 asks for the disabled
buttons and their words. The list carries everything the rules need. A
sign-in is confirmed by an explicit act or not at all, so the alert's id
is sent only from that button. The address change and the sign-ins are
decided by the same standing and the same age, so they are read in one
place.

**Rejected alternative:** offering every button and showing the hub's
refusal afterwards: it works, but it makes the human try in order to
learn the rule. Confirming a sign-in by opening its alert: rejected in
the entry linked above. Putting the held address change under the
notification settings, where the address lives: those settings carry
the mail, and the decision needs the standing that the sessions section
shows.

## Sessions say what this session may not do, and a sign-in is confirmed by its own call

**Id:** 0d50b2d4-2841-4510-a204-90d3aa574927
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 (`POST /auth/sessions/{id}/confirm`, `confirmed_at`, the banner), §18.2 and §18.3, contract PR #1230; the bell card tsk-0kz8v1ff5sgf, 2026-11-03
**Revisit when:** the session view gains a field that says what a session may do
**See:** views.md#sessions-say-what-this-session-may-not-do-before-it-is-tried-and-this-was-me-is-the-only-way-a-sign-in-is-confirmed — 561b77f6-2a12-4352-aa50-36a8aa773fbe — as of 2026-11-03
**See:** refresh.md#the-bell-pins-the-unread-security-alerts-and-mark-all-read-takes-them-only-after-asking — 643600cd-dd61-4291-85d7-025e322f4c81 — as of 2026-11-03
**See:** refresh.md#the-bell-pins-security-alerts-but-no-sign-in-the-notifications-page-lists-the-current-sessions-read-again-when-sessions_rev-moves — 09f74f56-7c6c-4d94-a499-ef804b022f3a — as of 2026-11-04

What the earlier entry says about disabled buttons and their reasons stands. What
changed: **This was me** posts the session's confirm and is offered on an active
session that is not in good standing, where this session may confirm it; an ended
session has none. The unread alerts come from the hub's `pinned` block; one that
reports no session in the list gets **Mark read**, and an id the hub skips is said
with its reason, never called read. The mail sign-in banner follows the sessions:
it stays while the reported session, or one it approved, is live and not in good
standing, whatever the alert's read flag, and is checked again on each counts round
while it is shown.

**Reason:** reading an alert no longer confirms anything (§2.6.5), so the session's own
`good_standing` is what the buttons and the banner must follow. The confirm answers with
the session, so its result is known without reading the list again.

**Rejected alternatives:** marking the alert read as the confirmation, as before: the
contract made reading and confirming two acts. Keeping the banner tied to the unread
alert: marking it read in the bell would take the banner down while the sign-in is still
unconfirmed. Offering This was me on an ended session: there is nothing left to confirm.

**Since 2026-11-04** (09f74f56-7c6c-4d94-a499-ef804b022f3a): `pinned` holds no sign-in, so the
unread alerts listed in this section are only the other security kinds, each with **Mark
read**; no row says its sign-in alert is unread, and the ended sessions stay folded. **This
was me** on an active unconfirmed session is unchanged.

## The Ticker view reads the listing, not the events, and says each reason in the dashboard's own words

**Id:** 6c688878-105b-4162-b0ad-5e1302df921c
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** docs/api.md §17.5 (shaped per reader), §17.6 (manual post), §17.8 (subscriptions) and §17.9 (listing and the dashboard's part); the coordinator's card for the Ticker view (tsk-sbx670wtr5qb), 2026-10-23; the dashboard's implementation against the mock, 2026-10-23
**Revisit when:** the hub serves `/ticker`, or the listing gains a field the view now derives
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-10-23

The Ticker tab reads `GET …/ticker` (`for=me` by default, `type`, `area`,
the hub's cursor) and shows the listing's compact items as they come,
shaped for this reader by the hub. A ticker event in the project's feed
is only the signal: the view reads its own listing after the newest item
it shows (`after=`, oldest first, page by page), with the same filters,
and puts what it has not shown on top. Every read belongs to one filter
set, and an answer that arrives after the filters changed is dropped. A
404 is an error (until 2026-10-30 it meant "no ticker" when the hub's
`openapi.json` lacked the path, e1699490). Reasons are shown as
words ("you own hub/", "you implement §13"), not as the API's tokens. A
manual post to everyone asks first, since it wakes every member who has
not muted it.

**Reason:** the listing is the one form the hub shapes per reader and
per filter (`for_me`, `why`, `muted`, a decision withheld from a
non-reader); building items from the raw events would mean redoing that
shaping in the page, and getting a decision's visibility wrong would
show a reader something the hub hides. §17.9 leaves the words to the
dashboard. A post to everyone is the one action here that wakes the
whole team.

**Rejected alternative:** reading the newest page again on each event:
when more than a page of items arrives at once (a reconnect, a burst of
deploys), the ones in between are never shown until a reload. Building
items from the raw events: the per-reader shaping would have to be
redone in the page. Taking any 404 on the listing as "no ticker": §17.6
notes that a mistyped project answers the same. Showing the reason
tokens as they are: they are the CLI's text form, not words for a
person.


## The chat list is a list, not a row of header links; a name wraps whole and a line says who it is

**Id:** 37084cf9-9062-456e-bc7e-f4265fc9ccff
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's screenshot of the deployed chat view, relayed by the coordinator (tsk-2my9kqmjp6nk), 2026-10-23: every entry read "Oliver Zehentleit…", the time sat on the name, the list was a narrow column beside the heading; the dashboard's implementation, 2026-10-23
**Revisit when:** the header gets a nav that is not a row of links, or the chat list leaves its `<nav>`

The header's link rules (a scrolling flex row, links on one line) apply
to `nav.switcher` and `nav.views` only, not to every `<nav>`. The chat
list, a `<nav>` itself, is a block again: heading and **New group chat**
above the list, a name that wraps instead of running under the time. The
list is wider (16 to 24 rem). A direct chat's second line says who it is
(`agent · @handle · harness`), a group's `group · ` and its people;
presence is the avatar's dot and words for a screen reader. Unread chats
come first, then the newest.

**Reason:** the generic `nav` rules were meant for the header's rows,
and the chat list inherited them: a flex row made the heading a column
of its own, and `white-space: nowrap` cut every name to its owner's
shared prefix and drew it under the time. The handle is unique where
the display names are not, and the harness tells agents of different
kinds apart.

**Rejected alternative:** overriding the header rules for the chat list
only: the next `<nav>` would inherit them again. Cutting the shared
prefix off the names: the card asked for the name to stay readable as
it is, and a prefix shared by today's agents need not be shared
tomorrow. Presence as a line of its own: the dot already says it.

## The dashboard asks the hub no capability question; a route it calls that is missing is an error

**Id:** e1699490-402f-45ac-9461-d85189411559
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's alpha rule (no compatibility layers before launch, 2026-10-29); the coordinator's rulings on tsk-wgg2t8ngx9xg (the notifications fallback and the "not on this hub" mechanism removed, `hubHas` and `hubBody` with them, and the field-presence checks in the same PR), 2026-10-30; hub/src/maity_hub/app.py (every router mounted unconditionally); hub/src/maity_hub/views.py and policy.py (the fields every project and member view carries)
**Revisit when:** Maity leaves alpha and a dashboard must run against an older hub (§1.6), or the hub mounts a route only under a setting

The page no longer reads `GET /openapi.json`: there is no `M.api.hubHas`,
`M.api.hubBody`, `M.api.missingRoute`, `M.api.absent` or
`M.dom.notOnHub`. Every control is offered by the page's own rules
(role, trust, project state), and every route it calls is called; a
404 or 405 from one is an error and is said as one. Nor does the page
test whether the hub sends a field it always sends (`"signing" in
policy`, `"logo" in project`, a card's `parent`): only fields the hub
sends to some readers or under a condition are tested, such as a
member's `owner_preferences` or `keep_the_why_unconfirmed`.
The notifications' counts are read like any other call: until they are read the switcher
counts the open requests from `/me`, and a failed read is said.
Settings a hub really may have off stay explicit in its answers, such as
`409 attachments_not_configured` or a sign-in method's `method_disabled`.

**Reason:** the dashboard and the hub ship together from one
repository, and the hub mounts every router without a condition, so a
route "not on this hub" only happens with an older hub, which nobody
runs in the alpha. The machinery cost a request per page, a muted text
per feature and a branch per view, and it hid a broken deploy behind a
quiet line.

**Rejected alternative:** keeping the machine-form checks for the
controls only: the same dead branches in each view, for the same hub
that does not exist. Keeping the quiet line for a 404: a missing route
now means something is broken, and that should read as broken.

## A control for a route a hub may lack is offered only when the hub's machine form lists it; an unreadable one keeps the control

**Id:** 51dab38e-abd9-4848-91ed-a066eea39e9f
**Type:** decision
**Status:** superseded
**Superseded by:** e1699490-402f-45ac-9461-d85189411559
**Evidence:** confirmed
**Source:** the coordinator's web-vs-live audit and its card (tsk-x995qwddkrk2), 2026-10-23: on maity.team "New group chat" and "Attach files" were offered while the hub served neither; the dashboard's implementation, 2026-10-23
**Revisit when:** every hub the dashboard serves has group chats and attachments, or the hub answers a capability list of its own

`M.api.hubHas(method, path)` reads `GET /openapi.json` once per page and
says whether the hub serves a route, the `/api/v1` prefix and the
parameters' names not compared. New group chat, the form at
`/<owner>/<slug>/chat/new`, the blind removal in Project settings and reading
along from outside a project need `POST /projects/{slug}/conversations`;
without it the chat list says "This hub has no group chats yet." instead
of looking empty. Attach files needs `POST /projects/{slug}/attachments`
and is hidden, too, once the hub answered 404 to the pending list. The
Ticker asks the same way. A machine form that cannot be read counts as
"served": the controls stay, and a failure says itself where it happens.

**Reason:** the hub has no capability list, and its machine form is the
one place that says which routes it serves; the routes in question could
not be probed without side effects (a POST would create) or tell apart
(`GET …/conversations` exists on hubs without group chats, and a 404
may be a mistyped project). Offering a control whose every use fails
tells the human nothing until they have typed a message or picked a
file.

**Rejected alternative:** hiding the controls when the machine form
cannot be read: a passing network failure would silently take working
features off the page for the rest of its life. Each view reading
`openapi.json` on its own, as the Ticker did: the same read and the same
two key forms in several places.

## The inbox is the requests alone; activity is on the bell, the Chat button and /notifications

**Id:** 2ff6afe9-ed47-4ffd-b12d-947cfb7774ca
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report and decision on tsk-430dnt8s25a8 (the Request updates section slow and noisy, the tab's count against an empty list), relayed by the coordinator, 2026-10-29; docs/api.md §7, §18.2, §18.3
**Revisit when:** the hub gives the inbox a kind of activity that asks for an answer, or the bell no longer lists everything unread

The inbox, in a project and across them, lists the requests and nothing
else: the block of unread activity under them (Request updates,
Conversations, Mentions, Account) is gone. Its history is the Show filter
(answered, closed). Unread notifications are on the bell, conversations
on the Chat button, and every notification on `/notifications`, where an
unread one is in bold with a dot as on the bell and **Mark all read**
marks up to the head of the first page (§18.3).

**Reason:** the block mostly repeated the hub's notices about agents not
listening, held the page while it read up to four pages of 50, and made
read and unread look alike; the inbox is for what asks for an answer.

**Rejected alternative:** keeping the block with read and unread told
apart: the activity would still sit under the requests and be read on
every visit, while the bell already shows it.

Since 2026-10-30 (the maintainer's wish, the card tsk-bt2p3rem8tbj)
`/notifications` also has **Mark read** beside each unread item, sent
with its id, without opening it, the row marked read in place (its
button gone, the focus on its link, the pages read so far kept), and
**Mark all read** stays in place,
off while nothing it marks is unread. It leaves every security alert
unread, whatever the session, with the line "Mark all read leaves
security alerts unread: mark each one read on its own."
(`waiting.mark_all.hint`). **Mark read** is not offered on one of the
open matters of §18.3 — `registration_pending`, `mail_disabled`,
`agents_not_listening`, told by their targets
(`registration`, `settings`, `agents`, `M.notify.keepsUnread`)
— which read as read once the matter is closed, nor on a security
alert this session may not mark (`M.sessions.mayMark`, as the bell
does): an address change only from a confirmed session older than it,
every other security alert from any session (§18.3). A sign-in is no
item; the box above the list shows the sessions (§2.6.5). An id the hub
leaves unread anyway is answered as `skipped` (§18.3), which the page
says, its row staying unread. The sessions are read for that only when
the page shows an unread security item. Until 2026-11-04 a fourth
matter, `report_open` (target `report`), stood among them; a new report
is now the instance admin's personal request instead (entry
f50ed8ee-5948-43c8-817a-d1b008bf1f5a).

Since 2026-10-31 (the maintainer's wish, `context/chat.md` entry
6e357e0c "An inbox answer carries a note with any button", §7) each open
request has one free-text field **above** its buttons, always writable:
every reply button sends `{reply_id, text}` when the field has text, and
**Talk** sends `{talk: true, text}`, **Send** the text alone. "Talk" is
one word in every language (a language file leaves `inbox.talk` out
rather than translating it). Talk works only where the asker is an agent
the reader owns (§7: accepted only from the human who owns the asking
agent): inside a project from the member list (`owner_id`), across
projects and for a personal request from the reader's own profiles
(`GET /agents`, read once per view; their ids are the agents' member
ids). For a human asker, a request the hub filed itself (no asking agent
reads the answer) and when the profiles cannot be read it is disabled
with its reason; where Send and Talk stand and when they are disabled is
the next entry's. `canTalk()` in `js/inbox.js` is the one place to
change when the hub computes a field for it.

## Send and Talk stand on every request one can answer; where the hub would refuse them they stay, disabled, and say why

**Id:** 3cfa5e18-b709-4d76-a560-ce24ef5eecfc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-nx6hm8qjzm3z (Send and Talk on every inbox item) and the lead's decisions on its plan, 2026-11-04; docs/api.md §7 "The inbox", §15.6 (a consent's text alone read as No); hub/src/maity_hub/takeovers.py (`reply_required` on a takeover's request); web/js/inbox.js; the e2e step `send_talk_step`
**Revisit when:** the request view says which consent carries a proposal or a placement, or the hub computes per request whether the text alone or `talk` is accepted

Every request with a field has **Send** after its replies, on a request
with options too: it sends the text alone (`{text}`), Ctrl+Enter the
same, and is disabled while the field is empty. It stays disabled, with
its reason below the buttons (`.reply-hint`, its `aria-describedby`),
on every `consent`, every request with `action` or `placement`, and a
takeover's (`takeover_id`), and there Ctrl+Enter is not offered: a
shortcut that never sends is not announced. **Talk** stands on every request one can
answer, disabled with its reason where `talk` is not accepted: for
another owner's agent, a human asker and a request the hub filed itself
(above), and on a takeover's: like the words alone, it is refused there,
since one of its replies is required. No reason is said for a Send that
is not there.
Neither stands where no answer is possible at all: a call that only the
project's owner answers, seen by another member, and a personal request
not read in full. A refused answer gives the controls back, and what was
disabled stays disabled.

**Reason:** the hub takes the text alone as an answer to any request
(§7), so a request with options had no way to answer in one's own words
although the hub would take it. Where the hub refuses the text alone (a
takeover's reply is required) or reads it as No (a consent's proposal or
placement, §15.6), a button that sends it would answer something the
reader did not mean; one that is missing does not say why. Every
consent is treated alike, a plain one too: the request as the inbox
reads it does not say which consent carries a proposal or a placement,
and a Send that works on one consent and not on another, for a reason
the reader cannot see, would be the same surprise.

**Rejected alternative:** hiding Send and Talk where they do not apply,
as before: the reader cannot tell a button that is missing here from one
that does not exist. Talk for another owner's agent: the hub refuses it
(`only_the_owner_of_the_agent`), so the button would surely end in
`invalid`. A field from the hub saying per request whether the text
alone and `talk` are accepted: a hub change for what the dashboard can
tell from the request today; the Revisit when names it.

## A project's unread mentions are a link beside its tabs, to /notifications filtered to the project

**Id:** 0906c3fe-ffe3-4baf-94c1-c093de6fee54
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-xb7bf1x0h3cy (the owner's report: the Maity pill showed 2, the Inbox and Chat tabs nothing), the plan agreed with the lead on the card, 2026-11-03; docs/api.md §18.2 (`kind`, `project`), §18.3 (`up_to` with `kind` and `project`), §18.8 "Per-project badges"; the maintainer's decision to drop the line on the Chat tab, card tsk-sesdq48m9ewk, 2026-11-10 (chats 102080 and 103539)
**See:** views.md#the-inbox-is-the-requests-alone-activity-is-on-the-bell-the-chat-button-and-notifications — 2ff6afe9-ed47-4ffd-b12d-947cfb7774ca — as of 2026-11-03

A project's pill counts its open requests, unread chats and unread mentions (§18.2 `by_project`),
but only Inbox and Chat have a tab count. While the project has unread mentions, a line beside its
tabs ("1 unread mention") links to `/notifications?kind=mention&project=<owner>/<slug>`. That page
reads both filters from its address and asks the hub with them (§18.2). Its heading names them
("Mentions in Maity"), a link leads back to all notifications, and Mark all read sends the same
`kind` and `project` with `up_to` (§18.3), so it marks nothing outside the filter. The line is
filled again with every count read, so it follows the pill.

The line is left out on the Chat tab, on its list and in an open chat: the maintainer asked for it
gone there, since the chat list shows a chat with an unread mention as an @, visible at once
(tsk-sesdq48m9ewk, 2026-11-10, chat 102080). The @ covers chat mentions only: the line also counts
mentions in project messages and on cards (§18.1), which the Chat tab does not show. Asked about
those, the maintainer kept the removal because they stay in the bell and on the line of every other
tab, as on the pill and /notifications (chat 103539).

**Reason:** a count on a project should lead to what it counts in one step, and mentions have no
place in the project: the inbox is the requests alone (see 2ff6afe9). The hub already filters
by kind and project for reading and for marking, so the dashboard needs no new call.

**Rejected alternatives:**
- Leaving mentions out of the pill: §18.8 builds the per-project badge from `by_project`, whose
  total counts them, and the all-projects pill would no longer add up.
- A Mentions tab: the tabs are the project's own views; this one would only lead out to
  `/notifications`.
- The pill leading to the mentions when they are all it counts: the pill always opens the
  project, and a target that changes with the count is surprising.
- The line in the inbox only: it would show on one tab, and the inbox does not redraw when only
  the counts change.

## A personal request in the cross-project inbox is labelled Personal; its project, card and mentions are no links

**Id:** 2fd5910d-3233-4aca-a16e-8c1cc73d071a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §7 (personal requests, PR #232); the coordinator's card tsk-x995qwddkrk2, 2026-10-23; the dashboard's implementation, 2026-10-23; the coordinator's choice of the count fix on tsk-430dnt8s25a8 (option a), 2026-10-29; the review of PR #1356 that found the people of a personal request linked by the member list since, 2026-11-04
**Revisit when:** the dashboard gets a personal inbox of its own, apart from `/all`

A personal request (`personal: true`, listed only by `GET /requests`) is
answered and withdrawn on `/requests/{id}/answer` and `…/withdraw`. Its
badge says "Personal" and its project's name without a link, its card and
its mentions are text, its free text has no @ picker, and it offers
Withdraw, which only its human may do. Grouped by project, the personal
ones come first under "Personal". Since 2026-10-29 a project's own inbox
lists the open personal requests about that project too, read from
`GET /requests`: its tab counts them (§18.2), so the list shows what the
tab says; they keep the label, and their badge, card and mentions lead
into nothing. Who asked, on whose behalf and to whom are named as
everywhere: a link only for a member the request's project lists
(801bc195). The hub has no
project filter on `GET /requests` (§7), so the project's inbox filters
what it reads; a failed read is said in the list's status line, never
shown as an empty list, since a list short of its tab is the bug this
fixed. The list's own reload follows the inbox count of §18.2
(`by_project`, `counts.inbox`), which counts those personal requests,
not `/me`'s `open_requests`, which does not.

**Reason:** the project's routes answer `not_found` for a personal
request, the project's own listing never holds one (§7), and its human
need not be a member of that project: a link to the project's inbox or
card would lead nowhere. A member the project lists has a page there,
and one it does not list stays text (801bc195). A tab that counts what its list leaves out
reads as a bug (the maintainer's report).

**Rejected alternative:** the project's badge and links as for every
other entry: they lead to an inbox without the request, or to a project
the human cannot open.

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

## A member is named through one helper, as a link to their row in Members

**Id:** 801bc195-cbbf-497a-82d0-7c40bc7567b1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's rule that agents and humans are always clickable, relayed by the coordinator (tsk-f7w3w35bq0r3), 2026-10-23; the dashboard's implementation, 2026-10-23; the maintainer's report that "Asked by" in the inbox was plain text, relayed by the lead on tsk-3re8qp89hc18, 2026-11-04 (web/js/inbox.js `ref` and `membersOf`, the e2e step `asker_links_step`); the review of PR #1356 that found links to members the project no longer lists, 2026-11-04
**Revisit when:** a member gets a view of their own apart from the Members row, or names appear inside a control that cannot hold a link

`M.dom.memberRef(ctx, who, opts)` is the one way a view names a member:
a link to `/<owner>/<slug>/team/<id>` (Members marks that row and focuses
it), the full name as tooltip, `data-member` for tests. A member the
project does not list (removed, outside) and every member in a view read
from outside the project are plain text. The inbox of all projects
reads the member list of each request's project among the reader's, once
per view, and names who asked, on whose behalf and to whom by it: a link
into the request's project for one that list names, text for one it does
not (a member removed since, a human who asks without a membership, a
project the reader is not in, a list that could not be read), as inside
a project. A name inside a button (an inbox entry's head) stays text,
since a link cannot sit in a button.

**Reason:** the maintainer wants to reach any member's actions from
wherever they appear, and one helper keeps the link, the tooltip and the
plain-text rule the same on every page.

**Rejected alternative:** a link built in each view: the rules for who
is linkable (listed, inside the project) would drift between pages.
Keeping the inbox of all projects plain text, as it was until
2026-11-04, since it read no member list there: the maintainer found the
plain name a dead end. A link built from the request alone, for anyone
it names in one of the reader's projects: the hub keeps an open request
of a member removed since, and names a human who asks without a
membership the same way, and both links opened only "No member with the
id … in this project" (the review of PR #1356, 2026-11-04).

## A route the hub does not serve is said quietly, and the page does not ask it again

**Id:** aa3669b7-71e6-4e87-9376-5759824653d3
**Type:** decision
**Status:** superseded
**Superseded by:** e1699490-402f-45ac-9461-d85189411559
**Evidence:** confirmed
**Source:** the coordinator's card from H's audit of every route the web calls against the hub on main (tsk-yht5tzadgv83, tsk-056gjh5jpfq7), 2026-10-23: 19 of 83 not served, some red, the notifications read every 15 s regardless; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub answers a capability list, or every route the web calls is served on every supported hub

A 404 or 405 means "not on this hub" only when the hub's machine form
does not list that method for that path (`M.api.missingRoute`); a 404 on
a listed route is the resource's (a project left, a card gone) and stays
an error, as does one while the machine form cannot be read. A view that
needs a missing route shows a muted line in its place (`M.dom.notOnHub`)
and notes the route (`M.api.absent`, method and path without the query,
until the next navigation, so a deploy meanwhile is found): the notifications' count read on the `/me` round, the browser
notifications' long-poll, the overview's re-reads and the sessions list
ask no more. A 5xx, a network failure, 401 or 403 is still shown as an
error.

**Reason:** an older hub without a feature is the normal case while the
hub grows, not a failure of the reader's; a red line for it reads as
something broken, and a timer that keeps asking costs a request every
15 seconds for nothing.

**Rejected alternative:** a check of the machine form before every call,
as for the controls (views.md: controls only for routes the hub lists):
the answer of the call itself already says it, and these reads happen
whether or not a control is drawn. Caching every 404 by its full path: a
card or a request that is gone answers 404 too, and must not be taken for
a missing feature.

## Joining an agent happens in Agents: a panel under the title, open joins as seats in the grid

**Id:** d80f865d-5b59-4ad1-8cc2-c1079d13869c
**Type:** decision
**Status:** superseded
**Superseded by:** 621d28a8-36f5-4ebd-a90a-f7d729d7af34
**Evidence:** confirmed
**Source:** the maintainer's wish that Join an agent be part of Agents, not a page of its own (tsk-rf6qynscm6px), 2026-10-23; the designer's layout for it, 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** joins get a lifecycle of their own beyond open, used, expired, burned and revoked, or the Agents view is split

Join an agent is no longer a tab. Agents' title row has **+ Join an agent**
(owner and admin), which opens an inline panel under it, closed by
default and open at once in a project without agents or at
`#/p/<slug>/agents/join`; the old `#/p/<slug>/join` opens the same. The
form keeps its logic (js/join.js) in two columns; a made join's line
takes the form's place, with Join another and Done. An open join is a
dashed **open seat** at the front of the agents' grid; the rest of the
joins are folded at the view's end as Earlier joins.

**Reason:** joining is how an agent gets into that view, so the action
sits where its result appears; an open join is a member that has not
arrived yet, so it stands among the members, not in a list of its own.
The record of old joins is rarely needed.

**Rejected alternative:** a modal dialog for the form: it hides the grid
the seat appears in, and the panel works the same at 390 px. Open joins in
a section of their own below the cards, the first idea: it kept them
apart from the team they join.

## A preference proposal is reviewed as an inline line diff; one on an older version is merged by hand, never accepted as is

**Id:** 8546c70b-d006-4913-9ae3-6aeac5a250d3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's wish for a review with current text, proposed text, diff, edit before accepting, accept or reject (tsk-qwamrxnd8vc3); docs/api.md §19.4 (no silent overwrite, the hub does not rebase); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the designer answers on the review layout, or the hub lists proposals with their texts

The review in the personal inbox shows the reason, then a line diff from
the human's current text to the proposed one, one line per row with − and
+ (said in words for screen readers), and both texts in full folded below.
Its own answers replace the plain Go and No: **Accept**, **Edit, then
accept** (the edit goes with the current version) and **Decline** with an
optional reason. A proposal written against an older version offers no
plain Accept, only **Merge by hand** or Decline. Because a list shows no
proposal, the inbox reads every open personal request on its own.

**Reason:** an inline diff reads the same at 390 px as at 1280, where two
columns of free text would wrap into each other. Withholding Accept on a
stale base keeps to the contract's rule that applying it would drop the
newer text unread: the hub would answer 409, so the page does not offer
what it knows fails. Personal requests are few, so reading each one costs
little and gives the review the human's current text at once.

**Rejected alternative:** a side-by-side view of both texts, the other
layout the card names; kept as the designer's choice to make, not decided
here. Offering Accept on a stale proposal and showing the 409 afterwards:
a refusal the page could have foreseen. A review that fetched its texts
only when opened: the inbox could not tell a preference proposal from any
other personal request before that.

## The public swarm page is drawn from the hub's reduced body only, with initials, and opens with or without a session

**Id:** d81c0a1a-0d4c-4176-9a85-a56ef9f5975e
**Type:** decision
**Status:** superseded
**Superseded by:** b3982ae9-18ec-4e1a-b383-c8d68d817a71
**Evidence:** inferred
**Source:** docs/api.md §6.22 (the public body: agents only, no avatar, no card ids or titles, no member_id; served at #/s/<slug>), the card tsk-ejtazwt37dhp; the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub serves pictures to visitors, or the designer reworks the page

`#/s/<slug>` renders `GET /swarm/{slug}` before the page asks for a
session, so a member who follows a shared link sees exactly what the
world sees. Agents carry two-letter initials where the members' tab has
pictures; a card held is a count. Off, closed or unknown is one friendly
"no public swarm here" with a sign-in link, the same for all three.

**Reason:** the public page is what someone links to from outside; if a
signed-in member got the members' page at that address, they could not
check what they publish. The hub already strips what the world may not
see, so the page draws nothing from any other read — no member list, no
avatar path, which a visitor could not load anyway (§6.10). One message
for off, closed and unknown matches the hub's uniform `not_found`, which
must not tell whether a project exists.

**Rejected alternative:** sending a signed-in member at `#/s/<slug>` to
the Swarm tab: it would hide the public view from the people who decide
to show it. Generated avatars on the public page: they come from member
ids, which the public body leaves out by design.

## Agents are shown by owner/handle only where the short handle is shared in the project, and one's own profiles always

**Id:** d21eff03-cd0b-4977-9e9f-85eb7cc5cbed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.3 (the global name, shown inside a project wherever two members share a short handle), §8.6 (long mentions, a human comes first, ambiguous_mention), the card tsk-zx7brc52q9xg, 2026-10-25; the dashboard's implementation, 2026-10-25
**Revisit when:** handles become unique per instance, or the designer wants the long form everywhere

One helper (`M.dom.handleOf`) decides per project: an agent whose short
handle another member of the project also has is shown by its `name`;
everyone else, every human included, by the short handle. The picker
uses the same rule on the list it reads, so what it inserts is what the
hub resolves. One's own profiles on the account page always show the
long name; the join panel names them as members are named in the project. The hub's `ambiguous_mention` is put in words by the shared
status line, so every composer says it the same way.

**Reason:** the short handle is what people read and type in a project;
showing `owner/handle` everywhere would lengthen every line for the
rare case. Deciding by the project's own member list mirrors the hub's
rule exactly, so the dashboard never shows a short handle the hub would
refuse in a mention. A human keeps the short one because the hub resolves
it to the human first.

**Rejected alternative:** the long form for every agent in every view:
noise for the common case. Translating the refusal in each composer:
six places to keep in step instead of one.

## A join for an agent that is already a member asks which instance it makes, replace preselected

**Id:** 48b11115-3f26-4f0b-b3c6-7e50cb6d9b90
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's incident: after a lost first join, a new join for the same agent failed with "the agent is a member: new_instance or replaces" and the dialog had no way to say it (tsk-02251dpwm8kp), 2026-10-25; docs/api.md §3.1, §6.17; the dashboard's implementation, 2026-10-25
**Revisit when:** the hub lets a member's join change the membership, or the designer reworks the join panel

When the chosen agent is a member of the project, the join panel shows a
choice instead of role, areas and briefing (whom it reports to has a field
of its own, e69c571c): **Replace
instance** with the member's active instances (presence, cards held) or
**Start another instance** with the team's count against its limit.
Replace is preselected when there is an active instance. The join then
carries only the agent, the expiry and `replaces` or `new_instance`. A
refusal `instance.required`, or `differs_from_membership` on a field the
form sent (the hub checks the membership's fields first; either way the
list on screen was stale), reads the members again and offers the same
choice; the human creates it again.

**Reason:** the usual way here is the incident's: an instance whose
credential got lost, which a replacement takes over with its cards;
another instance beyond the default limit of one is refused anyway. The
membership's fields must be omitted or equal for a member's join, so
offering them would only invite an `invalid`; they change on the card.
The hub's refusal is the final word, as the list may be older than it.

**Rejected alternative:** creating the join right after the refusal with
a guessed choice: replacing revokes a credential, which the human picks.
Keeping role and areas in the form and sending the membership's values:
the human would see fields that do nothing.

## A first join may name whom it takes over from and the hand-over; a message's hand-over links to Messages

**Id:** 3d623647-4575-492b-9252-e215afa0e87e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §3.1, §5.2, §6.2 (contract #896); the card tsk-tj523m1r2z7y; the hub's part (#900); the dashboard's implementation, 2026-10-31
**Revisit when:** the hub gives a message a page of its own, or offers a search for cards and messages a field could use
**See:** views.md#a-join-for-an-agent-that-is-already-a-member-asks-which-instance-it-makes-replace-preselected — 48b11115-3f26-4f0b-b3c6-7e50cb6d9b90 — as of 2026-10-31

The join panel has two more fields for a first join, hidden like the
membership's fields when the chosen agent is already a member:
**Takes over from**, a choice of the project's agent members other than
the chosen agent (for a member bringing their own agent, only their own
agents, as the hub allows), hidden when there is none to choose; and
**Hand-over**, a text field for a card id or a message's number, sent as
a number when it is all digits. The hub's refusals (`first_join_only`,
`not_an_agent_member`, `not_found`, `not_readable`, a member's limit on
`takes_over`) are said in words at the field. A join and a member that
named them say "Takes over from @handle; the hand-over is in …", the
handle linking to the member and a card to its page. A message has no
page of its own, so "message #seq" links to the project's Messages view.

**Reason:** the contract lets the hub check both values, and its answer
is the final word. A text field takes either kind of hand-over without
the panel first reading every card and message. A link to Messages
still leads the reader to where the message is listed.

**Rejected alternative:** a picker of cards and recent messages: it
would read the whole board and the event window for one optional field,
and a message to all from before that window could not be named. An
unlinked "message #seq": it leaves the reader nowhere to look.

## Project memory is chosen on /new with its setup options

**Id:** a8e479be-cb07-49cc-b7bd-b48500903ee1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on project memory and setup cards (docs/api.md §6.1, §6.21, contract #339), 2026-10-25; the card tsk-c8jt63tnztqj (provider read only after creation, the badge policy editable with its snippet in Project settings); hub/src/maity_hub/models.py (`extra="forbid"`: a hub refuses a body field it does not know); the dashboard's implementation, 2026-10-25; the before-launch cleanup (tsk-wgg2t8ngx9xg, tsk-qeh64f8gpvnd), 2026-10-29
**Revisit when:** a second provider arrives, the hub sets something up on a provider change, or the overview gets its badge section (§6.20 names the overview for the snippet)

The create form has **Project memory** (Keep the Why preselected, None)
and the five setup options beneath it in the cards' order (three until
#715 added the CI linter and the published dashboard, 2026-10-30), all
ticked, each sent as `true` or `false`. The dashboard's option has a
**Path** field under it, prefilled with `keep-the-why-dashboard` and
checked as the hub checks it (§6.21: one to five segments, and `..`
nowhere in the value, `a..b` included, as the coordinator settled it on
2026-10-30), its refusal said at the field;
`dashboard_path` is sent only while that option is ticked, and left out
of the request otherwise, never sent as `null`. Project settings show the setup's cards
read only and offer the README badge (`policy.badge`) with its snippet;
the provider itself is changed there since 2026-10-31
(de95eb84-842b-4476-95c6-dcbaf3a98064), until then it was shown read
only with a pointer to a card for an agent. Until 2026-10-30 the form asked
the hub's `/openapi.json` whether `POST /projects` names `memory` and
`setup`, and without them offered neither; since then it always offers
and sends them (e1699490, the alpha rule).

**Reason:** the path is left out with the dashboard unticked because the hub would only
drop it, `null` is `invalid` (§6.21), and a malformed value in a hidden
field would refuse a creation for something the human did not choose. The
form's check is the hub's, not a stricter or looser one of its own: a
refusal only one side makes stops or lets through a creation for no
reason; the hub alone checking would show the error only after sending.
Barring only a segment `..` was rejected: the segment rule already bars
it, and it would let `a..b` through, which the hub refuses.
The badge sits with the other policy
fields that need a reason, until the overview has its own section.

**Rejected alternative:** a provider dropdown in Project settings: it
would invite a change whose consequences the hub does not carry out.
Until 2026-10-30 sending `memory` and `setup` always was rejected
because a creation on an older hub would fail; under the alpha rule no
such hub runs, so they are always sent now.

Until 2026-10-29 the form also sent the `keep_the_why` boolean to a hub
that knew the provider only under that alias (before §6.21). It no
longer does: such a hub is offered no project memory. **Reason:** the
maintainer's rule for the alpha is to delete compatibility layers before
launch, and no hub before §6.21 is running. **Rejected alternative:**
keeping the alias: a third branch in the form for a hub nobody runs.
The hub dropped it from `POST`, `PATCH` and the project view (#606), and
the fixture hub with it: it refuses the field as the hub does.

## Statistics sum counts of things over the window and show people by their busiest day

**Id:** 39d109d7-026a-4d53-b7c2-5fda6ff51b77
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the cards tsk-73gz17sbq1k4 and tsk-h8805v7phn9b and docs/api.md §16.6 (per-day series, counts only, no chart library beyond the dashboard's); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub answers distinct active people per window, or the designer reworks the tiles

Each day series is one row: the window's figure, today's value and a
small line of the days. For registrations, new instances, cards and
reviews the figure is the sum of the days; for humans and agent
instances active it is the highest day ("up to N a day"). The days are
also a folded table, which is what a screen reader reads; the lines are
inline SVG drawn by the page.
Days the hub cannot know (reviews before it kept card history) are a dashed
line at the foot of the row, so every row spans the same width without
drawing an unknown day as a solid zero.

**Reason:** the hub counts a person active once per day, so adding the
days would count the same person thirty times and look like growth that
is not there; a distinct count per window is not in the answer, and the
page invents no number. One line per series keeps every chart to one
scale and one colour, so none needs a legend. Every row spans the same
width so the rows can be read against each other by day, and an unknown
number is never shown as a 0.

**Rejected alternative:** a sum for every series: wrong for people.
A gap for the unknown days: the line starts in the middle of its row. A
solid line at zero: it invents a number.
One chart with all series: eight scales in one axis, and colours that
would need a legend. A chart library: the contract and the CSP keep the
page to its own code.

## Placements are a section of Agents; stop goes at once, restart asks once more, consent stays in the inbox

**Id:** 5273b057-4d96-41b8-bd5f-e52f8828450c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's inbox decision to show the agents' lifecycle beyond spawn (tsk-dkgmeb3gx4nd), 2026-10-25; docs/api.md §15.5–§15.7, §15.10; the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the designer answers on the row layout, the hub lets the dashboard know runner ownership in the placement itself, or placements get a page of their own

Where an agent runs is a section of the Agents view, after the grid:
one row per active placement with what is wanted and what the runner
last reported. Stop and Start are one `PATCH` of `desired` each, Stop
without a question; Restart asks once more inline before its `POST`; a
new join is offered only when the placement's credential is revoked
among the credentials the view already reads. Actions show for a human
admin who is the owner (`owner_id`) of the placement's runner — `GET
/runners` also lists runners attached where one is an admin — or the
agent profile's owner. A placement waiting for consent offers only the
link to its inbox request: there a stop would withdraw it and a restart
approve it.

**Reason:** the agents' cards are where people look for an agent, and
the section reuses the credentials the view reads anyway. Stopping is the
contract's safe direction; a restart ends a working session, so one more
click is worth it. Approving here would duplicate the inbox, the one
place that answers requests, and its audit.

**Rejected alternative:** a column of the members table: Members lists
humans too and has no room for the reported state. A modal confirmation
for restart: one more click inline does the same at phone width. Asking
the hub for each credential to decide on `rejoin`: the view has them.

## An agent is started on a runner from Agents' Where they run, on one's own live runners only

**Id:** 7baa75e7-2cf3-4cb5-ae41-93e04cdb71d9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-dsp6htj4c686 (the owner said yes to req-t9ev5zkeeg00, 2026-11-09: his runner was paired and online, and the dashboard had no way to start an agent on it; a "Start on a runner" form on the Agents page, an existing agent or a new profile, docs/api.md §15.6); the choices below about which runners and tools are offered are the implementer's
**Revisit when:** the hub lets an agent propose a placement from the dashboard (`agents:propose`), a runner of someone else can be attached (§15.4, invitations), or the form needs a field the join panel has and this one lacks (the subagents instruction, a take-over)
**See:** views.md#placements-are-a-section-of-agents-stop-goes-at-once-restart-asks-once-more-consent-stays-in-the-inbox — 5273b057-4d96-41b8-bd5f-e52f8828450c — as of 2026-11-09

Where they run, on the project's Agents, has **Start an agent on a runner**
for a human with members:admin. It offers the runners attached here
(`GET …/runners`) that the human owns, whose credential is live and which
offer the project's repository: one of the runner's advertised
`repositories` matches the repository's URL without `https://`, with the
hub's rule (`check_repository` in `hub/src/maity_hub/placements.py`,
Python's `fnmatch.fnmatchcase`; `fnmatch` in `web/js/placements.js` is its
port, a `[…]` set read as Python 3.12's `fnmatch.translate` reads it, so a
reversed range such as `[z-a]` matches nothing, `[!z-a]` any one character,
and neither throws and hides the runner's other patterns; the name is read by
Unicode character, as Python reads it, so `?` takes a character beyond U+FFFF
whole (an advertised pattern is printable ASCII, `Name` in
`hub/src/maity_hub/routes/runner.py`; the port reads any pattern the same
way); and a `*` is matched by going back only to the last `*`,
not by one RegExp over the pattern, so many stars against a long name take
time in proportion to the two lengths, not seconds). With none, the section says so and links the project's Runners; with
attached runners of which none offers the repository, it says that and
names the repository; a project without a repository offers no form and
says a runner needs one. The agent is one
of the human's own agents here without an active placement, or a new
profile with the join panel's fields (trust, role, reports to, areas,
briefing). Where, tool, mode and model come from what the chosen runner
last advertised: reachable targets, installed tools for that target, the
tool's modes with its default chosen, its models or the runner's default.
Without a tool, Start is disabled. The call is one `POST …/placements`. A
refusal shows the hub's message, code and named fields, and the new
placement is listed by reading the list again. The route asks for no
second factor, so the call is not wrapped in `M.stepUp.run`.

**Reason:** the placements are already shown and steered here, so the
form sits beside them. Offering only what the hub accepts keeps the
choices few: someone else's runner is `forbidden`, a revoked one
`runner_revoked`, an agent placed already `placement_exists`, a tool
that is not advertised `harness_not_offered`, and a runner that does not
offer the project's repository, or a project without one,
`repository_not_offered` (the last added by tsk-wn6qp27090qy, after a
re-check of the merged form found such runners offered).

**Rejected alternative:** the form on the instance-level Runners page:
there the project would be one more choice, and the placements are not
shown there. Free text for the tool and the model: the runner advertises
the lists, and a typo would only be refused by the hub (a tool it does not
know as `invalid`, a model the runner does not offer as
`harness_not_offered`, `_check_spec` in `hub/src/maity_hub/routes/placements.py`).
Listing every attached runner and letting the hub refuse: a choice that
can only fail. Listing a runner that does not offer the repository as
unavailable instead of leaving it out: the other runners the hub would
refuse are left out too, and with none left the section says why.

## Project settings are the project's last tab, not a panel from the gear menu

**Id:** ecbeaecb-2dcf-45ff-ae44-d8b2b455e218
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's feedback of 2026-10-25 ("project settings da oben ist komisch, das muss eher runter auf die projekt ebene, z.B. nach Runners und Why ein Settings wäre logischer", tsk-r7qja01wwzvv) and bug report (a save in Project settings landed on the inbox, tsk-t407bnycxera); the dashboard's implementation, 2026-10-25
**Revisit when:** the settings grow enough to need sub-pages, or the designer renames the tab

The project's settings are a view, `/<owner>/<slug>/settings`, shown as the
last tab of the project's row, after Runners and Why, for every member:
what one may change is a form, the rest read only. The gear menu keeps
what is not the project's (runners, instance administration). A save
redraws the route it was made on, so it stays on Settings; the
overview's Set the repository goes there at the repository field.

**Reason:** the settings belong to one project, and every other thing of
the project is a tab; a panel opened from a global menu read as the
hub's. As a panel it lived under the header of whatever view was open,
and a save, which redraws that view, closed it and left the human on
the inbox.

**Rejected alternative:** keeping the panel and reopening it after a
save: it fixes the jump but not the place the maintainer found odd.

## Signed in, the theme is set in Your account; the header has a theme menu only signed out

**Id:** 4faefa89-4543-48f1-a964-53574a6ded5d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25, together with the instruction of the same day to put Chat and Notifications buttons where the theme menu was; the dashboard's implementation, 2026-10-25
**See:** rendering.md#the-theme-is-set-on-html-by-a-script-in-head-without-defer-the-dark-tokens-answer-the-system-and-an-explicit-pick — ce73e8de-738e-4a8b-89ac-f98ef7d7ed81 — as of 2026-10-25
**Revisit when:** the theme is kept on the hub per human, or the signed-in header gets room to spare again

The theme menu (System, Light, Dark) shows in the header only on the
pages one sees signed out: the sign-in page and the landing page (the
public swarm page went with the contract #697). Signed in, the header has none; Your account has a
Theme section (on its Settings tab, `/account/settings`; `/account/theme` leads there) with the
same three choices as radio buttons and a line that the choice is kept
in this browser only. It is the same per-browser value either way, so a
pick made signed out holds after signing in.

**Reason:** a signed-in human sets the theme rarely, and the header's
top right is wanted for what is used all the time (chat and
notifications). Signed out there is no account to go to, so the menu
stays there.

**Rejected alternative:** the menu in the header and in the account:
it keeps the place the header needs. Keeping the choice per human on
the hub: a contract change for something a browser holds well enough,
and the instruction asked for none.

## At phone width the header's text beside the logo is hidden from sight, not from screen readers

**Id:** d88c7687-5b55-45c7-92e8-6689e2181e06
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25, from a phone screenshot of the cross-project inbox; the dashboard's implementation, 2026-10-25; the project's mark added after his phone screenshots of 2026-10-28 (inside a project the buttons wrapped to a second row)
**Revisit when:** the switcher stops naming the current scope, or the header gets a second line on phones

Below 600 px the span beside the logo (the project's name, "Everything
waiting for you", "Your account", …) is clipped to one pixel by CSS,
the usual visually hidden pattern; on wider screens it stays as it was.
The project's mark beside it is not shown there either (`display:
none`): it is decoration, already hidden from screen readers. The
buttons beside the logo are spaced tighter there (gaps, inner padding,
the counts' padding; the same height), so that with their counts they
stay in the logo's row at 360 px. Only two counts of three characters
("99+") at 360 px still wrap, into the two rows it had before.

**Reason:** on a phone the text crowded the menus, and the switcher's
current tab already names the scope. Inside a project the mark and the
buttons' spacing pushed the buttons into a second row, which moved the
whole page down; the tab shows the same mark. Clipped rather than removed, a
screen reader still reads where the page is.

**Rejected alternative:** `display: none`: it takes the name from
screen readers too, and the page title alone is read only on load.
Shortening the text: the project names are the operators', of any
length.

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

## The header gets a "+" menu to bring someone in; invitations get their own page; Runners lose their tab

**Id:** 3f6eadd3-d1d5-4389-bb65-626e9cdbc1dc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's card tsk-05meme59sq1x, 2026-10-31 (bell between the gear and the profile, a bold "+" right of the Lead button with Agent and User, `/invite` for invitations, Invite user and Join agent on Members, the old invitation form on Members gone) and his word the same day to take the Runners tab out of the project tabs, linked from Project settings instead; docs/api.md §16.11 (`/invite`, contract #919); the dashboard's implementation, 2026-10-31
**Revisit when:** the agents page gets its join at the top (the same card's next part), a project gets more ways to bring someone in, or an endpoint gives the invitations of all one's projects at once (then `/invite` no longer reads them one project at a time)
**See:** views.md#the-row-of-tabs-has-no-new-project-tab-the-tabs-menu-follows-the-tabs-a-dragged-tabs-place-is-a-line — 4ff40142-df78-4c11-8f0c-c0024adecd79 — as of 2026-11-09

The signed-in header reads Lead, Chat (the maintainer's order, tsk-td5c6z21xg5s, 2026-11-01), "+", the gear, the bell, the
profile. "+" is a menu like the gear's with Agent (the agents page) and
User (`/invite`), for humans only; Runner and Project were added later
(4ff40142). `/invite` lists the projects where the
human adds members. The one chosen (`?project=`, as Members' Invite user
links it) shows the invitation form and its list. The other projects
show their lists without a form. Members has two blue buttons at the top,
Invite user and Join agent; its own invitation form is gone. The project
view `runners` keeps its route and its Settings tab mark, but has no tab:
the project's Settings links it. `/invite` reads the projects one after
the other and draws again when another project is chosen. A counter
drops an older pass still reading, as `renderSeq` does in the router;
without it, two passes append their lists twice.

**Reason:** the layout is the maintainer's (confirmed); why is read
from the card, not stated by him: bringing someone in is one act whether
it is an agent or a person, so it gets one place in the header, and an
owner of several projects finds all their invitations on one page. Why
the Runners tab goes was not given (unknown).

**Rejected alternative:** the header first and `/invite` in a later
pull request, which would have shipped a User item leading to no page.
Reading all projects at once with `Promise.all` and no counter: a choice
made mid-read would still append twice.

## The header's Chat badge counts unread chat messages from the notifications, not chats

**Id:** 3ad5cf20-0240-4536-aaef-3bd8b411288f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25 for Chat and Notifications buttons in the signed-in header (tsk-wnk7wv6p4se7), and the coordinator's ruling the same day on the badge; docs/api.md §9.3, §18.2; the dashboard's implementation, 2026-10-26
**Revisit when:** the hub counts conversations with unread messages (a per-conversation count on /me/notifications), or the message count proves misleading in practice

Where the theme menu was, the signed-in header has Chat; since
2026-10-31 the order is Chat, Lead, "+", the gear, the bell and the
profile (views.md#the-header-gets-a-menu-to-bring-someone-in-invitations-get-their-own-page-runners-lose-their-tab — 3f6eadd3-d1d5-4389-bb65-626e9cdbc1dc). Chat leads to `/chats` and carries
`counts.chat` from `/me/notifications`, which the header already reads,
worded "N unread chat messages". `/chats` reads the conversations
across projects (§9.3, `GET /me/conversations`) and shows them in the
hub's order: pinned with unread, unpinned with unread, quiet pinned, the
rest. On a hub
without notifications both buttons stand without a count, the bell as a
link to everything waiting.

**Reason:** the hub has no list of conversations across projects; the
instruction asked for unread chats, but counting them would mean one
§9.3 call per project on every count refresh. `counts.chat` costs
nothing extra and needs no hub change; the view itself may read every
project because it is opened rarely.

**Rejected alternative:** counting conversations with unread messages
from one §9.3 read per project each refresh: N calls every cycle. A
per-conversation count added to `/me/notifications`: the cleaner
number, but a contract change, kept as the follow-up should the message
count mislead.

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

## A Keep the Why notice about an agent leads to its project's Members, or to one's agents on the account

**Id:** be999be7-325a-4fcf-954a-2bdadb6e6f84
**Type:** decision
**Status:** superseded
**Superseded by:** none — the notification kind `keep_the_why` was removed on 2026-10-26 (docs/api.md §18.2, "No longer notifications"), so the dashboard has no such item to link anywhere; an unconfirmed commitment now reaches the owner as a request in the inbox (§6.23), linked like every request
**Evidence:** confirmed
**Source:** docs/api.md §6.23 and §18.2; the coordinator's ruling of 2026-10-25 on the item's target and the interim place (tsk-bq6q65910g13); the dashboard's implementation, 2026-10-26
**Revisit when:** the dashboard gets a page of one's agents outside any project

The `keep_the_why` item names the agent as `target: {type: "member"}`.
Where the owner is a member of the project it opens
`#/p/<slug>/team/<agent id>`; where not, `#/account/picture/<agent
id>`, the list of one's agents on the account, with that agent marked
and focused.

**Reason:** the owner of an agent need not be a member of the project the
agent works in, and cannot open that project; the account's list is the
one place the dashboard shows all of one's agents.

**Rejected alternative:** the cross-project inbox (`#/all`), where other
items of a project one cannot open go: it says nothing about the agent.
A new page of one's agents: the right place, but beyond this change; the
link moves there once it exists.

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

## The global chat updates from the notifications stream, not from any project's events feed

**Id:** dc0a02f8-c657-406a-8f63-f260b588e7e8
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's card for the global chat (tsk-z8z8cg56y00s), 2026-10-26, after that day's incident of an events long-poll multiplied by open tabs; the dashboard's implementation, 2026-10-26; the list across projects (§9.3, GET /me/conversations) read once instead of per project, 2026-10-28
**Revisit when:** the hub offers a per-user chat stream, or the notifications stream stops reporting chat messages

`/chats` shows every project's chats in the Chat tab's layout and opens
one in place with chat.js's own pane, in that project's context. It opens
no events long-poll: the notifications stream (js/notify.js), which every
signed-in page reads anyway, says that something changed; the global view
then reads its conversations once a burst has settled (0.4 s), but only
for an answer with a chat or mention item in it, or one that moved the
chat counts (since 2026-11-08, c5a75e7f): in one
read across projects (`GET /me/conversations`, §9.3; until 2026-10-30
each project's list on a hub without it, e1699490). The open conversation fetches what came after its last
message, as its project's feed would have made it, and reads its newest
page and (for a group chat) itself again, to take over what the stream
cannot name: a removal, a deleted file, a rename, a change of who is in it
or of closed. The lists and the members are also read every 30 seconds, as
a project's Chat tab does. All of it is one update at a time, with at most
one more pass for whatever was asked meanwhile; the open chat's re-read
and its delivery check take one page per pass and go on from there the
next time, so no nudge reads a whole history.

**Reason:** a feed per project, or even one for the open conversation's
project, multiplies with every open tab; that multiplication was the
incident of the same day. The stream already carries a chat message as a
notification for its human party, so it is enough to know when to read.

**Rejected alternative:** one events feed per project the human is in: the
incident's pattern, N long-polls per tab. Only the open conversation's
project's feed (the card allowed it): still one more long-poll per tab,
and the list of the other projects would still need the stream. Polling
the lists every few seconds: more reads than the stream for slower news.

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

## The Agents page reads credentials only for its own agents that are placed

**Id:** a71aebc3-1d25-4e28-90ce-f96f8c716c02
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the performance measurement on tsk-a5pxwgkgr73e (step 1, 2026-11-08: 27 credential lists at once, queuing from 95 to 568 ms); the plan on tsk-d61rvjm6gteh (PR C), approved by the coordinator the same day
**Revisit when:** the placements list carries whether its credential was revoked, or the member list carries the credentials

A project's Agents page read the credentials of every agent of one's own
in it, at once, before the "Where they run" section could draw. That
section needs them only to know whether a placement's credential was
revoked, which decides whether **Restart with a new join** is offered. It
now reads the placements first and asks for the credentials of one's own
agents that have a placement, once each; a placement that appears later
asks for its agent then. It listens for placement events before its first
read, and reads the list again once it stands if one came meanwhile.

**Reason:** on the measured project those reads were the page's slowest
part, and most of them served nothing: few agents have a placement.

**Rejected alternatives:**
- The credentials read when a row is expanded: the rejoin choice stands in
  the placement row as it is drawn, so the read would only move.
- The revoked state in the placements or member list: one read less, but a
  contract change, which this card's boundary excludes.

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
  the reader. Taken up on 2026-11-10, after prod measured the closed
  window as the board's longest wait: [the board draws once the open
  groups have answered](#the-board-draws-once-the-open-groups-have-answered-the-closed-columns-follow).
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

## Registration is offered where the hub registers or the invitation one comes from admits

**Id:** f1e41ebd-42a8-484b-b260-f69ee036a00c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.7, §2.7.1 and §3.4; the coordinator's ruling of 2026-10-26 that the registration page is built with the invitation card (tsk-55xeem2xbht5); the dashboard's implementation, 2026-10-26
**Revisit when:** `GET /auth/methods` starts to say something per invitation, or registration gains a way in that is not an address and a password (OAuth, §2.7.1)

`/register` shows its form where `GET /auth/methods` says
`registration: true`, or where its `next` is an invitation whose page
says `registration: sign_in_or_register`. Otherwise it says the hub does
not create accounts on request and leads to sign in. After the request it
always says "check your mail", for every address alike.

**Reason:** under `closed` or `allowlist` an address-bound invitation
admits its address (§3.4), but `GET /auth/methods` keeps the instance's
mode and so says `false`; the invitation's own answer is the only place
the page learns that this person may register. The hub answers every
well-formed request the same, so the page must not suggest it knows
whether an account will be made.

**Rejected alternative:** the form for everyone, the hub sorting it out:
on a closed hub every visitor would fill it in for a mail that never
comes. Only `GET /auth/methods`: an invited person on a closed hub could
not register at all, which §3.4 allows.

## The registration form names the instance's terms before the mail is sent

**Id:** 48c34360-b586-4e82-b21a-737b922f1734
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.6.1, §2.7 and §2.7.2; the card tsk-46vft0764kve (the terms from `terms`), the review of #652, 2026-10-29; the coordinator's ruling on an empty allowlist, 2026-10-29
**Revisit when:** acceptance moves from the link's page to the form, or terms gain more than a URL and a version (§16.4)

Where `GET /auth/methods` answers `terms`, `/register` says that
completing the account accepts this hub's terms, with their version. It
links the terms only when `M.dom.safeUrl` passes the address (plain
`https`, no user info); otherwise it names them without a link. The
hub answers `registration: false` under `allowlist` while both lists
are empty, so neither the login page nor `/register` offers a way in
that nobody could finish; the instance admin sees the gap as
`missing: ["allowlist"]` (§16.4).

**Reason:** the terms are accepted on the link's page, where their
version is signed with the registration token (§2.7.2). Without a word
on the form, a person would meet them only after the mail, and might
find out only there that they do not want to accept them.

**Rejected alternative:** a checkbox on the form: it would record
nothing, since acceptance and its version belong to the completion's
`POST` (§2.7.2), and it would suggest a second acceptance. Linking any
URL the hub returns: the hub checks `https`, but the dashboard does not
rely on that alone. `registration: true` under an empty allowlist, as
the contract first said: every address would get the form and the mail
silence of a request that is dropped, a dead end for everyone.

## An agent is named with the instance that wrote or did it, as <handle>#<id>

**Id:** 0b6d2a5f-32ba-4979-8c18-1567498ecbac
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish relayed by the coordinator (tsk-6sxbvsf87219), 2026-10-27: when a handle has several instances it must always be visible which one wrote; docs/api.md §6.17 (the dashboard shows `<handle>#<id>`, every work record carries the instance), §9 (`from_instance`), §7 (`asked_by.instance`), §8.1 (`actor.instance`); the dashboard's implementation, 2026-10-27; the maintainer, 2026-10-31 (tsk-bczgjkfpw1wg): `@handle#id` offered by the @ picker and shown as two links everywhere
**Revisit when:** the contract gives an instance a name of its own or a view of its own, or the hub names harness and model on a chat message

`M.dom.memberRef` takes `opts.instance` (an id, or a record with
`instance`, `harness`, `model`). With one, an agent reads
`<handle>#<id>` (`owner/handle#id` where two agents share the handle,
`@…` where the view names handles; the name, where a reference read
across projects carries no handle), the `#id` muted, a link of its own
beside the handle's and not in it, with
"Instance <id> · <harness> · <model>" as its tooltip where the record
says them (an event's `actor` does, a chat message does not). Chats
(direct, group, global), the project messages, the ticker, the inbox's
asker, the overview's reports and a card's notes and history pass what
their record carries; without an instance, or for a human, the name stays
as before. An id that is not an instance id is not shown. In a chat two
instances of one agent are two senders: their messages are never grouped
under one name. The handle leads to the member's page, the `#id` to
the same page's Sessions with that instance's line marked and focused
(`…/team/<id>/sessions/<instance>`), where no link is possible (a
member the project does not list, a view from outside) both stay text.
A stored mention `@handle#id` in a text reads the same: two links, the
member and its instance. The @ picker offers, after each agent, its
instances that are not revoked as `@handle#id`, a dormant one marked,
in the slots the members leave free, so a short `@` shows as many
members as before; typing `#` after a full handle narrows to that
agent's instances. An address naming an instance the member does not
list says so on Sessions instead of marking nothing. Until
2026-10-31 the `#id` led nowhere (the designer's pass on #429: it
names, it leads nowhere else); the maintainer asked for it to lead to
the instance.

**Reason:** a team of instances shares one membership and one handle,
so the name alone cannot say which session wrote; the instance id is the
address the contract already gives it. Keeping it in the one helper keeps
the form the same on every page.

**Rejected alternative:** the handle and the `#id` as one link: the two
lead to different places, the member and its instance, and one link
could only reach one of them. The `#id` leading to an instance view of
its own: the contract has none, the member page's Sessions already lists
the instances. The display name with the id after it: the
contract names an instance by handle, and that is what a reader types to
reach it (`@handle#id`). Showing the instance only on hover: the
maintainer wants it seen without looking for it.

## In the global chat an agent's message names its projects by logo, from the reader's own member lists

**Id:** bb8a9b29-8be9-4843-872c-07bd3e38641d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish relayed by the coordinator (tsk-p94e7njrmg1p), 2026-10-27: in the global chat every agent message shows the projects the agent is in, as the project logo with the name on hover, never a project the reader may not read; docs/api.md §11.2 (the logo), §6.3 (the member list); the dashboard's implementation, 2026-10-27
**Revisit when:** the hub lists an agent's memberships across projects for a reader, or the global chat shows chats of projects whose member list the page has not read

`/chats` reads every project of the reader's context anyway (members
included, for the names); `projectsOf(memberId)` is those of the
reader's projects whose member list names the agent, in the switcher's
order, each drawn with `M.projectMark` (the logo, else the monogram),
the name as tooltip and as hidden text for a screen reader. It is set on
the global chat's project contexts only, so a project's own Chat tab
shows none. A human's message and the reader's own show none.

**Reason:** the reader's own member lists already say every project the
reader may see the agent in, and only those; a project the reader is not
in never reaches the page, so nothing private can show. No new hub call
and no contract change were needed.

**Rejected alternative:** a hub list of the agent's memberships: it
would have to filter by the reader's `project:read`, which is exactly
what the reader's own project list is. Showing the project names as text:
the maintainer asked for logos, and several names would crowd the line.

## An agent card's admin actions sit in one Actions menu; the pause form opens from it

**Id:** 0d1a03cd-81e9-4895-af2d-ef8dc54806a6
**Type:** decision
**Status:** superseded
**Superseded by:** 1c00024d-a3a6-49bc-ba2e-704359713aeb
**Evidence:** confirmed
**Source:** the designer's pass part 3 on #366/#369 (tsk-w2xnkrwf147m), 2026-10-27: every agent card carried an open Pause form with its hint, which made each card about twice as long
**Revisit when:** the member page header gets its own Actions menu (the designer's overview handover), so both can share one list

An admin sees **Actions ▾** at the end of an agent card's header
(`M.menuButton`) with **Pause…** and **Edit briefing** (or **Write a
briefing**). The pause form stays in the card, folded; **Pause…** opens
it and focuses the reason, **Cancel** folds it again. A paused agent
keeps its one **Clear pause** button in the card. The briefing's text
and its own edit button stay, since they are content, not a control.
Revoking stays beside each credential in the card's list.

**Reason:** one control in the header keeps the cards short and
scannable; the actions are rare, the facts are what is read.

**Rejected alternative:** Revoke… in the menu, as the designer sketched
it: revoking is per credential, and an agent may hold several, so the
menu would need a second choice the credential list already makes. A
dialog for the pause: the folded form keeps its hint and status in
place and needs no focus trap.

## The header with the lockup is in the page itself; loading and failure stand centred under it

**Id:** d48f94c1-fbdf-4f81-b16d-896fe74535ce
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's feedback relayed by the coordinator (tsk-vb0dgwhrkvsn), 2026-10-27: on a phone, while the app loads or cannot load, the page was a blank strip with "Loading…" top-left; wanted the header with the logo at once and kept on failure, the loader centred, the same for the failure, static so it shows before JavaScript runs; the designer's pass on #433, 2026-10-27 (no red alarm box: a calm block, plain words, the reason folded, Try again primary at the edge; the loader after 300 ms); the dashboard's implementation, 2026-10-27
**Revisit when:** the header's first row changes, or the page gets a shell that renders on the server

`web/index.html` holds the header's first row as `brandTitle()` draws
it (the lockup, one file per theme), so it is on screen before any
script or hub call; every view redraws the header as before. The loader
(`p.page-loading`, 48 px with "Loading Maity…" under it, shown after
300 ms so a fast load never flashes it) and a page that could not load
(`div.page-failed`: the mark at 50 %, a title in plain words, what to
do, the reason under Details, a primary **Try again** that shows the
loader and loads again, and **Sign in again** on a 401) are centred in
what the header leaves of the screen: `body:has(> main >
…)` becomes a column of the screen's height and `main` takes the rest.
A browser without `:has` shows them at the top, as before.

Since 2026-10-30 the lockup is a link home (the maintainer's wish, the
card tsk-vqn9m1qt4rtt): signed in to everything waiting (`/all`),
without a session to the instance's start page (`/`), the static
header's link `/` as no session is known yet. The link carries the
accessible name ("Maity: everything waiting for you", "Maity: home");
the two pictures have empty `alt`, since only one of them shows and the
name would otherwise be read twice or be the bare word.

**Reason:** the first thing a person sees should say where they are, and
a failure should not look like a broken page; plain HTML and CSS show
before the scripts load, which on a slow phone is the longest wait. A
selector on what `main` holds needs no class to set and none to forget
to remove when the first view arrives.

**Rejected alternative:** drawing the header from JavaScript first: it
waits for every deferred script. A class on `main` that the router
removes: one more step every path to a view must remember. The error box
as the failure: red in an empty screen reads as a crash, and a file path
as its title is the system talking to itself.

## The keys that send stand beside the send button, named as the keyboard prints them

**Id:** dbb154d5-b5cf-4e9d-884f-0e9467a6788a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish relayed by the coordinator (tsk-00q3ddrh7a1q), 2026-10-27: users should see that Ctrl+Enter sends; the hint in the field label went unnoticed; on the button or as its mouse-over, both fine; the designer's pass on #431, 2026-10-27 (left of Send in one action row, not twice, hidden on a phone); the dashboard's implementation, 2026-10-27
**Revisit when:** the designer reworks the composers, or the dashboard gets a language setting of its own

`M.dom.sendOnCtrlEnter` puts the keys, once the view is on the page,
right before the button that sends (the one it was given, else the form's
submit button), the two one group (`span.send-with-keys`): a muted
`span.send-keys`, hidden from a screen reader, which reads the button's
`aria-keyshortcuts` instead; the button's tooltip says them too. The
chat composers (direct, group, global) have one row of actions, Attach
at the start and the keys with a primary Send at the end; their label
says the keys to a screen reader only, so they are not seen twice. At
phone width the hint goes and the button is laid out as before. `sendKeysFor` names them:
⌘+Enter on an Apple device (platform or user agent), Strg+Enter where
the page's `lang` or else the browser's language is German, Ctrl+Enter
otherwise. A device that only knows touch (`hover: none` and
`pointer: coarse`) shows none.

**Reason:** people look at the button when they are about to send, not
at the label above the field; one place in the helper reaches every
composer that sends this way, today's and later ones. Keys named as the
keyboard prints them are found on it at once.

**Rejected alternative:** the keys inside the button's text ("Send ·
Ctrl+Enter"): the button's name for a screen reader and every test of it
would change, and a narrow composer has less room for it. The tooltip
alone: it is not seen without a mouse resting on the button.

## The overview leads with what needs the reader; its README badge is shown there and changed in Settings

**Id:** 057e7277-3eba-4267-93d2-c6b74a5e2ff1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's handover on the overview (#6484, tsk-qse9t2b3a9n8), 2026-10-27: the five panels had equal weight and the one thing to act on (open requests) sat bottom left; the maintainer's wish for a Contract link in the project facts (tsk-yhbmz7mjng7n, step 1), 2026-10-27; the dashboard's implementation, 2026-10-27
**Revisit when:** the hub serves the contract for reading inside Maity, or the overview gets other editing in place

Waiting for you and Board come first, then Team and Latest reports;
Project and README badge stood under Team (d7ee1073 below) and are the
Overview's Project tab since 2026-10-30 (58c58a28-d6b1-453f-99dc-7f21179b3ee2). A member in a list is a chip
(`M.dom.memberChip`), the shared form the member page header will use
too. The Contract link is `docs/api.md` on the forge at the repository's
default branch, built only for GitHub and GitLab, whose path shapes are
known. The badge panel shows the state, the badge and the snippet to
everyone; an owner or admin is sent to Project settings to change it
(**Change in Project settings**).

**Reason:** a person opening the overview comes to see whether anything
waits for them, so that is the first thing, with its action one click
away. The badge is changed in one place, Project settings, where the
project's other policy lives. Until #618 a badge change also needed a
logged reason, which Settings asked for; that argument fell away when
the badge alone needed none (docs/api.md §6.20, re-checked with the
coordinator on 2026-10-29), and the one place to change it is what
remains.

**Rejected alternative:** the designer's radio pills that change the
badge on the overview: a second place to change one setting, with the
overview the only view that edits in place. A Contract link guessed for
any forge: a wrong path shape would be a dead link that looks right.

## Project and README badge stand under Team, before Latest reports

**Id:** d7ee1073-1752-4134-9e51-878c5c28f2c2
**Type:** decision
**Status:** superseded
**Superseded by:** 58c58a28-d6b1-453f-99dc-7f21179b3ee2
**Evidence:** inferred
**Source:** the maintainer's screenshot and wish on tsk-b67chbx96n29 ("move the two blocks in front of Latest reports"), as the coordinator passed it on, 2026-10-30: on a wide desktop Project and README badge were a row of their own below the whole report list, with empty space under Team; the place under Team is the implementation's choice from the two the coordinator named
**Revisit when:** the maintainer asks for another place, or the overview gets a panel that competes for the space under Team
**See:** views.md — 057e7277-3eba-4267-93d2-c6b74a5e2ff1 — as of 2026-10-30

The second row is Team with Project and README badge under it
(`.overview-stack`), and Latest reports beside them. On a phone, where
the row wraps, the order is Team, Project, README badge, Latest reports.
That phone order follows from the page's own order alone: the smoke test
checks the order of the elements, not how the row wraps, so a CSS
`order` on Latest reports would put it first on a phone without a red
test.

**Reason:** Latest reports is a long list; whatever came after it was
out of sight, while Team left empty space beside it. Under Team the
facts fill that space on a wide screen and still come before the
reports on a narrow one.

**Rejected alternative:** Project and README badge as their own row
before the reports: on a wide screen it leaves the empty space under
Team and pushes the reports, the second thing a reader looks for,
further down. Keeping the three rows and only shortening the report
list: the wish was about the order, not the length.

## Abuse reports are a section of /admin: the snapshot as text, each action said before it is sent, a suspension asked first

**Id:** f4e5de2b-d329-444e-b98f-1ea8888b147a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's launch card tsk-d4ppa9jsj0d7 (the hub has the routes, the dashboard had no screen), 2026-10-30; docs/api.md §16.8 (the snapshot is the one content an instance admin reads; text untrusted; the four actions; a suspension lifted only by the operator)
**Revisit when:** reports get a target of their own for organisations, or an admin may lift a suspension from the dashboard

The instance admin's **Reports** section (`js/admin-reports.js`) lists
the reports as the hub orders them (open first, newest first), filtered
by status and type; it opens on the open ones, though the hub's default
is all, because the open ones are the admin's work. One opened shows the reporter's text and the
snapshot, every field as plain text in `pre` or a definition list,
never as markup or a link. The action is chosen from the four with the
effect of each said under the choice. **Suspend** asks for a
confirmation naming the target. A resolved report can be resolved
again to replace its action, and **Dismiss** then lifts its hold.

**Reason:** the snapshot is untrusted content that someone chose to
report, often because it is hostile (prompt injection, spam); shown as
text, nothing in it acts. A suspension ends every session and
credential of an account at once and only the operator lifts it, so it
is the one action asked twice.

**Rejected alternative:** opening the reported target in its project:
§16.8 gives the admin no read of the project, only the copy. Confirming
every action: dismiss and hide are undone by resolving again, and a
dialog for each would teach clicking through.

The fixture hub (`js/api.js`) mirrors `/admin/reports`; the e2e step
`reports_admin_step` checks the shapes against the real hub, because
the fixture's default status, its `closed_at` on a second resolve and
the snapshot missing from its `resolve` answer had drifted once (review
of #778).

## The limits per person are chosen as a number, no limit where the contract has it, or the default, the environment's shown locked

**Id:** 28adb478-d5fa-450b-9bbd-e985d93405c4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's launch card tsk-d4ppa9jsj0d7 (the hub had `GET`/`PATCH /admin/settings/limits`, the dashboard no screen), 2026-10-30; docs/api.md §16.5 (the values, `unlimited`, `null` restores the default; `max_aliases` 1–8 without `unlimited`), §16.2 (sources), §2.8.4 (step-up); the dashboard's implementation; card tsk-1zng488dbprp (`max_aliases`), 2026-11-06
**Revisit when:** plans set the limits per plan (§2.7, part two), or the hub adds a limit

The **Limits** section (`js/admin-limits.js`) shows each value with a
choice of how it is set — a number, no limit, or the default — the
number field only for the first, the value's source in words and the
people at or over it. A bounded value (today `max_aliases`, 1–8)
offers only a number or the default, because the contract has no
"no limit" for it and the hub refuses `unlimited`. A value from the environment is shown, its
controls disabled. Only changed values are sent: a number, `unlimited`,
or `null` for the default; the call goes through `M.stepUp.run`, so a
missing second factor or password is asked where it stands.

**Reason:** the contract gives three different meanings — a number,
"no limit" stored by the admin, and the default restored by `null` —
and one number field cannot say the last two apart; an empty field read
as the default would be guessing.

**Rejected alternative:** a single number field with "0 means no
limit": the hub refuses 0 (`invalid`), and the default would still need
a gesture of its own.

A refusal whose `fields` name no field shown here is said in the status
line, because a display at the fields only would swallow it (merge of
#782 into #778).

## The instance admin area shows one section at a time

**Id:** 4c499cf2-cd9d-4ce1-be8d-639aa32306b6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's pass part 3 on #371 (tsk-w2xnkrwf147m), 2026-10-27: the admin page was one scroll of about 5,000 px (Statistics, Users, Mail settings, Landing page, Instance information); docs/api.md §18.2 (a `registration_pending` item links to Admin → Registration; until 2026-11-04 a `report_open` item to the report in Admin → Reports, since then a report's request in the inbox, §16.8) and the review of #778, 2026-10-31
**Revisit when:** a section other than Registration and Reports needs a link of its own, or the area grows past one row of buttons

`/admin` reads every section as before, then shows one: a row of
buttons at the top names them (`aria-pressed` on the shown one), and the
page opens on the first, Statistics. A section whose read fails says so
in its place (until 2026-10-30 a section the hub did not serve left the
row, e1699490). The others stay
in the page, hidden, so a form half filled in keeps what was typed.
The two sections a notification or a request leads into have an
address: `/admin/registration`, and `/admin/reports/<id>`, which opens
that report as well (the target of a report's request, entry
f50ed8ee-5948-43c8-817a-d1b008bf1f5a). The page is the same, opened on that section; the
section is found by the hub path it reads, not by its label, which is
translated.

**Reason:** the admin comes for one thing at a time; five long sections
under each other hid all but the first below the fold.

**Rejected alternative:** a sticky list of anchors over the whole page,
the designer's other option: the scroll stays 5,000 px, only the jump is
shorter. A route for every section (`/admin/users`): only the two
sections a notification or a request names need a link. The older Users page at `/admin/users` was removed
before launch with the other compatibility routes, so that address is
now no view at all.

## A dormant instance is said with its address wherever the instance is shown, and put to rest where an agent is managed

**Id:** b4065586-3275-4bfe-a3a0-c5b45d720d61
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-p6edzbw9gwjp, 2026-10-31; docs/api.md §6.17 ("A dormant instance", contract #817), §6.12 (`source: dormant`), §6.2 ("Another owner's agent"); the maintainer's ruling that each action has one place (#643)
**See:** https://github.com/oliver-zehentleitner/maity — 9d2cc07a-0158-4042-ad71-eb9801ceaf77 — as of 2026-10-31
**Revisit when:** the hub lets an agent put a sibling to rest, or a dormant instance gets a reason or an end of its own

A dormant instance reads "dormant — ask @<handle>#<id> directly" in
every place that shows the instance:
- the presence cell on Members;
- the member's Sessions tab;
- the organisation tree;
- the chat's instance picker.

When every instance is at rest, the member's row also says that only an
instance address reaches it (`availability` `limited`, `source:
dormant`). Putting an instance to rest and waking it is a list of the
instances, one button each, in the agent's Manage row on Members and on
its owner's card on Agents. It is offered to the profile's owner and to
a human with `members:admin`. An admin's change to another owner's agent
comes back as that owner's consent request, said as "not changed yet".
The team's lead instance gets no button, because the hub refuses it.

**Reason:** the instance is kept so that someone can still ask it, and
that only works if the address that wakes it is in view wherever
someone looks for the agent. The setting goes where the pause and the
rulebook already are, one place per action (#643). The member page
stays for reading.

**Rejected alternatives:**
- A "dormant" pill without the address: the reader would still have
  to work out how to reach the instance.
- The buttons on the member page: it only leads to Members and Agents
  (dda6f237).
- Offering the lead and showing the hub's refusal: a button that
  always fails teaches nothing. The hint says to choose another lead
  first.

## An invitation's link via the join host is offered only where the hub names one

**Id:** 35607b9c-4a72-4936-bcf8-63a429436ab9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.4 (`via`, "the dashboard's invite form shows 'link via <join host>', on by default, only when a join host is configured"), §1.1, §2.6 (`join_url` of `GET /auth/session`); the card tsk-053hsymxx1p8; the coordinator's ruling against a check of the machine form (the maintainer's alpha rule: no compatibility layer; the dashboard and the hub ship together, the hub's part #681 first), 2026-10-30
**Revisit when:** joins (§3.1) get the same choice in the join panel, or the e2e gets a join host of its own

The invite form reads `join_url` from `GET /auth/session`. Only when it
is set does it show **Link via <join host>**, ticked; it then sends
`via: "join"` or, unticked, `"public"`. Otherwise it sends no `via` and
the hub picks the link (`public`). The list says which link went out,
where a join host is named. The form takes `join_url` from the session the
page has read already (`M.api.session()`); that stays fresh because the
app reads the session again for every page it draws. The browser e2e
has no run with `MAITY_JOIN_URL`: the join URL must be https (§1.1), and
with a join host every join line defaults to `via: join` (§3.1), so the
e2e agent's `maity join` would go to a host that is not there; the join
host is checked after each deploy instead (`join-host.sh verify`).

**Reason:** the contract makes the choice exist only with a join host,
and a link to a host that does not exist would lead nowhere.

**Rejected alternative:** also asking the hub's machine form whether it
takes `via`, so a hub from before the field is not sent one: a
compatibility layer, which the alpha rule leaves out; the dashboard and
the hub ship together, the hub's part first. Always sending `via`,
`"public"` without a join host: the same as sending none, one more
field to keep right.

## Registration in the admin area: missing beside the fields, a block lifted by its typed address

**Id:** 9e0abafa-9fb3-41ba-b9b0-648e7e9523c0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.4, §2.7, §2.7.5; the card tsk-64tktcnndzk3 (the maintainer found no registration setting, 2026-10-29); the dashboard's implementation, 2026-10-29
**Revisit when:** the hub lists blocked addresses, or approval gets mails of its own (#280)

The Registration section says first what the hub does now
(`effective_mode`) and, beside the fields, in words what keeps
registration from working (`missing`: mail, an empty allowlist). A value
the environment sets, or terms that come from the legal pages, is shown
with its source and not offered. Lifting a block takes a typed address,
since the hub has `DELETE /admin/registrations/blocks/{address}` but no
list of blocks.

**Reason:** a mode that is set but not in effect (no mail) looks like
open registration that does not work; saying the gap where the admin is
looking avoids searching for it. A field the hub would refuse
(`set_by_environment`) is no choice. Without a list, a typed address is
the only way to the endpoint.

**Rejected alternative:** the mode alone, with the hub's refusal on
saving: the admin would learn of missing mail only by trying. A list of
blocked addresses kept by the dashboard: it would show only what this
browser lifted or saw rejected, not what the hub holds.

## A decision on a waiting account refreshes the counts, not the registration form

**Id:** 3f98cded-98a8-45d6-9cff-b92b3f531275
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the review of #660 (P3), web/js/admin-registration.js, docs/api.md §16.4, 2026-10-29
**See:** views.md — 9e0abafa-9fb3-41ba-b9b0-648e7e9523c0 — as of 2026-10-29
**Revisit when:** the settings form and the pending list move to separate views, or the hub sends the counts with the decision's answer

After Approve or Reject the Registration section reads
`GET /admin/settings/registration` again for `pending` and the hour's
counts, and redraws only those lines with the mode in effect and what is
missing; the form under them keeps what the admin has typed and not
saved.

**Reason:** the form and the list share one section; redrawing the form
from the hub's answer threw away unsaved edits without a word, while
the only thing a decision changes there is the counts.

**Rejected alternative:** redrawing the whole section after a decision,
as first built: unsaved edits lost. Redrawing the form only when it is
unchanged: it needs a comparison of every field with the hub's values
for nothing the counts alone do not already give.

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

## A chat opens on its newest page in two requests; older pages on scroll-up

**Id:** fcc59a72-46a0-4741-9d6f-abada05edab6
**Type:** decision
**Type:** constraint
**Status:** needs-review
**Evidence:** confirmed
**Source:** the maintainer's report that chats grow slower and slower (tsk-r1adgwp0a5dr), 2026-10-27, and the rule from the incident of 2026-10-26: no request whose cost grows with history; docs/api.md §9.1 and §9.2 (`before` marks nothing read, `after` marks and delivers, a group chat's window); measured in web/tools/smoke.js on a 2000-message chat: 10 requests and 2000 messages drawn before, 2 and 50 after
**Revisit when:** the hub can read the newest page and mark it read in one request (the Messages view pages through the project messages listing, §8.8, since 2026-11-04: 8e483bb1)

Direct and group chats read the newest 50: back with `before=` (the
list's last message, else the largest integer), then forward from the
first of them with `after=`, which marks them read and delivered as
opening a chat always did; in a group chat that forward read keeps to
the window, so what lies before one joined is offered, not shown.
Older pages come near the top or with **Show earlier messages**, the
reader's place kept by the height drawn in front. At the newest, more
than 300 drawn are cut to 100 and read again on scroll-up. Reading
along from outside, the 30-second re-read takes the newest page only.

**Reason:** a request whose cost grows with history slows every opening
of a long chat and, multiplied by readers, loads the hub; two requests
per opening and one per older page stay the same however long a chat
grows.

**Rejected alternative:** one forward read from the newest seq minus a
guess: seqs are the project's, not the chat's, so no guess finds the last
50. Reading back only: it marks nothing read, so the unread counts
would never fall. Keeping everything drawn: the DOM of a chat open all
day grows without bound.

## The ticker's contract implementers are edited as lines of text

**Id:** b1c60ee1-addd-4e0f-897c-937fcdea8b29
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's wish for ticker settings in Project settings (tsk-a3cj2canahy3), 2026-10-27; docs/api.md §17.3 (a map of up to 200 sections to up to 20 tokens each, `*` for the rest, the view to show unresolved tokens); the dashboard's implementation, 2026-10-27
**Revisit when:** the mapping grows past what a textarea reads well, or the hub validates and names unresolved tokens itself

`settings.ticker.contract_implementers` is a textarea of lines
`<section>: <token> <token>`, the contract's own notation; the form
checks each line and token before sending, sends the setting whole, and
says the tokens that name nobody now (a member not in the project, a
role nobody holds, an area no member owns) under the field.

**Reason:** the mapping is a list a maintainer writes once and reads
often; lines match how the contract writes it and how a reviewer would
paste it, and 200 sections fit.

**Rejected alternative:** a row per section with pickers for areas,
members, roles and trusts: many controls for a short list, and it could
not hold a token that names nobody yet, which the hub accepts.

## An agent's owner sets whom it reports to, on Members and on Agents, without members:admin

**Id:** c848b045-9411-43b3-8763-2fd998270a1d
**Type:** decision
**Status:** superseded
**Superseded by:** e69c571c-3365-433a-b26d-245efff28a7d
**Evidence:** confirmed
**Source:** the maintainer's report (seq 16183) that a member who owns an agent found no field for whom it reports to, and the card tsk-0s3gztb6jba7, 2026-10-30; docs/api.md §2.3 ("A human may always set the reports_to of an agent they own to null or to a member they own …, whatever their trust and role"), §6.2 ("Across owners", "Pending"); the coordinator's ruling on the withdrawal button, 2026-10-30
**Revisit when:** the contract settles whether the owner may start a cross-owner edge, or gives the member view the pending edge (`reports_to_pending`); the hub's owner path (tsk-fw3x5c13vq9g, #759) lands

Without `members:admin`, one's own agent's row on Members has
**Manage**, holding only what its owner sets: **Reports to**, the
owner's preferences switch and the rulebook. **Reports to** offers
nobody, oneself (where a member here) and one's other agents in the
project, without those that would close a circle, and sends only
`reports_to`. The project's Agents shows the same form beside the
rulebook. A boss of another owner is never offered; one set already
stays chosen, marked, so that saving keeps it.

There is no **Withdraw** for an open cross-owner request about the
agent: §6.2 says nothing in the member view shows a pending edge, and a
request names no member, so the page could find it only by its title,
which a wording change would break. It comes with the contract's answer
on cross-owner edges (a field such as `reports_to_pending` for the two
owners).

The page and the fixture hub went ahead of the hub: until its owner
path for §2.3 (tsk-fw3x5c13vq9g, #759) is merged, the hub answers this
`PATCH` from an owner without `members:admin` with 403, so the two are
merged together. Showing the form only with `members:admin` until then
was rejected: the owner would still have no lever, and the page would
have to change again.

**Reason:** §2.3 gives the owner this lever whatever their trust; a
field only an admin sees left the owner none. A cross-owner boss files
consent requests (§6.2) whose start by the owner the contract has not
settled, so it is not offered until it has.

**Rejected alternative:** the whole membership form for the owner: it
would offer trust, role and areas the hub refuses them. Finding the
pending request by its title: fragile and invisible to the reader when
it breaks.

## Whom an agent reports to is chosen where it joins, a boss of another owner offered and marked

**Id:** e69c571c-3365-433a-b26d-245efff28a7d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request (req-a5xxyvq74ft7, seq 86060): on Agents, letting agents join, Reports to should be settable there, not only under Management afterwards; card tsk-nbadjbr9zpg7 and the lead's go with its two points (seq 86087), 2026-11-07; docs/api.md §3.1, §2.3 ("to any other member, which is a cross-owner edge and takes effect only with the boss's side's consent"), §6.2 ("Own consent")
**Revisit when:** the contract gives the member view the pending edge (`reports_to_pending`), or a join that names `reports_to` for an agent already a member

The join panel offers **Reports to** in every case:

- **A first join, by an admin:** every member who is not a guest. One's own agents and oneself are plain; anyone else is marked "waits for consent", and the hub files that consent at the exchange (§3.1).
- **A member's own agent:** oneself (the default) and one's own managers in the project, the only bosses §3.1 lets a member's join name.
- **An agent already here:** a field of its own with the current boss. A change is the owner's own `PATCH …/members/{id}` (§2.3), sent before the join, so where it applies at once (200) the join page and the first resume show the new boss. Where it waits for the boss's side's consent (202, §6.2), the join page keeps the boss it was issued with, since the hub copies the boss into the join when it is created; the resume after the consent shows the new one.

If that `PATCH` is refused, no join is sent. If it is taken and the join then fails, the panel says both: the join's refusal, and the new boss, or the consent it waits for. A boss already asked for is not asked again in the same panel. The owner's **Reports to** on Members and Agents offers a boss of another owner too, marked the same way, its 202 said as the consent it waits for.

**Reason:** the maintainer wants to place agents, other owners' among them, at the moment they join, and §2.3 lets the owner start a cross-owner edge whatever their trust. The earlier rule (c848b045) held them back only until the contract settled that, which it now has.

**Rejected alternative:** a default boss on the agent profile, carried into every project: a boss is always a member of one project, and it would need a contract change (the lead, seq 86087). Sending `reports_to` in an instance's join: the hub refuses a membership field there (`differs_from_membership`). Undoing the `PATCH` when the join fails: the change was asked for on its own terms, and an undo could itself fail.

## An agent's credentials, briefing and pause live in its row on Members; an owner opens their own agents as Details

**Id:** 1c00024d-a3a6-49bc-ba2e-704359713aeb
**Type:** decision
**Status:** superseded
**Superseded by:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Evidence:** confirmed
**Source:** the maintainer's wish to fold the Agents page into Members → Manage (tsk-7v2snhk002ak, chat 2026-10-27); the coordinator's cut into two PRs and its tie to the decided Team page's Members tab (context/members.md f0ca2279: humans and agents in one list, actions per row), 2026-10-27
**Revisit when:** the Team page's Members tab lands, or a member page of its own takes the actions (tsk-rtb5vjrvbh34)

Opening an agent's row (members:admin) shows the membership form, the
briefing (edited there), whether it gets your preferences if it is
yours, its credentials with Revoke (read when the row first opens, kept
across redraws), the pause once, and Remove. Without members:admin a
human's own agents open as **Details**: credentials and the preferences
switch, nothing that changes the membership. With the join panel and the
placements moved too, the Agents page and its cards are gone; see the
entry on joining in Members.

**Reason:** one row per member, with what may be done to it, is the
Members tab the Team page decided; nothing a person could see or do on
the Agents page may get lost, an owner without admin rights included.

**Rejected alternative:** the owner's own agents read only, with no row
to open: their credentials and the preferences switch were theirs on the
Agents page. Loading every agent's credentials with the list: a call per
agent on every visit, for rows mostly never opened.

## The lead is reached by a Lead button left of Chat, not by Chat itself or a strip

**Id:** 0ff66bde-7c26-412a-a856-069b52764910
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish (tsk-g2qe0fyqqmmq, chat 2026-10-27): the chat entry a button like the others, the lead strip gone; and his decision on the form (req-4rpd7vqb6xe3, 2026-10-27): two buttons, Chat to the chat list, a Lead button beside it, one lead opened at once, several listed with a group chat with all leads
**Revisit when:** the Team page (req-2mwv85k5e1s6) gives the leads a place of their own, or a project names more than one lead by policy

Chat in the header is a button like the bell and always opens every chat.
The Lead button left of it (first right of Chat; the maintainer swapped them on 2026-11-01, tsk-td5c6z21xg5s) reaches whom `M.leadChat.targets` names (the
policy's lead now, one's own proxy; without a lead the admin agents and
one's own proxy; until 2026-10-30 on an older hub only one's own admin
and proxy agents, e1699490), across every project outside one: one is opened at once,
several are a menu with, per project with more than one, a group chat
with all of them (an open one of exactly those people reused). Without
anyone to reach there is no Lead button. The strip above the tabs and
the section on All projects are gone.

**Reason:** the unread count on Chat counts every chat; a click on it
that went to the lead would not lead to what the count says, and the chat
list would have no way in from the header outside a project.

**Rejected alternative:** Chat as the lead's button, a menu of the leads
and All chats when there are several (asked as B): a second click to
every chat, and one button meaning two things. Keeping the strip: it took
the room above the tabs on every page of a project.

## On a phone the Lead stands on the Chats page, not in the header

**Id:** 6abce868-55e7-4f64-b3c4-3984bda22965
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's card tsk-m9ew7v609fq0, 2026-11-03 (on a phone the header's buttons wrapped under the logo; hide the Lead there, its function reachable another way, the menu or settings named as an example); the dashboard's implementation the same day
**Revisit when:** the header gets room for the Lead at phone width again, or the Chat button stops leading to `/chats`
**See:** views.md#the-lead-is-reached-by-a-lead-button-left-of-chat-not-by-chat-itself-or-a-strip — 0ff66bde-7c26-412a-a856-069b52764910 — as of 2026-11-03

At phone width (≤ 600 px) the header hides the Lead button, so Chat, +, the gear, the bell and
the profile fit in the logo's row from 360 px (narrower, they still go under it). The same control (one lead opened at once, several a menu with
their group chat) stands on the Chats page under its heading, at the left edge, with its word, at
phone width only; its menu opens from that edge.

**Reason:** Chat leads to `/chats`, so the lead is one tap further than before, and the control
keeps everything it does. Hiding it was the maintainer's call; where it went instead is the
author's.

**Rejected alternative:** an entry in the gear or profile menu, as the card suggested. A menu
item is one action, and several leads with a group chat would need a second menu inside the
first.

## On a phone the project's links are one row that scrolls; the state stands beside it

**Id:** df210b31-e55a-47c9-93da-2d139e9ded89
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's card tsk-m9ew7v609fq0, 2026-11-03 (on a phone the project's links wrapped into two rows; one row that scrolls sideways, the state always in sight); review on #1271 (with Review, Released and an absence the first version squeezed the row to 0 px and scrolled the page sideways)
**Revisit when:** a project gets so many state parts that they leave no usable row beside them on a phone, or the header gives the links a row of their own
**See:** views.md#a-projects-own-links-stand-beside-the-repository-which-reads-repository-whatever-the-forge-the-form-sends-only-what-changed — 10a77061-c980-4990-b44b-cb7f518cd4eb — as of 2026-11-03

At phone width (≤ 600 px) the repository, Pull Requests, the project's own links and Why are one
row of their own (`.project-links`) that scrolls sideways, with the fade cue of the tab rows.
The state, the released mark and the absence stand beside it, outside the row, so a scroll
never moves them away. The row keeps about one link's width (9rem); the state parts that do not
fit beside it wrap under it.

**Reason:** two rows of links took the room above the tabs, and the state is the part the
maintainer asked to keep in sight. A row allowed to shrink to nothing hid the links and pushed
the page sideways once an absence stood beside the state.

**Rejected alternative:** the links wrapping as before (two rows or more on a phone), which the
card asked to end. The state parts never wrapping: with an absence they need more than a phone's
width.

## Runners in the gear menu, not in the projects' row

**Id:** a6c7bf3a-9742-4535-ae21-110bd809dc47
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request (tsk-cb6myw32def0), 2026-10-27

The link to `/runners` sits in the header's gear menu, beside the
instance administration, and no longer in the row that lists the
projects. The menu marks it as the page shown.

**Reason:** a runner belongs to the person who runs it, not to a project;
the projects' row lists projects, and the gear menu holds what is not a
project's.

**Alternatives:** unknown.

## The dashboard keys a project by its full name, everywhere

**Id:** 242091d4-23c3-446e-ae63-6bb67057640e
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (projects in their owner's namespace; a client keeps `full_name` or the pair, never the slug alone), the card tsk-dbbcw9ccabfk and the hub's PR #483, 2026-10-27
**Revisit when:** organisations become namespace owners, or the hub serves the one-segment routes again

A project's address in the dashboard is `/<owner>/<slug>/…` (§16.11), and every
key the dashboard keeps for a project is its `full_name`: the API base,
the switcher, the inbox's grouping and filter, the counts, the global
chat, the read-along page, the lead button, the runners' configuration.
A full name that is no project of one's own is asked of the hub once,
which answers an alias with the current name. The address before
namespaces (`/p/<slug>`, rewritten through `legacy_slug`) is gone since
2026-10-29 with the other old addresses (§16.11): no redirect. The fixture
hub maps a full name to its fixture directory and refuses an old path
with 410, as the hub does.

**Reason:** a slug is unique only within its owner's namespace; a key or
a link built from the slug alone could reach another owner's project of
the same slug, and an old link could lead somewhere new.

**Rejected alternative:** changing only the API paths and keeping the
slug as the dashboard's key: two projects named `shop` would share
counts, drafts and links. Rewriting the old `/p/<slug>` by the current
slug: §6.25 forbade it, since another project may carry that slug by now.

## Agents are added in Members: Add at the head of the agents' table, open joins as seats under it

**Id:** 621d28a8-36f5-4ebd-a90a-f7d729d7af34
**Type:** decision
**Status:** superseded
**Superseded by:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Evidence:** confirmed
**Source:** the maintainer's wish to fold the Agents page into Members (tsk-7v2snhk002ak, chat 2026-10-27); the coordinator's cut, whose second PR moves joining and the placements and removes the Agents page, 2026-10-27; the decided Team page's Members tab (context/members.md f0ca2279)
**Revisit when:** the Team page's Members tab lands, or joins get a lifecycle beyond open, used, expired, burned and revoked
**See:** views.md#joining-an-agent-happens-in-agents-a-panel-under-the-title-open-joins-as-seats-in-the-grid — d80f865d-5b59-4ad1-8cc2-c1079d13869c — as of 2026-10-27

The agents' heading on Members has **+ Add an agent** (owner and admin),
which opens the join panel under it: closed by default, open at once in a
project without agents or at `/<owner>/<slug>/team/join`. The panel is read beside the
list, never before it, so the rows and a member asked for by the URL do
not wait for the joins. Open joins stand as seats under the agents'
table, the placements after it, the earlier joins at the end. A count
line says how many agents, online and open joins there are.
There is no Agents tab; the old `…/agents` and `…/join` addresses are
gone since 2026-10-29 with the other old addresses (§16.11).

**Reason:** an agent is a member; adding one where the members are, and
seeing its seat next to them, keeps one place for the team, as the Team
page decided.

**Rejected alternative:** keeping Agents as a tab beside Members: two
views of the same people, with the actions split between them. Seats
inside the agents' table as rows: a seat is no member yet, and the table
is read by the hub's member list.

## A member adds their own agents from Agents while the policy's member_agents is not off

**Id:** 5cb62418-20f0-465f-b01e-be12e665a07e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.1 "Bringing your own agent" and §6.1 (`member_agents`, `member_agents_max`); the card tsk-zd2ch05rk7s1, 2026-10-27; the review of PR #472, 2026-10-27
**Revisit when:** §3.1 changes what counts

A human member without `members:admin` sees **+ Add my agent** at the
head of Agents (the agents' table on Members before 54a49af9) when the project's `member_agents`
is not `off`. The panel offers only what §3.1 lets a member
set (trust member or guest; every role of §2.3 but ops and proxy;
no reports to, no areas) and lists only the member's own joins. A line
says how many agents of theirs the project allows. The count is the
member's distinct agents that are active members or have an open join,
as the hub counts. At the limit the button stays while the member has an
agent in the project: the panel then makes another instance or a
replacement of one of them and refuses a new agent before sending.
Project settings turns the feature on or off and sets the limit.

Until 2026-10-30 the button also needed the field to be present at all,
for a hub that predated it and refused a member's join with 403; the
hub always sends it, so that check went with the alpha rule (e1699490).

**Reason:** an instance
or replacement counts nothing in §3.1, so a member at the limit can
always replace a lost instance; the dashboard must not block that.

**Rejected alternative:** the button off at the limit: it blocked the replacement §3.1
keeps open. Counting every open join: an instance's join counted as a
new agent.

## The team rulebook is on the agent's card and in its row, for its owner only

**Id:** 49804786-8704-4db6-a473-e348a12a77c5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.18 (only the human who owns the agent profile sets `team`); the card tsk-xzbk67raztm0, 2026-10-27; the review of PR #473, 2026-10-27
**Revisit when:** §6.18 lets an admin set a team's rulebook, or the Team page gives teams a place of their own

On the project's Agents, the card of one's own agent holds its **Team
rulebook**, and so does its Manage row on Members (since 54a49af9; the row
alone before); nobody else sees it, an admin included. The limit
shows the active instances beside it and says that lowering it stops
none. The lead is chosen among the active instances; one revoked since
stays chosen, marked revoked. Only the fields that changed are sent. A
join refused with `instance_quota` links to the card, focused at the
limit (`/<owner>/<slug>/agents/<id>/rulebook`), and does not edit the limit
in the join panel.

**Reason:** the contract gives the rulebook to the profile's owner
alone, so a form an admin could see would only fail. Sending only what
changed keeps a save of one field from overwriting another set
elsewhere, a revoked lead included.

**Rejected alternative:** editing the limit in the join panel where the
refusal appears: the panel's user may not be the owner, and the rulebook
would have two places. Alternatives to the row's placement: unknown.

## A project's name is changed in Project settings; a card outside its project reads with it

**Id:** 9cf859f1-d5e0-420c-9ea3-d633cea94e33
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (rename by a human owner, transfer by the namespace owner as a consent request, aliases, card references outside a project); the card tsk-cns4d1d7ht4j from the maintainer's chat; the hub's PR #487, 2026-10-28; the card tsk-9e5cd0b0hmzx, 2026-11-04 (the step-up entered in place)
**Revisit when:** another call of the section becomes sensitive (§2.8.4), or the transfer's targets change in §6.25/§6.26

Project settings has a **Project name** section for a human owner of
the project: the full name, the earlier ones, a rename of the slug that
follows the new address, and, for the namespace owner (for an
organisation's project, each of its owners), a transfer to another
human owner of the project, into an organisation the human owns or
administers, or, out of an organisation, into the human's own
namespace (KTW e47c8d0d says which of them moves at once), with the
request withdrawable from the same place. A step-up the hub asks for
is entered in place: the transfer goes through `M.stepUp.run`, which
asks for the code in the form and sends the transfer again once it is
given; Cancel ends it without a failure. A
card's or a request's id reads `<owner>/<slug>/<id>` wherever it is shown
outside its project (`M.ids.where` says so by the view's scope), written
by one helper (`M.ids.ref`). The hub never parses the prefix (§6.25:
the id stays the identifier); the dashboard reads `<owner>/<slug>/<id>`
in written text as a link into that project (KTW 50234f88 in
`rendering.md`, `js/ids.js`).

**Reason:** the name belongs with the project's other settings and to
the people the contract gives it to; one helper keeps the prefix in one
place, as the card asked, so a later change of its form is one edit.

**Rejected alternative:** a transfer that names anyone by handle: the
contract takes only a current owner of the project or an organisation
(§6.25, §6.26), so the list offers those owners and, of the
organisations, only the ones the human owns or administers, other than
the project's own and none that is suspended.

## One's agents have a page of their own in the gear menu; adding one to a project is that project's join panel

**Id:** 1031c11b-7642-4ed9-87ce-de504b2044fc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on the card tsk-hn82893h9sdh, 2026-10-29 (agents belong to their owner and span projects; "add" means the join flow; the account keeps no agents section, one place); the maintainer's card tsk-05meme59sq1x, 2026-10-31 ("Join an agent" at the top, a list like Members with Manage, the instances inside); docs/api.md §6.3, §3.1, §6.17, §16.11 (`agents` a reserved first segment)
**Revisit when:** the hub can make a join for a profile without a project view (a join across projects), or the Team page's Members tab takes the profiles over

`/agents`, in the gear menu beside Runners, lists every agent profile of
the human (`GET /agents`): its picture, its memberships with trust, role
and the instances against the team's limit, its name, git identity and
handle, and its deletion; a new profile at the end. **Add to a project**
leads to that project's Agents with the join panel open and the
profile chosen (`/<owner>/<slug>/agents/join?agent=<id>`, since
54a49af9; Members before it): the one join
component, where the project's rules (who may bring agents, the
member's limit, the team's) are known. The profile asked for
(`?agent=<id>`) is kept across a failed first read of the joins, so
**Try again** opens the panel with it chosen, as the first open would
have. The handle is offered on every profile (§6.24); until 2026-10-30
only where the hub's machine form named it. `/agents/<id>` marks one profile.
The account keeps the human's own picture and points to this page; an
agent's picture stays settable on its card on a project's Agents and in
its Manage row on Members as well.

Since 2026-10-31 the page has **Join an agent**: a project chosen
(`?project=<owner>/<slug>`, which also opens the panel at once) and that
project's join panel, the same component mounted with the project's
context; since 2026-11-01 it stays closed until asked for (1ac94340).
The profiles below are a list like Members (picture, name and
global handle, projects, active instances, presence). **Manage** opens
under a row what the card held, and per membership the instances with
their credentials and revocation, the part Members' Manage uses, read in
that project's context when the row opens. A row stays open across a
redraw; a profile just made, or the one in `/agents/<id>`, opens its row.
A project's Agents is the same list limited to that project: one's own
agents there as rows (trust and role here, presence, active instances
here), Manage opening the card with what belongs to the membership here,
the agent in `agents/<id>` (or its rulebook) open from the start.

**Reason:** an agent is the owner's across projects, so its settings
need one place that is not a project; and the join panel already knows
each project's rules, which a second join flow on this page would have
to repeat.

**Rejected alternative:** a join form of its own on `/agents`: it would
repeat the project's join rules (§3.1's member limits, the team's
instance limit) apart from the panel and drift from it. Keeping the
agents in no project on the account: two places for the same profile.

## Members is two tables without levels; only the organisation tree follows trust

**Id:** f4ec0c89-33e8-4f62-b192-371a23b91581
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on tsk-xxewyredc97a, 2026-11-01: the indent was agreed for the organisation chart only, and the two tables of humans and agents were good
**See:** views.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-11-01

Members shows a table of humans and one of agents, each in the hub's order, with no indent and no level by trust; the columns are again each table's own. In the Organisation tree, a member with no parent by `reports_to` or area stands at its trust's level, owners at the top, then admins, members and guests, each a level deeper; a level nobody holds leaves no step. Such a member is not put under one owner's node: with several owners that would draw a line to one of them that the project does not have.

**Rejected alternatives:** one list with levels (#949): a misunderstanding of the wish, which was about the chart only. Two tables each indented by trust: the same indent nobody asked for on the list.

## Members and the organisation tree follow trust: owners at the top, then admins, members and guests

**Id:** 9333bd7a-dbda-4c4f-88d8-fa08124ef06d
**Type:** decision
**Status:** superseded
**Superseded by:** f4ec0c89-33e8-4f62-b192-371a23b91581
**Evidence:** inferred
**Source:** the maintainer's wishes on the card tsk-05meme59sq1x, 2026-10-31, given in three steps: only owners at the top and everyone else indented; the order owners, members, guests; then the levels follow trust, owner, admin, member, guest, each a level deeper, and a level nobody holds leaves no empty step; for both the Organisation tree and the Members list, which becomes one list
**Revisit when:** a project needs a level the trust does not express, or the Team page shows reports_to in Members too
**See:** views.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-10-31
**See:** views.md#a-projects-tabs-members-a-neutral-list-with-chat-agents-ones-own-agents-the-organisation-on-the-team-page — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-10-31

Members is one list instead of a table of humans and one of agents. Its
rows go by trust: owners, then admins, then members, then guests, each a
level deeper (the name cell indented), within a level in the hub's
order. A level nobody holds is left out, so the next moves up. The
columns are both tables' columns; a human's agent-only columns (owner,
paused, Keep the Why) read "—". Only my agents still shows one's own
agents. In the Organisation tree, a member with no parent by
`reports_to` or area stands at its trust's level the same way. Such a
member is not put under one owner's node: with several owners that would
draw a line to one of them that the project does not have. A trust the
dashboard does not know counts as member.

**Reason:** the levels are the maintainer's (confirmed: "the real
hierarchy" has the owners as its root, then by trust). Read from that,
not stated by him: a human member and the owner on one level, as the
tree drew a member without `reports_to`, look like peers.

**Rejected alternative:** keeping two tables in Members and indenting
only within each, which would still put a member human beside the owner.
Hanging members without a parent under the first owner, which claims a
reporting line that is not there.

## A project's tabs: Members a neutral list with Chat, Agents one's own agents, the organisation on the Team page

**Id:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on the card tsk-3ap6mj5y1k2a, 2026-10-29 (Members neutral with a Chat per entry, the admin's Manage kept as it is; an Agents tab before Runners and Why, the component of /agents filtered to the project; the organigram into the Overview, the Organisation tab gone without a redirect); the maintainer's request relayed by the coordinator on the card tsk-ttywzxsaj1ht, 2026-10-31 (Agents right after Members, Jour fixe between Why and Settings); docs/api.md §16.11 (the project views, `agents` among them, `org` no longer)
**Revisit when:** the Team page's Members tab lands, or the hub lets an agent's owner pause or remove it without `members:admin`

2026-11-09: the project tab, the page title and the member page's breadcrumb are named Team (req-77az2zs017fe); its path stays /members. The Team page's own Members tab and its heading keep that name, so the Revisit-when lines on that tab are not triggered by this.
2026-11-10: the path follows the name: the view and its member pages are at /<owner>/<slug>/team (the maintainer's decision, so that the name and the path match; card tsk-yy9d5np8pjmr). `members` stays a reserved word, the maintainer's wish, so no slug or later view takes it; /members is a word that is no view, with no redirect. The Members tab keeps its name.

**Members** lists everyone in the project the same way for every
viewer: trust and role, presence, owner, joined, paused, a link to the
member and a **Chat** per entry (one's own agent: its direct chat;
anyone else: a new group chat with them chosen, `chat/new?with=<id>`).
With `members:admin` each row keeps
**Manage**, with the membership form, briefing, picture, rulebook,
credentials, pause and removal. **Agents** (`/<owner>/<slug>/agents`, for
humans) shows one's own agents in the project, each as its card on
`/agents` (`profileCard`, one component), with what belongs to the
membership under it: the preferences switch, the team's rulebook, the
credentials, and with `members:admin` the pause and the removal (§6.2
gives an owner without it neither). The join panel, the open joins, the
placements and the earlier joins are there; `…/agents/join[?agent=<id>]`
opens the panel, `…/agents/<id>/rulebook` the limit, and a new project
lands on Agents. The parts the Members row and the Agents card share
(rulebook, credentials, picture, pause, removal) are one code,
`M.memberParts`. The organisation tree was a section of the Overview,
redrawn there when a member event arrived; since 2026-10-30 it is the
Team page's Organisation tab (58c58a28-d6b1-453f-99dc-7f21179b3ee2). The join panel and the
placements belong to Agents because both are about one's own agents:
a join makes one, and where they run is managed by their owner or the
runner's; a list everybody reads is no place for either. In the row
Agents stands right after Members, and Jour fixe between Why and
Settings: Inbox, Overview, Board, Members, Agents, Chat, Messages,
Ticker, Why, Memory, Jour fixe, Settings (an agent sees no Agents tab).

**Reason:** Members is where one sees who is in the project and talks
to them; managing one's own agents is a different job, the same one as
on `/agents`, so it gets that page's component in the project. A tab
for one computed tree was a page to go to for what the Overview can show.

**Rejected alternative:** the earlier cut (1c00024d, 621d28a8): one's
own agents opened as **Details** in their rows on Members, the join
panel at the head of the agents' table, the placements under it, and an
Organisation tab. It mixed managing one's agents into the team's list,
and the list looked different to each viewer. A redirect from `…/org`
to the Overview: the alpha rule, no compatibility routes.

## An agent's bridges sit with its other member parts; a connection across owners is said as waiting for two consents

**Id:** 522e04b1-28b8-452a-a246-7f45e433e3c8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 "The bridge" after the contract #927 and the hub's bridges (the connection on the served agent's membership, `201` at once or `202` with the first of two consents, `bridges` and `bridging_for` in the member view, End for either owner, either agent and `members:admin`, cross-owner bridges among a group chat's observers); the coordinator's card tsk-x0krjnw8p78t (connect with a purpose on the agent's member view, owner only; the waiting line; both lists with End; "carries for @handle" in the group chat's header), 2026-11-01; placing it in `M.memberParts` and the waiting line's wording are the implementer's, 2026-11-01
**See:** views.md#a-projects-tabs-members-a-neutral-list-with-chat-agents-ones-own-agents-the-organisation-on-the-team-page — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-11-01
**Revisit when:** the member view carries open bridge requests, the hub's `202` names both consents, or a purpose may be changed from the dashboard (`PATCH …/bridges/{brg}`)

An agent's **Bridges** are one more part of `M.memberParts`, so the
Manage row on Members and the agent's card on Agents show the same:
the agents that lend it their hands (`bridges`) and those it lends its
hands to (`bridging_for`), each with its purpose, marked when another
owner's, and **End** for either agent's owner or `members:admin`; the
End goes to the served agent's membership, whichever side it is shown
on. Only the agent's owner gets **Connect with a bridge** (an agent of
the project that is neither the agent itself, a proxy nor already its
bridge, and the purpose). A `201` re-reads the members and says the
bridge lends its hands. A `202` is said by the part itself as waiting
for the consent of the bridge's owner and of the project: the hub files
both, but its answer names only the first, so the generic consent line
of the other member parts would name one human where two decide. Open
requests are not listed, since the member view carries only connections;
the consents are in the inbox as usual. In a group chat an agent among
the observers is such a bridge, said as "carries for" the participants
its `bridging_for` names; a human observer is said as before.

**Reason:** a bridge is a setting of the agent's membership like its
rulebook or its credentials, managed by the same people in the same
places, so it belongs in the parts both views share. Saying the two
consents keeps the owner from waiting on one human when the project has
to agree as well.

**Rejected alternative:** a page or tab of its own for bridges, apart
from where the agent's other membership settings are. The shared consent
line of `act()`, which names the request's one addressee. Re-reading the
inbox after a `202` to list the open request: the inbox already shows
it, and the part would read a second resource on every redraw. In the
e2e only the section is checked, since `e2e-alpha` has one agent and a
second join would cost a CLI pairing for this alone; connecting, ending,
the waiting line and a refusal are in smoke.

## A member's own settings in a project are a tab of their own, My settings, at `my-settings`

**Id:** df54f284-212c-4eab-995d-778dce37f7fb
**Type:** decision
**Status:** superseded
**Superseded by:** f37bbdb4-2ad3-432e-babf-dd58f6e3ff79
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 in docs/api.md §6.2 (personal settings are the defaults, a member overrides them per project); the card tsk-32g2cjbm52ft; the coordinator's ruling on the path, 2026-10-29; the coordinator's ruling in the review of #649 (no fallback), 2026-10-30
**Revisit when:** a member's own settings for a project grow beyond a few, or the project's Settings tab is offered to every member as their own

**My settings** (`/<owner>/<slug>/my-settings`, a project view in
§16.11) shows every human member their own settings for the project:
each either **Use my default**, the value from the account sent as
`null`, or a value for this project, with what applies now. The first
is how long one of one's agent instances here may stop listening
before one hears of it. The account's notification settings hold the
default and its mode (inbox, bell or off). A failed read of a
member's settings is shown as an error; there is no quiet note for a
hub without the route (e1699490 removes that mechanism everywhere).

**Reason:** the project's Settings are kept by its owner and admins;
one member's own choices are not the project's and must not sit under
them. A tab of its own makes them reachable from inside the project,
where one thinks of that project's agents.

**Rejected alternative:** `settings/me`, under the project's Settings:
no new word for the slugs to avoid, but its tab would be marked as the
one shown and mix the owner's page with a member's own. One list of
per-project overrides on the account: far from the project it is about. A quiet "this hub has
no settings of your own per project yet" (`M.dom.notOnHub`) where the
route is missing: the hub and the dashboard ship together, and such a
note would hide a broken deploy behind words that sound normal.

## A request the hub files itself is Maity's; the not-listening digest leads to one's agents

**Id:** 967ed0c0-9e46-42cc-bd45-4fbc4ceae370
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §5.3 (the owner's digest: `asked_by` null, `filed_by` "hub", no project), §7, §18.1–§18.3 (`agents_not_listening`, target `agents`, linking to `/agents`; read only once its matter is closed — the coordinator's rulings of 2026-10-29); the coordinator's decision of 2026-10-29 on the target `agents` and "Maity" as the requester; the card tsk-32g2cjbm52ft; the review of #649
**Revisit when:** the hub files requests of its own that are about one project and should lead into it, or the dashboard gets a personal inbox

A request with `asked_by: null` and `filed_by: "hub"` names its asker
**Maity** (in the list) and **Maity, on its own** (in its facts), and
says nothing about an agent waiting, since none does. The hourly digest
of agent instances that are not listening — personal, about no project
and no organisation — adds a link to one's agents (`/agents`); its
summary lists the instances. The bell's `agents_not_listening` item
(target `agents`) leads to `/agents` too, and is not marked read when
opened: like `registration_pending` and `mail_disabled` it asks for an
action (resume or end the instances) and is read once the matter is
closed, when no instance is away any more (§18.1–§18.3); `keepsUnread`
names its target `agents`. A report's request (entry f50ed8ee-5948-43c8-817a-d1b008bf1f5a) has the
digest's shape, filed by the hub, personal, without project or
organisation, but is no digest and gets no such link.

**Reason:** "—" as an asker reads as a missing name, not as the hub;
and "the agent waits for the answer" would be false. The instances
named in the digest can be resumed or ended only from one's agents.

**Rejected alternatives:**
- The item's `url` as the link: the dashboard builds every bell link
  from the target (the entries above), so one item built otherwise would
  be the exception.
- Reading the bell's item on open, like a request's item: the bell would
  go quiet while the instances are still away, and the next hour's
  record would bring it back.

## A person or an organisation at /<handle> is one read of GET /people/{handle}, shown as the hub answers it

**Id:** 63efb194-f0ff-4137-bb1f-fb4265356e3b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report that `/wolfgang` showed nothing (seq 15767) and the card tsk-dnxgm9k0f317, 2026-10-30; the read the dashboard lacked, proposed with the card and settled by the coordinator as docs/api.md §6.27 (#738), with its later changes (`page_served`, `projects` with `shared` and `projects_total`, a placeholder for a `null` picture, `not_found` for whoever shows the reader nothing), 2026-10-30
**Revisit when:** §6.27 changes its answer, the hub serves a person's page images, or follows (`friends`) exist

`/<handle>` (one segment, not one of the dashboard's own words) is the
person or organisation view (`js/person.js`). It reads `GET
/people/{handle}` once and shows only what that answer holds for this
reader: the name, `@handle`, the picture, for a person the bio and the
links (each sent by the hub already built from the name, #764, so the
page builds none; Discord's name as text), the projects, for an
organisation its members. **View public
page** is there only while `page_served`, and opens `/<handle>?as=public`
in a new tab. A picture the answer gives no address for is a neutral
placeholder, not §6.10's generated avatar. A shared project leads to its
Overview, any other to its public page. An alias answers with the
current handle and the address follows it; `not_found` says that there
is nobody to see, as for an unknown name.

**Reason:** what a reader may see of another person (the bio only while
the page is public, the links by `links_visible`, a picture by §6.10)
is the hub's to decide per reader; one read that already answers that
keeps the view from guessing it from member lists, which would show a
bio or a link to the wrong reader or miss the public projects. The
generated avatar needs the account id, which the answer leaves out on
purpose.

**Rejected alternative:** building the view from the member views of
the shared projects: no bio, no public page, nothing for a person one
shares no project with, and no organisation for a non-member. A
generated avatar from the handle: it would differ from the one every
other view draws for the same person, and change with a rename. Hiding
the picture's place: the layout would jump from one person to the next.

## The fixture hub serves an organisation's page by its switch, which the hub does not yet

**Id:** efe947bc-444d-4b65-b694-610be9137806
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the delta review of #748 (the fixture's `/people` route), 2026-10-30; `hub/src/maity_hub/routes/people.py` (`page_served` read from the store)
**See:** https://github.com/oliver-zehentleitner/maity — 4423561d-6f8e-4ad5-8729-0b896fb37e3c — as of 2026-10-31
**Revisit when:** the hub renders an organisation's page kind

The fixture hub's `GET /people/{handle}` answers `page_served` for an
organisation from its `public_page` switch, and lists its projects with
a served page as `shared: false`. The real hub reads the store, where no
organisation page exists yet, so it answers `false` for every
organisation. The person view's **View public page** branch for an
organisation is drawn only in the fixture.

**Reason:** with the hub's answer the branch would never be drawn
in smoke, and would break unseen when the hub starts serving the page.

**Rejected alternative:** `page_served: false` for every organisation in
the fixture, as the hub answers today: it matches the hub, but leaves
those branches untested.

## A member's page is for reading; its Actions menu only leads to Members or Agents

**Id:** dda6f237-ffeb-4b68-ba0a-844c77f269dd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's handover #6484 (the member page header with an Actions menu: Assign a card, Edit briefing, Change role or reports to, Pause, Revoke the session, Remove), 2026-10-27; the coordinator's ruling on the card tsk-rtb5vjrvbh34, 2026-10-30, with the maintainer's decision of #643 (each action in one place) as its reason
**See:** views.md — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-10-29
**Revisit when:** the maintainer moves the admin's actions out of the Manage row, or a member page of its own takes over what the Agents card does

`/<owner>/<slug>/team/<id>` is a member's page: breadcrumb, header,
and the tabs Activity, Cards, Briefing, Sessions & credentials, all read
only. Its **Actions ▾** holds only links: **Manage on Members**
(`?manage=<id>`, the list with that row open) for an admin, **Manage on
Agents** (the agent's card) for its owner; without either there is no
menu. Every member link leads to this page, not to a marked row.

**Reason:** since #643 each action lives in one place: an admin's on the
Manage row of Members, an owner's on Agents. A third place for the same
forms would let them drift apart and leave the same change reachable
from three screens with three sets of words.

**Rejected alternative:** the Actions menu as the handover drew it, with
the actions themselves (role, pause, briefing, revocation, removal):
it would undo the one-place rule of #643. Taking the Manage row away
from Members in its favour: that reverses the maintainer's own choice
("finde ich super") for the row.

## A human's picture is set on the account, an agent's in its row on Members; the account keeps only agents no project shows

**Id:** 59aaf51f-c63d-4cb6-966b-85eb8f2c682d
**Type:** decision
**Status:** superseded
**Superseded by:** 1031c11b-7642-4ed9-87ce-de504b2044fc
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-th1yq0jtk3yf (an agent's picture belongs to its management, personal settings keep only one's own), 2026-10-28; the coordinator's ruling on the fallback for agents in no project one is in, 2026-10-28
**Revisit when:** the dashboard gets a page of one's agents outside any project, or §6.10 gives `members:admin` a say over pictures
**See:** rendering.md#a-picture-is-uploaded-on-the-account-checked-as-the-hub-checks-it-with-no-preview-of-the-chosen-file — 3ec853f0-4141-4e81-acdf-c0fee94c920b — as of 2026-10-28

The account's Profile tab (`/account`; `/account/picture` leads there) sets the human's own picture. An
agent's picture is set where the agent is managed: in its row on
Members, under **Details** or **Manage**, for its owner only, as §6.10
allows. The picture is read from one's agent profiles (`GET /agents`)
when the first such row opens, since the member list carries no
`avatar_source`. The account still lists, under **Agents in other
projects**, the owner's agents that are in no project the owner can
open, and only those. `/account/picture/<agent id>` for an agent that
Members reaches leads to `/<owner>/<slug>/team/<agent id>/picture`,
the row open. The checks before sending and the missing preview stay as
the entry this one replaces describes them.

**Reason:** a picture is part of managing the agent, next to its
credentials and rulebook, not of the human's personal settings. An
agent working only in projects its owner is not a member of has no row
the owner can open. Without the account's list, its picture could not be
set from the dashboard, and a Keep the Why notice about it would lead
nowhere.

**Rejected alternative:** dropping the account's list entirely and
sending such a notice to `/all`. `/all` says nothing about the agent,
and its picture would become unreachable. Keeping every agent's picture
on the account: this is what the maintainer asked to move.

## The project banner is shown at 2:1, the shape of a forge's social preview

**Id:** c2e9d1e8-f7b5-46fd-8c93-9ea04ff52042
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-4jhn5xeypjjb (the banner had the wrong height; GitHub asks for at least 640×320, ideally 1280×640) and his follow-up (never crop: the Keep the Why banner's text was cut); the coordinator's cap at 960 pixels, 2026-10-28
**Revisit when:** the 960-pixel cap is too small or too large for the inbox below, or a forge's preview has another shape

The banner on the project's inbox, and its preview in Project settings,
are as wide as their column, at most 960 pixels (the banner centred),
and half as high (`aspect-ratio: 2 / 1`).
The image is never cropped (`object-fit: contain`): one of another shape
is shown whole, with margins in the surface colour. There is no fixed
height; the cap keeps the inbox below in sight on a wide screen, where
the full width made the banner the whole first screenful.

**Reason:** a project's banner is mostly the repository's social preview,
which GitHub defines at 2:1. The same shape shows it whole at every
width. A preview often carries text, such as the Keep the Why banner, and
cropping makes that unreadable, so margins are preferred.

**Rejected alternative:** the fixed 180-pixel strip it had: at desktop
width it cut a 2:1 preview to about 6.5:1, showing only a stripe of it.
Filling the 2:1 box by cropping (`object-fit: cover`): a banner of
another shape lost the text at its edges.

## The view being left is inert until the next one is drawn

**Id:** 1d888f69-9233-40b4-b9f3-cd679825ef82
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the runner flake of web-e2e (tsk-q1xrpaahtah0, runs 40718638353 and 40721945466) and the reviewer's reproduction with ordinary clicks and Back on PR #551, 2026-10-28
**Revisit when:** views are mounted before their data is read, or a view is kept across navigations

A navigation renders the next view off screen and mounts it when its
data is read; until then the view being left stays shown. From the start
of the render it is `inert`: no click, key or focus reaches it.

**Reason:** an action in the old view (a Revoke) was answered into that
view, which then disappeared, while the new view showed what it had read
before the action, as if nothing had happened. The page alone was wrong,
the hub had revoked. Inert keeps the old view as a visual placeholder
without letting it start anything.

**Rejected alternative:** waiting in the end-to-end test only: it hid a
real case (a click during a slow navigation). Clearing the old view at
once: a blank page on every navigation, and a jump. Making every view's
initial read consistent with actions in other instances: one rule per
view, for a race the inert placeholder removes for all of them.

## An agent profile is deleted where it is managed, confirmed by its handle, its projects named first

**Id:** 7929359f-6af1-415e-b6e6-a55dd40ca27c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-g1yz7rhaptqk (profiles deletable, with a confirmation by typing the handle and what happens), 2026-10-28; docs/api.md §6.3 (`profile_in_use`, `?cascade=true`, the tombstone)
**Revisit when:** the hub offers an undo or a grace period for a deleted profile, or deletion moves to a page of one's agents outside any project

The owner deletes a profile in its row on Members, beside its picture,
and on the account for an agent in no project of the owner's. The page
first names every project the profile is a member of and what deleting
it ends there (credentials, claims, placements), then enables the button
only once the handle is typed. A profile that is still a member
somewhere goes out with `?cascade=true`; one in no project, without.

**Reason:** a deletion cannot be undone, and in a project it ends a
working membership. Typing the handle makes it a deliberate act for this
very profile, and the named projects say what it costs before, not after.
In a Members row the profile is always a member, so the cascade is the
only deletion that can succeed there.

**Rejected alternative:** a plain `DELETE` first and a second
confirmation on `profile_in_use`: two dialogs for what the page can say
at once. A browser `confirm()`: it names neither the projects nor the
handle, and is clicked away too easily.

## Every role of §2.3 is offered from one list, by its label, with what the role does under the picker

**Id:** 43c080d3-e47c-45a3-9add-3da834cdf588
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's note that roles were missing (manager, the red team, …) and the card tsk-g62vwd7bqztk, 2026-10-30; the coordinator's brief for its web part (labels and short help texts from §2.3, the picker everywhere), 2026-10-30; docs/api.md §2.3 (the roles' table, the security teams), §3.1 (a member's own agent: not ops, not proxy)
**Revisit when:** §2.3 adds or drops a built-in role, or a project's own roles (§2.3) get a place in the pickers
**See:** views.md — b71cebbf-56d9-4f65-aef9-cbb4ab5131a1 — as of 2026-10-30

`js/trust.js` holds the one list of built-in roles, in the order of the
§2.3 table, each with a label ("Red team") and a few words of what the
member does, taken from that table. Every role picker (a member's form,
an invitation, a join, a member's own agent) fills its options from it
by label, with the role's words as the option's tooltip and, under the
picker, as a hint line the select is described by, following the chosen
role. What a picker offers stays its own rule: proxy only with trust
admin and only from an owner, a member's own agent every role but `ops`
and `proxy`. A security team counts as the role whose scopes it has
(red team as tester, purple team as reviewer) where the dashboard asks
who reviews, tests or prepares a release; the blue team counts as
coder, which no dashboard question asks for. The fixture hub keeps the
same roles in one list of its own. The list is the hub's too (`scopes.ROLES`
and `COUNTS_AS` since #711, the same §2.3): a role added or dropped on one
side is changed on the other in the same contract change. A member's
line elsewhere ("admin · red-team", `M.trust.words`) keeps the hub's
token: it is what the CLI and the hub's answers show, and the label is
for the moment a role is chosen.

**Reason:** the roles had been copied into each picker, and `manager`
and the three security teams were missing from all of them; one list is
one place to add the next. A token like `purple-team` does not say what
the member will do, and a choice of role is made by someone deciding
what an agent is for.

**Rejected alternative:** the tokens as the options' text, as before:
correct for the hub, unclear for the person choosing. The help as the
options' tooltip only: a tooltip is not read on a phone or by every
screen reader. A table of every role beside each form: longer than the
form it explains.

## Trust and role are shown and chosen as the hub keeps them; what only an owner may grant is not offered to others

**Id:** b71cebbf-56d9-4f65-aef9-cbb4ab5131a1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 (trust × role, owner_only, the guest's limits) and the card for the dashboard's part (tsk-tx9qcehevfnk), which replaces the interim mapping at the API boundary, 2026-10-28
**Revisit when:** a project's own roles (§2.3) get a place in the dashboard, or the hub lets a non-owner grant trust admin

The dashboard reads and sends a membership's `trust` and `role` as the
hub has them. Every view asks one helper (`js/trust.js`) who governs
(trust owner or admin, never a proxy, which relays and decides nothing
itself), who is an owner and who is a guest, and names a
member as "trust · role". The member form, the invitation and the join
line each choose trust and role on their own. Trust owner or admin and
the role proxy are offered only to a caller with trust owner, and proxy
only together with trust admin; a proxy whose trust changes becomes a
coder in the same change. An owner's membership is removed only by an
owner, so no one else is offered it. A guest is never offered as an assignee
or as whom someone reports to, and a human guest is offered no new
group chat. The overview groups the team by trust.

**Reason:** trust and role are two separate questions (§2.3): how far
the project trusts a member, and what the member does. A single name
could not say "admin reviewer" or "guest coder", and the interim mapping
lost exactly those. The choices the hub refuses for a non-owner
(`owner_only`) or for a guest would only lead to a refusal, so they are
not offered.

**Rejected alternative:** keeping the mapping between single-role names
and trust and role at the API boundary: it translated every answer and
body and could not show a guest's role or a reviewer with trust admin.
Offering every choice and saying the hub's refusal afterwards: a form
that offers what it will refuse.

## A sensitive call asks for the password or a code where it stands, then is made again

**Id:** bddf61cb-f6a0-4290-891f-2f3b3006946d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.8.1 (the proof: the password in the last 10 minutes, `reauthentication_required`) and §2.8.4 (the step-up, `step_up_required`, "the dashboard asks for a code and repeats the call"); the coordinator's card for Your data (§2.9), 2026-10-28
**Revisit when:** the hub tells in advance which calls will need a proof, or the dashboard gets a dialog layer of its own

A sensitive call goes through `M.stepUp.run` (`js/step-up.js`). It
makes the call. When the hub refuses with `reauthentication_required`
or `step_up_required`, it asks for the password or a code in a slot of
the section that made the call, proves it (`POST /auth/reauthenticate`,
`POST /auth/second-factor/verify`, a recovery code too) and makes the
call again, at most three times. A wrong answer is said there and asked
again. Cancel ends quietly.

**Reason:** the hub, not the page, knows whether the password was given
in the last 10 minutes and whether the human is enrolled, so asking
only after its refusal never asks for nothing. The question stands next
to the button that caused it. Your data is the first user; the other
sensitive calls (§2.8.4) can take the same helper; the transfer of a
project (Project settings, §6.25, §6.26) does since 2026-10-29, where it
used to say to sign in again.

**Rejected alternative:** asking for the password before every
sensitive call: needless right after a sign-in, and wrong for a
passwordless account. A modal dialog: the dashboard has none, and a
slot in place keeps the focus and the context where the human was.


## Every route that asks for the factor is called through M.stepUp.run, held by a list the hub test and the check share

**Id:** 4dc6b1f0-bd9d-4110-a961-41e830af134e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-6dk86ej9s0fq (the owner, 2026-11-09: pairing a runner on /runners showed only "This needs your second factor first."; the lead's scope: the fix, an audit of every route that calls `require_step_up`, a guard, the fixture refusing); hub/src/maity_hub (the routes), docs/api.md §2.8.4; the guard's form is the implementer's, as the card left it
**See:** views.md#a-sensitive-call-asks-for-the-password-or-a-code-where-it-stands-then-is-made-again — bddf61cb-f6a0-4290-891f-2f3b3006946d — as of 2026-11-09
**Revisit when:** the hub publishes which routes ask (in its OpenAPI, say), or the dashboard's calls go through typed per-route functions

`tools/step-up-routes.json` lists the hub's routes that ask for the factor (method and path under the API prefix; `body` where the hub asks only for one field, `when` where it asks only in some cases). Three readers keep it true:
- `hub/tests/test_step_up_routes.py` reads the hub's source: every route whose handler reaches `second_factor.require_step_up`, directly, in a lambda it hands on, or through the hub's own functions it calls. Each call is resolved through the module's imports, so the gate imported under another name, or called by a module's name or its full dotted path, counts the same. A function handed around under another variable or taken by `getattr` is not followed. The two sets must be equal.
- `tools/check.py` fails on a call `M.api.<verb>(path, …)` in `js/` whose path it reads as one of those routes and that does not go through `M.stepUp.run`. It is a reading of the text, not of the program. It recognises exactly the forms below; any other form is not checked and can pass.
  - **Path:** the parts of a `+` chain that are a string literal; `ctx.base`; a name, read from the last `const name =` or `let name =` before the call anywhere in the file (not by blocks); a call of such a name bound to an arrow, whose body is read; or `a ? b : c` and `a || b` of those; three deep. Any other part stands for any run of characters, slashes too (`M.api.projectPath` gives several segments). A path with no part read is left alone.
  - **Names in a body and of a named arrow (form 2 below):** a name is bound only by a declaration `const name =` or `let name =`. The check walks out from the call through the `{…}` blocks around it to the nearest block that declares the name, and takes there the last such declaration before the call, else the first. Its value is the text after `=` up to its `;` or the end of its block. Nothing else binds a name for the check, in a path either: not a later declarator after a comma (`const a = 1, name = …`), a parameter, a destructuring, `var`, a function declaration or a reassignment.
  - **Body:** for a route that asks only for one field, the call's body is read with the value of every name in it, three deep. The field counts where its key stands as a word in that text, so a key behind a variable counts.
  - **Asking first**, in exactly these four forms; in 2 to 4 the arrow's body is the call itself (`=> M.api.…(…)`, in parentheses or not), not a block:
    1. Inside the function expression that is the whole of `M.stepUp.run`'s first argument; not one called or bound right there.
    2. In an arrow `const name = (…) =>` or `let name = x =>`, not `async`, where an `M.stepUp.run(name, …)` in the file resolves, by the blocks around it, to this declaration. This shows the binding is handed to the question once, not that every call of it goes through it.
    3. In an arrow that is a property `key: (…) =>`, not `async`, where every `.key` read in the file (`x.key`, `x[i].key`) is `M.stepUp.run`'s first argument, no `{ … key … } =` destructures it, no `["key"]` reads it, and the file makes no call through brackets (`…](`).
    4. As an argument of a local function (`function f(…) {` or `const f = (…) => {`) whose parameter in that place is handed to `M.stepUp.run` as its first argument in its body. `f` is found as follows, and only so: the check walks out from the call through the `{…}` blocks around it to the nearest block that declares `f` by a function declaration (a `function`, also `async` or `export`, where a statement starts: at the top or after `;`, `{` or `}`), a `const` or a `let`. There it takes the last function declaration of that block, wherever the call stands; if the block has none, the last `const` or `let` before the call, else the first. Where that declaration is not such a helper, the call does not ask. Any other binding form is not resolved and can pass, for example a named function expression's own name, a parameter, `var`, an import or an assignment.
  - A call made to work out `M.stepUp.run`'s arguments, or in another of its arguments, is sent before anything is asked, and does not count.
  - `tools/test_step_up_check.py` holds those readings, some through the whole check on a file of its own (tsk-4zrnkb3gh6mq, after xyfr's post-merge re-check of #1547 found that a name given to `M.stepUp.run` anywhere in the file had counted, and 4hch's review of #1566 the reads and names the first fix still missed).
- The same check keeps `js/api.js`'s `STEP_UP_ROUTES` equal to the list. With `window.MAITY_FIXTURE_STEP_UP` set (to `Date.now()`, so that a code given earlier in the run does not count), the fixture hub refuses them with `step_up_required` until a code is verified.

A reject of a held address change is never asked by the hub, but it is sent through the question like the approve: the hub's reading includes it, and asking only after a refusal costs nothing there.

Known limits, each a way a new guarded call could go unseen (tsk-4zrnkb3gh6mq records them rather than closing them):
- The hub test finds routes declared as `@router.<method>("<path>")` on a module-level function with a local `APIRouter`. A route added with `add_api_route` (as `routes/project_images.py` adds its image routes), a class method, or a router built inside a function (as `app.py` builds the one for `/languages` and `/health`) adds nothing to its set; none of those files reaches `require_step_up` today.
- `tools/check.py` follows only the forms listed above. Any other way to write a binding, a path or a hand-over is not checked and can pass: a parameter of the same name, a reassignment, an alias that keeps the arrow, a direct call beside the wrapped one, a function passed under another name, a value stored and read in another file.
- The fixture asks for the factor on any `email.address` in `PATCH /me/notification-settings`; the hub asks only when a verified or disabled address changes (`_change_address` in `hub/src/maity_hub/notifications/preferences.py`). Wider than the hub, it never lets through what the hub refuses.

**Reason:** the runner pairing, the mail settings, the password, the address change and its approval, and the answer that moves a project were each written without the helper, and nothing failed until a person met the refusal. A list read from the hub and a check over every call catches the next one when it is written. A test drives only the flows someone thought of.

**Rejected alternatives:**
- The fixture refusing, with smoke and e2e to catch a missing question: it finds only what a test drives, and none of the eight calls had such a test.
- A hub contract test against routes named in docs/api.md: §2.8.4 names the calls in prose, not as a list a test reads, and the step-up is decided in the hub's code, which the source reading follows.
- Every `M.api` write through `M.stepUp.run`: each form would need a slot for a question the hub never asks.


## The second step of a sign-in is a page of its own for both ways; the mail's link is posted from the page

**Id:** 4fdf4cc1-e916-44d7-9064-5b07989b0d06
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §2.8.2 (the second-factor session reaches only `GET /auth/session`, the verify, the mail's resend and the logout), §2.8.7 and §2.8.8 after the contract #925 and the hub's first part #943 (`via: email`, `mail`, the link `/sign-in/second-factor/email#<token>` bound to the signing-in browser, the step-up by a mailed code); the coordinator's card tsk-ekpb0pvgw4bh and the lead's answers of 2026-11-01 (the step for both ways in this change, TOTP enrolment and the security page on tsk-94jtz06aps4b; `address_hint` to come with the hub's second part, "your address" until then; Admin → Sign-in in a second web change); the page's shape is the implementer's, 2026-11-01
**See:** views.md#a-sensitive-call-asks-for-the-password-or-a-code-where-it-stands-then-is-made-again — bddf61cb-f6a0-4290-891f-2f3b3006946d — as of 2026-11-01
**Revisit when:** the hub sends `address_hint` (drop "your address"), TOTP enrolment gets its page (tsk-94jtz06aps4b), or the e2e gets a hub with a secret key and a mail catcher

A session that owes the second factor (`GET /auth/session` answers
`second_factor: "required"`) gets one page and nothing else
(`js/second-factor.js`): with `via: totp` a field for the app's code or
a recovery code (six digits, spaces ignored, are a code); with `via:
email` the mail's state in words (sent, to `address_hint` or "your
address"; the next mail's wait when rate-limited; unavailable), a field
for the mailed code and **Send again**, which reads the session again
for what the hub says of the new mail. **Sign out and start again**
ends it. The mail's link lands on
`/sign-in/second-factor/email#<token>`: the page reads the token from
the fragment (the query `?token=` in fixture mode), drops it from the
address and posts it at once. A browser without that session, or one
already signed in, gets the contract's sentence on where to open the
link instead. The step-up asks `GET /auth/second-factor` when the hub
wants the factor: a human whose `via` there is `email` is mailed
a code as the question opens, with Send again, and types it
(`email_code`); everyone else keeps the app's code.
The fixture's verify takes `email_token` at a step-up too, as it cannot
tell the step from the step-up; harmless while the step-up sends only
`email_code` (the hub never takes the token there, §2.8.8). A session
state in the fixture was rejected for that one case.
The e2e's second hub covers the TOTP step and the step-up (#1003), and a
hub of its own the mail: the admin's switch, the link, the code and the
step-up by mail.

**Reason:** the dashboard had no second step at all, for TOTP neither;
both ways run in the same second-factor session, so one page serves
both. The mail's token completes only the sign-in of the browser that
asked for it, so posting it without a tap gives nobody anything; a tap
would only add a step to the one place where the human has just
clicked a link for exactly this.

**Rejected alternative:** a step for the mail alone, leaving an
enrolled human at a session that reaches nothing. A confirm button
before posting the link's token, as the device code has: the device
code approves another browser's sign-in, the token only this one's.
Trying the app's code first at a step-up and falling back to the mail
after a failure: one wrong code counts toward the limit (§2.8.6) and
says nothing a read of `GET /auth/second-factor` does not. The e2e
runs neither way: its hub has no `MAITY_SECRET_KEY`, which TOTP needs
and which the forge step checks is missing, and no mail settings; the
step for both ways, the link, the page elsewhere and the step-up by
mail are in smoke.

## Organisations live under the account: `/account/orgs`, not `/orgs`

**Id:** 73999dde-dbb6-4982-a448-e1441e7a5b6b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (one namespace `<owner>/<slug>`, the dashboard's route words reserved as handles) and §6.26; `DASHBOARD_WORDS` in hub/src/maity_hub/namespace.py; the coordinator's approval of the route on the organisations card, 2026-10-29
**Revisit when:** `orgs` is added to the hub's reserved dashboard words, or organisations get pages of their own beside the account (a public organisation page, §16.9)

The dashboard addresses a project as `/<owner>/<slug>`, and any first
word the dashboard does not use itself is read as an owner's handle.
The organisations view therefore sits under a word the dashboard
already owns: `/account/orgs` lists them, `/account/orgs/<handle>`
is one of them. It is reached from the profile menu.

**Reason:** `orgs` is not among the hub's reserved handles
(`DASHBOARD_WORDS`), so a human or an organisation may already be
called `orgs`; `/orgs/<x>` would then be that owner's project
`orgs/<x>` as much as an organisation page. Organisations are a
human's own business (§6.26, humans only, members only), which is what
the account holds.

**Rejected alternative:** `/orgs` and `/orgs/<handle>`: shorter,
but ambiguous with a project of an owner named `orgs` unless the hub
first reserves the word, a change to the hub and to handles that may
already exist. Putting organisations into the Settings menu: that menu
holds the hub's and the runners' settings, not the human's memberships.

## A suspended organisation's handle and public page are locked in the form, not only refused

**Id:** 156c278f-9df0-45c6-b53f-1cece42b2ed9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("Suspended": a rename and `public_page: on` are `forbidden`, `moderation_hold`) and §16.8; the review of the organisations page (#584), 2026-10-29
**Revisit when:** a suspension also locks other settings, or the hub sends the allowed changes with the view

While the organisation's view carries `moderation`, the settings form
disables the handle field and turning the public page on, and says why;
turning the page off stays possible. The refusal `moderation_hold` is
still said in words, for a suspension that comes between loading the
page and saving it.

**Reason:** the human should not type a change the hub will refuse;
the view already says the organisation is suspended.

**Rejected alternative:** leaving the fields open and showing the hub's
`forbidden` afterwards: the human types first and is turned away.

## The organisation's handle in the address is read as a typed one

**Id:** c3e2532b-f64a-4ade-b834-853ad4b1160f
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** docs/api.md §6.24 (handles are lowercase; `{org}` resolves a handle or an alias); the review of the organisations page (#584), 2026-10-29
**Revisit when:** the dashboard moves to real paths (the routing card after #601), where the route parser may normalise once for every handle

`M.orgs.handleOf` decodes the handle from `/account/orgs/<handle>`,
trims it, drops a leading `@` and writes it in lowercase, for the call
and for the page title, so `/account/orgs/%40OZ-Team` opens @oz-team.

**Reason:** a link copied with an `@` or typed with capitals names the
same organisation for a human.

**Rejected alternative:** handing the route as it is to
`GET /orgs/{org}`: an `@` or a capital letter would answer
`not_found` for an organisation the human is in.

## The fixture hub's reserved handles are a copy of the hub's list

**Id:** 6dccb66c-0cd3-4cbb-8b65-59e8e5b814e0
**Type:** workaround
**Status:** active
**Evidence:** inferred
**Source:** `ORG_RESERVED` in web/js/api.js; `DASHBOARD_WORDS` in hub/src/maity_hub/namespace.py (docs/api.md §6.25, "Dashboard routes and handles"; §16.11 with #601); the review of the organisations page (#584), 2026-10-29
**Revisit when:** the hub publishes its reserved words (in its machine form or a route), or #601 changes the list

The fixture hub refuses an organisation handle that is a word of the
dashboard's addresses from its own copy of the hub's list. It is a copy,
not a read: when the hub changes its words, `web/js/api.js` has to
change with it. On a real hub the hub alone refuses.

## New project offers an organisation as owner only where the human may create in it

**Id:** e0cf14f3-56b8-40c4-9e6e-4c5fb739b037
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("The organisation's projects", "Suspended"); web/js/new-project.js; the review of #609, 2026-10-29
**Revisit when:** the hub's form names the owners a human may choose, or organisations get a page of their own for new projects

The **Owner** field (until 2026-10-30 only where the hub's machine form
named `owner` on `POST /projects`, e1699490) offers the human and the organisations
in which they may create a project: as owner or admin, or as a member
while `members_create_projects` is on, and none that is suspended. When
`GET /orgs` fails, only the personal choice is left; the form still
works.

**Reason:** an organisation the human may not create in would only
lead to `org_role` or `moderation_hold`.

**Rejected alternative:** offering every organisation and saying the
hub's 403 afterwards: the rule moves into an error message.

## A transfer into an organisation moves at once only for its owner

**Id:** e47c8d0d-373f-4b2d-be05-15ad3d4306ef
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("Transfer into and out of an organisation"), §6.25; web/js/project-names.js; the review of #609, 2026-10-29
**Revisit when:** the transfer's answer says itself whether it moved or asked, or the project view carries the caller's role in its organisation

Project settings offer the transfer to the project's namespace owner,
and for an organisation's project to each of its owners. The
confirmation says before the call which case comes: into an
organisation the human owns, or to themselves out of an organisation,
the project moves in the call and the page follows its new name; into
one they administer, its owners are asked and the request can be
withdrawn. Whether the human is an owner of the project's organisation
comes from `org_owner` on their own member view (§6.2), since the
project view carries no organisation role. Suspended organisations are
not offered.

**Reason:** an owner of the receiving organisation speaks for it, an
admin only for themselves (§6.26); the page should say which before the
human confirms.

**Rejected alternative:** always saying the transfer waits for consent:
wrong for an owner, whose call moves the project at once.

## A personal request may carry no project

**Id:** 5857ebb6-4ecb-47cc-8bb4-278c2c406abb
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §7 ("Personal requests"), §6.26 (an organisation's invitation; a transfer request carries `project` and `org`); web/js/inbox.js; the review of #609, 2026-10-29
**Revisit when:** another kind of personal request names something other than a project or an organisation

The cross-project inbox takes a personal request whose `project` is
`null`: its slug stays empty, its label reads Personal, followed by the
organisation where the request carries `org`, and nothing links into a
project. A request with `project` and `org` (a transfer into an
organisation) names the project and the organisation it would move into.
One with neither (a report's request, §16.8) is labelled Personal alone,
its hidden name "Personal: " rather than "Personal, : ".

**Reason:** an invitation into an organisation belongs to no project,
and the inbox read `project.full_name` on every request, so one such
request broke the whole list.

**Rejected alternative:** filling in an empty project: it shows a
project that is not there, and the links behind it lead nowhere.

## A report's request in the inbox only opens the report

**Id:** f50ed8ee-5948-43c8-817a-d1b008bf1f5a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.8 ("Who is told"), §7 (`report`, `resolve_the_report`), §1.3; the card tsk-xz3yt6yz1b2b and the coordinator's approval of variant A, 2026-11-04 (the request cannot be answered, resolving stays in Admin → Reports; Open report must work from the all-projects inbox); hub/context/reports.md 2011e591
**Revisit when:** the hub lets the request itself resolve its report, or a report's request reaches someone other than the instance admin

A new abuse report reaches the instance admin as a personal request
without project or organisation, filed by the hub, carrying `report`
(`id`, `reason`, `type`). In the inbox such a request shows no text
field, no replies, no Withdraw and no digest's link to one's agents,
only **Later** and **Open report**, a link to `/admin/reports/<id>`,
where the admin reads the snapshot and resolves it. Resolving or expiry
withdraws the request on the hub's side; the inbox drops it on its next
read. The fixture hub does the same: it lists such requests for the open
reports, refuses answering or withdrawing them with `resolve_the_report`,
and withdraws one when its report is resolved. The bell's `report`
target (`report_open`) is gone from `M.notify`.

**Reason:** the hub refuses every answer and withdrawal of a report's
request (409 `resolve_the_report`), so a field or button there could only
fail; the decision needs the snapshot and the actions of Admin → Reports.

**Rejected alternatives:**
- Resolving in the inbox (the card's variant B): a second place for the
  same action, without the snapshot beside it.
- Keeping the bell's `report_open` item beside the request: every report
  shown, and mailed, twice.
- The digest's link to one's agents, which its shape alone would give
  (hub-filed, personal, no project, no organisation): it says nothing
  about a report.

## The meat-proxy hint quotes the hub's note as /me carries it, and no text of its own

**Id:** 8eb486bb-357a-477c-aaf5-2a4d51024cc4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2 `GET /me` ("the dashboard shows it under the switch from here and keeps no copy of its own") and §5.2 "Meat proxy"; the change that replaced the page's own sentence with `meat_proxy_note`; #990 removed the case for a hub without the note
**Revisit when:** the note gets text per human or a translation, or `/me` stops carrying it

Under the switch **I am a meat proxy** the account quotes
`meat_proxy_note` from `/me` as text, never through HTML.

**Reason:** the human should read exactly what the agents that deal
with them read. Any wording of the page's own drifts from the hub's as
soon as the note changes, as it did once already.

**Rejected alternative:** keeping the old sentence as a fallback where
the field is missing: on a hub whose note has changed, it would show
words the agents no longer read, the drift this avoids. Keeping a case
for a hub without the field: no such hub runs under the alpha rule
(§1.6), so #990 removed it.
Copying the text into the page: the same drift with every change of
the wording.

## Released is a mark beside the state, never a state; Project settings say it is never cleared

**Id:** 27ca6bd9-6e83-4a85-8620-f5e9f428362f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the released mark in the dashboard (PR #659, 2026-10-29) and the Grok review of it; contract in `docs/api.md` §6.1 and §6.9
**See:** https://github.com/oliver-zehentleitner/maity — de8abccf-94dc-4947-9926-463aa13edd8f — as of 2026-10-29
**Revisit when:** §6.1 lets the mark be cleared, or the hub's released rules text changes

The hub sets `released_at` once and keeps it through every state. The
dashboard therefore shows "Released" beside the state badge, in the
header and in the overview's State row, not as a sixth state. The
tooltip carries the released rules in the hub's words, so a reader sees
what the mark binds. Project settings say the mark holds "for good"
and offer no control for it. A project without `released_at`, or a hub
that does not send it, shows no mark.

**Reason:** no call clears the mark, so a control in the settings would
promise something the hub refuses. The overview is where a reader looks
up the state, so the mark belongs there as well as in the header.

**Rejected alternatives:**
- A `released` entry in the state select: it would be lost on the next
  move back to build, which the maintainer's decision rules out.
- The mark in the header alone: the overview is where the state is read.

## A member's Activity reads the hub's latest 5000 events and says so

**Id:** 4c3f8949-c8df-4c99-bb0c-08dc47205eed
**Type:** workaround
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §8.3 (an event's `seq` counts across the whole hub; a feed is read forward with `after=` only, without a filter by actor) and §8.8 (the listing holds messages only, with no filter by sender); the coordinator's review of #687, 2026-10-30 (the window `after = head − 200` counted the hub's events, not the project's); the rule from the incident of 2026-10-26: no request whose cost grows with history; the card tsk-0m6qx612y5px and lotse's agreement, 2026-11-04 (project message seq 69405): the Messages view moves to §8.8, the Activity keeps the window
**Revisit when:** §8.3 takes `actor=` (`GET /events?actor=`)

The hub cannot be asked for one member's events, nor for a project's
latest events counted in that project. The member page's Activity
therefore pages through the project's feed from the hub's latest 5000
`seq` forward (its own scan in js/member-page.js), keeps the member's
own events that are not redacted, and shows the newest 50; each opening
of the page reads up to 26 pages of 200, a cost bounded by the window,
not by history. Where the window cut something, it says it counts the
hub's latest 5000 events, all projects counted, so a quiet member in a
busy hub reads as cut, not as idle. A cursor that does not move stops
the read with an error. The Messages view no longer shares this scan:
it pages through the message listing (§8.8, 8e483bb1) since 2026-11-04.

**Reason:** what the client can afford to read is bounded by the hub's
numbering, not the project's; a sentence that names the project's events
would promise what the window cannot see. The Activity stays on the
window when the Messages view leaves it: it lists every kind of a
member's events (cards claimed, requests answered, members joined, and
messages), while §8.8 lists messages only and cannot be asked for one
sender, so it would show a fraction of the Activity and still need the
scan for the rest. Settled with lotse on 2026-11-04 (seq 69405).

**Rejected alternative:** reading the whole feed from the first event:
its cost grows with the hub's history, which the 2026-10-26 rule rules
out. A window of 200 for the Activity: in a busy hub it held few or none
of the project's events and said nothing about it. The Activity from
§8.8 alone, filtered to the member in the page: it would drop every
event that is not a message and page through every sender's messages to
find one member's.

## The swarm statistics are the Overview's Swarm tab, read on their own; no project tab, no public page, no switch

**Id:** 8a528eb5-8dd6-4fec-996e-79c5b57abb51
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 that the swarm is a statistic (root context/projects.md, bfe4c4a6, card tsk-w89mspg3gwx1); docs/api.md §6.11, §6.22, §16.11 after the contract #697; the card tsk-b8ndat73wttr; how the section reads and redraws is the implementer's, 2026-10-30
**Revisit when:** a public project's page draws the reduced numbers in the dashboard (§16.9), or the Overview gets a refresh of its own for the swarm

The project's Overview carries the **Swarm** section: who is at work
now, what each holds, and the window's counters with the 7/30/90-day
switch, as the old Swarm tab had them (`js/swarm.js`, `M.swarm.section`).
Since 2026-10-30 it is the Overview's own Swarm tab
(`/<owner>/<slug>/overview/swarm`, 58c58a28-d6b1-453f-99dc-7f21179b3ee2), no longer a row under
the counts. The section is built once per visit of that tab and reads
`GET …/swarm` itself, once and on a window change; a card, request or
probe event draws nothing there. There is no Swarm tab in the
project's row of tabs, no `/<owner>/<slug>/swarm` view, no public swarm page or `?as=public`, and
no `swarm_public` switch in Project settings; the fixture hub no longer
serves `/swarm/{owner}/{slug}`.

**Reason:** the maintainer made the swarm a statistic of the project,
not a place of its own. Read with the counts, every card event would
read the swarm again and reset the window the reader chose; the live
part has no event of its own to follow either, so it is as fresh as the
last read, as the tab was.

**Rejected alternative:** keeping `/<owner>/<slug>/swarm` as a redirect
to the Overview: the alpha rule, nothing old is kept for compatibility,
and the address was never shared outside the dashboard. Drawing the
section anew with the Overview's counts: a swarm read per card event,
and the window lost. Keeping the public page until public projects get
their pages: the contract removed its route and its switch.

## A chat with an agent sends to the whole team unless one instance is chosen beside its heading

**Id:** 4236b804-8b55-4a94-a166-5fb4c010f127
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request relayed on the card tsk-f0ctq47mw0f6 (a selector of the agent's live instances beside the heading, the whole team by default, the choice kept per chat for the session, shown on the sent message, hidden with one instance), 2026-10-30; docs/api.md §9.1 (`to_instance` on a direct message wakes exactly one instance) and the coordinator's ruling that the message carries `to_instance` back (id or `null`), 2026-10-30; the hub side is the card tsk-p1df7ggm17bc
**Revisit when:** group chats get a choice of instance, or the hub tells which instance the wake rule chose for a message to the team

An agent with more than one instance that is not revoked gets **Send
to** beside **Chat with <agent>**: **The whole team** first and chosen,
then each live instance as `<handle>#<id> · <presence>`. A chosen
instance goes as `to_instance` on `POST …/conversations/{agent}/messages`;
the team is no field at all. The choice is kept per conversation in this
tab, like a draft, and ends with signing out; one whose instance is gone
falls back to the team. One's own message sent to an instance says "to
<handle>#<id>" from the message's own `to_instance`, never from the
selector. An offline instance is offered too, marked so.

**Reason:** the team by default keeps the agent's own wake rule in
charge; picking one instance is for the times the human knows which
session holds the work. The label is read from the answer, which carries
`to_instance` as written (a replaced instance's message reaches its
successor, but the message still names the instance the human chose), so
it says what was sent, whatever the selector shows by then.

**Rejected alternative:** a mention `@handle#id` in the text: a direct
chat never resolves mentions (§8.6), so it would wake nobody. Offering
only online instances: an offline one still gets the message at its next
resume, and its being offline is said in the option. Keeping the choice
in browser storage: a stale instance id would outlive the session it
named.

## The project's repository and Keep the Why dashboard are links beside its state, from what the project view already holds

**Id:** bdb4632c-1047-4a88-9249-f09f8c50d1e8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request on the card tsk-n161gf6h8feb (two buttons top right beside the state, the repository with its forge's icon, the Keep the Why dashboard, both in a new tab), 2026-10-29; the coordinator's note that the project view already carries `repository` and `keep_the_why_export.members[]` with the root at `path: ""` and its `dashboard_url`, so no contract change, 2026-10-30
**Revisit when:** a project needs a dashboard address other than its export's, or the hub derives more forges

In a project the header shows, after the state, the absence and the
released mark, a link to the repository (`repository.url`, labelled by
`repository.forge`: GitHub and GitLab with their marks, Gitea by its
name with a branch mark, any other as "Repository" with a branch mark) and **Why**, the dashboard of the Keep
the Why family's root member. Either is left out where the project has
none or its address is not plain `https`; both open in a tab of their
own and are named for a screen reader with where they go.

**Reason:** these are the two places one leaves the dashboard for most
often; the data is in the project view already, so the links cost no
request and no new setting.

**Rejected alternative:** a new project field for the dashboard's
address, as the card first proposed: the export already names it, and a
second address could drift from the one the family publishes. Only the
Overview's Project panel, where both links already are: one click
further, on one view only.

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

## A project has one Settings view: Project for its admins, Mine at settings/mine for every human member

**Id:** f37bbdb4-2ad3-432e-babf-dd58f6e3ff79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish for only one Settings in a project (relayed on the card tsk-wzqeneerfacp, 2026-10-30); docs/api.md §16.11 after the contract #741 (the `settings` view with two tabs, the project's at `settings` for `project:admin`, the caller's own at `settings/mine` for every member, a caller without `project:admin` at `settings` gets `settings/mine`; `my-settings` is no project view any more); the alpha rule, no redirect from the old path
**Revisit when:** a member without `project:admin` needs to read a project setting the overview does not show, or one's own settings for a project grow into a page of their own
**See:** views.md#a-members-own-settings-in-a-project-are-a-tab-of-their-own-my-settings-at-my-settings — df54f284-212c-4eab-995d-778dce37f7fb — as of 2026-10-30

The project's tabs end in one **Settings**, offered to its admins and to
every human member. Inside it two tabs, as links: **Project**
(`/<owner>/<slug>/settings`) for a member with `project:admin`, and
**Mine** (`/<owner>/<slug>/settings/mine`) for a human, one's own settings
for the project with one's default from the account. A member without
`project:admin` who opens `settings` is sent on to `settings/mine` and
sees no tab bar, having one tab. `/<owner>/<slug>/my-settings` is gone,
without a redirect.

**Reason:** two tabs called Settings and My settings side by side read as
one thing twice; one place with a part for the project and a part for
oneself is where a member looks for either.

**Rejected alternative:** keeping **My settings** as a tab of its own
(df54f284): the maintainer asked for one Settings. Showing a member the
Project tab read only, as before: the contract shows it to admins only,
and what a member may read of it (language, memory) is on the overview
or in the project's files. A redirect from `my-settings`: the alpha
rule, no route kept for an old address.

## The meat-proxy switch has its two parts under it, each sent alone; the hub decides the switch and the note

**Id:** e9c14296-f8da-4f83-871b-056a0d3ab6ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2 `GET /me`, §5.2 "Meat proxy" and the `PATCH /me` row after the contract #702 (two stored parts, the switch derived, the order in which a body applies); the coordinator's card tsk-j9mgn2z3e7pf (two sub-points, both ticked on switching on, each cleared alone, the note under them from `GET /me`), 2026-10-30; the page's shape is the implementer's, 2026-10-30; the review of #720 (the answer's shape), 2026-10-30
**See:** views.md#the-meat-proxy-hint-quotes-the-hubs-note-as-me-carries-it-and-no-text-of-its-own — 8eb486bb-357a-477c-aaf5-2a4d51024cc4 — as of 2026-10-30
**Revisit when:** the hub adds a third part, or the note gets text per human or a translation

Under **I am a meat proxy** the account shows the two parts, *Lead me
step by step rather than expecting me to explain.* and *When you need a
human's hands, come to me first.*, as checkboxes of their own. The
switch sends `meat_proxy` alone (on ticks both, off clears both); a part
sends only that part, so ticking one while the mode is off turns it on
with that part, and clearing the last turns it off. After every answer
the switch, both parts and the note are drawn from what the hub sent
back, never from what was clicked. The answer of `PATCH /me` is `/me`
itself (§5.1), so the page reads `answer.member`, as it reads `GET /me`;
the fixture hub answers in that same shape. The note stands under the parts;
while the mode is off it is the text switching on would send.

**Reason:** the hub stores the parts and derives the switch, so drawing
from its answer keeps the page and the agents' text the same, whatever
order the person clicks in. Sending the one field that changed lets the
hub's order rule decide, as §5.2 spells it out.

**Rejected alternative:** sending the whole state (switch and both parts)
on every change: `meat_proxy: false` with a part set to `true` is
`invalid`, and the page would have to repeat the hub's rule. Disabling
the parts while the switch is off: the contract lets one part alone turn
the mode on, which a disabled box would hide. Labels of the page's own
wording for the parts: they are the person's own sentences in §5.2, the
same words the note puts together. Reading the fields at the top of the
answer with the clicked value as fallback (the earlier code): against the
hub it never read the answer at all, and the fixture's flat answer hid it.

## A chat's meat-proxy switch sits between Attach and Send; it draws from its own answer, and Follow my profile gives the choice back

**Id:** 393898d2-62e1-4e5d-a1b7-8eacb859ea01
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §9.3 "Meat proxy per chat" after the contract #922 and the hub's #956 (`PUT …/conversations/{id}/meat-proxy` with `true`, `false` or `null`; the participants' entries carry `meat_proxy` and, for oneself, `meat_proxy_chat`; no event); the coordinator's card tsk-n872zkxmwbec (a switch beside Attach and Send in direct and group chats for human participants, a way back to `null`, the designer's two icons, on in the accent on `--out-bg`), 2026-10-31; the coordinator's word to use the designer's final3 icons, 2026-11-01; the button's shape and the Follow my profile link are the implementer's, 2026-11-01
**See:** views.md#the-meat-proxy-switch-has-its-two-parts-under-it-each-sent-alone-the-hub-decides-the-switch-and-the-note — e9c14296-f8da-4f83-871b-056a0d3ab6ed — as of 2026-11-01
**Revisit when:** the designer sends the icons with the Maity logo, the hub emits an event for the per-chat value, or a chat offers parts of its own

In a direct or group chat a human participant finds the meat-proxy
switch in the composer's row, between **Attach files** and **Send**
(`js/meat-proxy.js`, one part for both composers through
`M.chatParts.actionRow`). It is drawn from one's own entry in the chat's
participants: pressed while `meat_proxy_lead` holds in this chat, never
for the hands part alone, which is the profile's in every chat (the
owner's word on tsk-rznymp9hb1qm: the mode in a chat means being told what
to do); its tooltip says whether that is the profile's value or this
chat's own. A click
sends the opposite as this chat's value; **Follow my profile**, shown
only while the chat has a value of its own, sends `null`. An agent, an
observer (no entry of its own) and a hub whose entries carry no
`meat_proxy_lead` get no switch. Since the hub emits no event for the change,
the switch takes the hub's `204` as the new state and works out what
holds itself (`null` follows the profile's lead part from `/me`); the chat's
value is read again from the participants the next time the chat opens.
The icons are the designer's two SVGs in `web/brand/`, drawn as a CSS
mask so that they take the button's colour (muted off, the accent on).

**Reason:** the switch belongs where the human writes in that chat, next
to the other per-message choices, and the same part in both composers
keeps them alike. A plain toggle covers on and off; the way back to the
profile is rarer and gets its own small link rather than a third state
on the button.

**Rejected alternative:** a three-way control (on, off, follow the
profile) on the button itself, which a click cannot step through
without passing a state the human did not want. Re-reading the chat
after each click to learn the state: the hub's `204` says the value was
taken, and the rule for what holds is the contract's. The icons as
`<img>`: an image does not take the button's colour.

## The Overview has three tabs, Summary, Swarm and Project; the organisation is a tab of the Team page

**Id:** 58c58a28-d6b1-453f-99dc-7f21179b3ee2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer, 2026-10-30, as the card tsk-n2r6t7jnzm2d passes it on (the Overview too full, split into tabs; the org chart on the Team/Members page as its own tab, not on the Overview; the swarm may stay or become a tab, the implementer's proposal); docs/api.md §16.11 (`organisation` is a project view); the split of the panels into the three tabs is the implementer's
**Supersedes:** d7ee1073-1752-4134-9e51-878c5c28f2c2
**Revisit when:** the GUI round with the maintainer moves a panel, or the Team page gets its Availability tab

2026-11-09: the project tab, the page title and the member page's breadcrumb are named Team (req-77az2zs017fe); its path stays /members. The Team page's own Members tab and its heading keep that name, so the Revisit-when lines on that tab are not triggered by this.
2026-11-10: the path follows the name: the view and its member pages are at /<owner>/<slug>/team (the maintainer's decision, so that the name and the path match; card tsk-yy9d5np8pjmr). `members` stays a reserved word, the maintainer's wish, so no slug or later view takes it; /members is a word that is no view, with no redirect. The Members tab keeps its name.

The Overview (`/<owner>/<slug>/overview`) has the tabs **Summary**,
**Swarm** (`overview/swarm`) and **Project** (`overview/project`), as
links with the shown one marked. Summary is what needs the reader and
the state: Waiting for you and Board, then Team beside Latest reports;
only it reads `GET …/overview` and re-reads it on card, request and
probe events and, for a narrow viewer, on its timer. Swarm is the swarm
section, read on its own. Project holds the facts (repository, state,
policy, contract, Keep the Why) and the README badge, read from what
the header already has. A tab the page does not know shows Summary.
The organisation tree left the Overview: it is the Team page's
**Organisation** tab at `/<owner>/<slug>/organisation`, a project view
the contract already lists, beside **Members** at `team`; both
pages carry the same two links (`M.teamTabs`), and the project's row
of tabs marks Members for either. The tree is drawn again when a member
event arrives.

**Reason:** one page with every panel had grown past what is read at a
glance; what needs the reader belongs on the first screen, and the
facts and the statistics are looked up, not watched. The swarm as a tab
keeps its own read out of every visit to the Overview. The org chart
describes the team, so it belongs with the team's list, as f0ca2279
planned the Team page.

**Rejected alternative:** the swarm kept as a row of Summary: a swarm
read on every Overview visit, and the page still long. The organisation
as a fourth Overview tab: the maintainer placed it with the team. A
`members/organisation` address: `members/<id>` is a member's page, and
a word there would have to be told apart from an id.

## Members filters to one's own agents with Only my agents, kept per viewer in the browser

**Id:** 7b08511c-7f7e-4af2-bd7e-df6f01476e0b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer, 2026-10-30, as the card tsk-n2r6t7jnzm2d passes it on (a filter 'Only my agents' on the members list, the member's `owner` being the signed-in human, remembered per viewer); where it is kept is the implementer's
**Revisit when:** the hub keeps per-viewer view settings, or the GUI round asks for the filter on other lists too

A human viewer of Members gets the checkbox **Only my agents**. On, the
list is the agents whose `owner_id` is the viewer, and the humans'
table is not drawn; with none, it says so. The choice is kept in the
browser's `localStorage` under one key per viewer
(`maity.members.mine.<member id>`), for every project, and a browser
that keeps nothing still filters for the visit. Agents never see the
box: they own no agent. What an owner may change on their own agent's
row without `members:admin` is unchanged (Manage with reports to,
preferences and team, §2.3).

**Reason:** the maintainer wants their own agents at a glance on a list
that holds everyone's. A per-viewer key keeps one person's choice from
another's on a shared browser, and the hub has no field for view
settings.

**Rejected alternative:** one key for every viewer: a second person
signing in on the same browser would inherit the filter. A key per
project: the maintainer asked for it per viewer, and switching projects
would lose it. A setting on the hub: there is no such field, and a
contract change for a list filter is out of proportion.

## An agent is isolated from its Manage row on Members, with a reason and a confirmation; the row and the list show it

**Id:** d2546b1d-4a69-4e89-9b98-d9b894c572ed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-n2r6t7jnzm2d (humans with members:admin get Isolate / Lift isolation with a reason, and the `isolated` badge); docs/api.md §6.2 "Isolation" as of #771; the coordinator's go to build against the contract before the hub's #783, 2026-10-30; where the controls stand and the confirmation are the implementer's; the card tsk-zwxtdfmdscf7 (the maintainer, 2026-10-31: a box in the lift dialog, unticked by default, hides the isolation's events; contract #826, the hub's reason in `context/members.md`)
**Revisit when:** the GUI round moves the member actions into a menu per row (f0ca2279), another owner's agent gets Propose change beside it, or the hub lets a hidden window be shown again

In an agent's **Manage** row, for a human with `members:admin`, after
the pause: **Isolate with a reason** (1–500 characters), sent as
`POST …/members/{id}/isolate` after a confirmation that names what
happens at once; an isolated agent shows who isolated it, when and why,
and **Lift isolation** (`DELETE` on the same path, no confirmation). The
name cell carries an **Isolated** badge with the reason in its title, on
every reader's list, since the member view carries `isolated` for all.
An agent's own caller and a member without `members:admin` get no
control. The fixture hub answers both routes as §6.2 describes.
Lift isolation sits in a small form with one box, **Hide what happened
while it was isolated**, unticked, and a line on what it means; ticked,
the `DELETE` carries `{"hide_isolation_events": true}`, unticked it
carries no body. The choice survives a redraw of the table (another
action, the presence refresh) as a typed reason does: it cannot be made
up for after the lift, the window comes only from the lift itself. A member with hidden windows (`isolation_windows`)
shows them under its name, as event ranges, to every reader of the
list, as `isolated` is shown; a seq is written as the hub gives it, not
formatted as a number.

**Reason:** isolation is the project's lever against a misbehaving
agent, beside the pause and the removal that already live in that row;
it takes effect at once for an agent another human owns, so the
confirmation says so before it is sent. Lifting gives access back and
loses nothing more, so it needs no question; whether the agent may read
the isolation's events again is the one choice it carries, and the box
starts unticked because the hub's default keeps them readable (§6.2).

**Rejected alternative:** a separate Isolate button on the list row:
the row holds Chat and Manage only (54a49af9), every other member action
is in Manage. Isolating without a confirmation like the pause: the pause
is a soft stop the owner may lift, isolation releases claims and closes
placements of someone else's agent.

## A chat's composer hides for reading on a phone and grows on a wide screen; both are the browser's choice

**Id:** 5af3970c-0f6a-42e7-a211-13ba27fbae5d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer, 2026-10-31, with a phone screenshot (card tsk-k6nakahy6fnj): fold the composer away on a phone to read, less empty space between the buttons and the field, the field 2× and 3× as high on a desktop with one click; kept per browser, no hub field
**Revisit when:** the GUI round moves the composer's controls, or the hub keeps per-viewer view settings

The composer of a direct chat and of a group chat has one head
(`M.chatParts.composeHead`): its label, then on a phone a button
**Hide the composer** / **Write a message** (controlling the form; its
label says what a press does, so it carries no `aria-expanded` as well)
and on a wider screen a group of **1×**, **2×**
and **3×** (`aria-pressed`) that sets the field's rows to one, two or
three times its own. Hidden, only the head stays, so the history takes
the room; shown again, the field has the focus. Quote opens a hidden
composer, so the quote it puts in is seen. On a phone the field is
capped at 40% of the screen's height, since a 2× or 3× chosen on a wide
screen still sets its rows there. Both choices are kept in
`localStorage` under one key for every chat, and a browser that keeps
nothing still applies them for the visit. An empty status line and an
empty list of files take no room in the composer any more, and its rows
stand 4 px apart.

**Reason:** reading a long chat on a phone wants the screen, writing a
long message on a desktop wants the field; neither is worth a setting
on the hub, and one key keeps the choice from one chat to the next.

**Rejected alternative:** a choice per conversation: the maintainer asked
for it per browser, and a reader would set it again in every chat. A
field that grows with its text by itself: it moves the history while one
types and still does not give a phone its screen.

## A chat fills the window from where it starts, less what stands below it; "Sending…" stands in the composer's row

**Id:** 21fd7884-0462-49dc-8e47-da59f57ef557
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-j10w2hsm1h90 (the owner, 2026-11-03: the chat no longer ended at the window's bottom edge after the product line of #1290; the Chats list column too; "Sending…" to move beside the meat-proxy switch); card tsk-df4tcq83pnf6 (the maintainer, 2026-11-02: the chat input ran past the bottom of the screen and the page had to be scrolled; wanted the input inside the viewport on desktop and phone, light and dark); browser measurements at 1280 × 800, 390 × 844 and 375 × 667 in the PR
**Revisit when:** the chat stops sizing itself with `--chat-h`, or the product line moves out of the page's flow
**See:** views.md#a-chats-composer-hides-for-reading-on-a-phone-and-grows-on-a-wide-screen-both-are-the-browsers-choice — 5af3970c-0f6a-42e7-a211-13ba27fbae5d — as of 2026-11-05

The open chat's height (`--chat-h`, `fitToScreen` in `js/chat.js`) is the window's height less where
the chat layout starts on the page and less what stands below it down to the end of the page
(main's padding, the product line of §16.13). Where that leaves room for the pane's fixed chrome
(heading, composer, and the like) plus about 60 px of history, the page ends at the window's bottom
edge, the product line under the composer is in sight, and only the history and the chat list scroll.
When the fixed chrome fits in the window but that comfortable height would run past the bottom edge
(a short phone, a tall header), the height stops at the window edge so the input stays on screen; the
product line may then sit just below the fold rather than pushing the composer off. That needs room
for at least about 24 px of history next to the fixed chrome; only when the fixed chrome with those
24 px is taller than the window below the layout (a tall sign-in banner on a short phone) does the
page scroll, and then the product line stays below the composer, never over it. It is
measured again on a resize and whenever the page around it changes size (a `ResizeObserver` on the
body: a banner above, the product line below), and on the visual viewport so a phone's on-screen
keyboard is followed. The observer measures in the next frame, not in its own round, where a new
height would resize the body again and the browser would report a ResizeObserver loop. Besides the
body it watches the pane's fixed parts and the panes the layout holds: folding the composer or making
it taller, and on Chats a group chat taking a direct chat's place, change the floor without resizing
the body; only the current pane's parts are watched. A layout not yet in the page, as Chats builds it
while its view is still drawn, is measured once it is there, a few tries at most, and then lets go of
its listeners; the holder a pane is drawn into on Chats is not measured at all, Chats measures the
layout the pane moves into. While a message is sent, "Sending…" and a failure stand in the composer's
row, after the meat-proxy switch and before Send, so no line appears below the row and nothing moves.

**Reason:** the earlier measure took the header's bottom and 16 px. It left out what stands between
the header and the chat and everything below it, so the product line pushed the composer past the
window's edge. On Chats the first measure came before the layout was in the page and stopped for
good, leaving the CSS fallback `calc(100dvh - 140px)`. A later floor of fixed chrome plus 60 px of
history kept the product line under the composer on a short phone, but forced `--chat-h` taller than
the window, so the input sat past the bottom edge and the page had to be scrolled to reach it.

**Rejected alternatives:**
- No product line on chat views: §16.13 puts it at the end of every page the dashboard draws.
- The product line inside the history's scroll area: it would only show at the end of the history
  and would scroll with the messages.
- A sticky or fixed product line: §16.13 says it is never sticky.
- The header's bottom plus a fixed allowance for the product line: its height changes with the
  width (it wraps on a phone) and a banner above the chat moves the layout too.
- Only a fixed floor (240 px) on a small screen: the heading and the composer of a group chat take
  more than that, so the composer ran past the pane and under the product line.
- A floor of 120 px of history: a group chat on a 390 × 844 phone no longer fitted the window
  even without a banner above it.
- Keeping `max(fixed + 60 px, space to the footer)` on every screen: on a 375 × 667 phone without a
  banner that floor was taller than the window, so the composer ran past the bottom edge and the
  page scrolled; the input has to stay in the viewport when the fixed chrome fits there.
- Stopping at the window edge whenever the fixed chrome alone fits: on Chats at 375 × 667 with the
  sign-in banner that left 3 px of history, an input in view with no message above it; below about
  24 px of history the page scrolls instead.
- A `ResizeObserver` on the body alone: the layout's height is fixed by `--chat-h`, so a change
  inside the open pane (the composer folded or shown, its 1×/2×/3×, a group's "Manage or leave",
  another chat on Chats) does not resize the body. The floor stayed the one measured first, and on
  a phone a group composer shown again ran under the product line with no history in sight.
- Watching the parts of every pane the layout ever held: on Chats each switch left the old pane's
  parts watched, and after twenty switches the observer watched over a hundred elements no longer
  in the page. Only the current pane's parts are watched; the ones that leave are let go.

## On a phone a chat shows less around it, and any chat can take the whole window

**Id:** 0e55c22f-572b-44a8-882a-52e1d4ee6813
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-fnch2yxp2kk1 (the owner, 2026-11-08, from a phone screenshot: the product line over three rows, the "In it:" line and the composer's hint taking the room, the chat hard to read); lotse#wtwy's go on the plan (nte-ekw1cx4xkxvb), with the §16.13 sentence in the same change; card tsk-2a56j80p3p9h (the owner, 2026-11-09, from a phone screenshot: the full-screen button at the top right, under the top bar's last entry, in a direct and a group chat; no agent session line on a phone)
**Revisit when:** the phone breakpoint (600 px) changes, the router stops drawing the view again on back, or the product line's parts change
**See:** views.md#a-chat-fills-the-window-from-where-it-starts-less-what-stands-below-it-sending-stands-in-the-composers-row — 21fd7884-0462-49dc-8e47-da59f57ef557 — as of 2026-11-08

At phone width (`max-width: 600px`, the dashboard's one phone breakpoint):
- The product line is only its first part, the Maity icon, `Maity` and the year (§16.13). The other three parts and the separators are not shown.
- A group chat shows no "In it: …" line over the messages. Its participants stay under Manage.
- The composer's label ("Message (@handle reaches someone in the chat)") is out of sight but still the field's label. A reader still hears what the field is for.

Wider than that, nothing changes.

Any open chat, direct or group, at any width, has a button in its heading row, an icon as the list's actions are (#1483), named "Read in full screen" and pressed while full. Where the chat list and the chat are one pane (`max-width: 720px`, a phone), it stands at the chat head's top right instead, on the row of the back link (← Conversations), and while full 8 px from the window's top and 12 px from its right; in the document it stays after the heading, so Tab still reaches it there. There a direct chat with an agent also shows no session line (`chat.session`) beside its heading. It sets `chat-full` on `<html>`, and the pane becomes `position: fixed` over the whole window at its height, on the page's ground; the page under it does not scroll.

The full screen ends:
- with the button again;
- with Escape, unless something open, a menu or the mention list, took that Escape first;
- with the browser's back;
- when the chat leaves the page: another view, or Chats putting another pane in its place.

Back works through `M.route.layer` (js/route.js). Entering pushes one history entry at the same address. Back from it only closes the layer: the router does not draw the view again, so the history, its scroll position and a draft stay as they were. The button and Escape leave that entry with a `history.back()` of their own, so no extra entry is left behind. A route change while it is full (a link in the chat, Back to the list, `go()`) closes the layer and takes its entry for the new address (`replaceState`, in fixture mode `location.replace`). Back from there returns to the chat once, not twice.

While full, everything outside the chat is `inert`: no focus reaches the covered page, and a reader does not read it. Only what the full screen marked is set back when it ends. The full chat's end is kept once in `js/chat.js`, not per pane: Chats swaps panes without disposing the view, and a closure per drawn pane would hold every pane visited until Chats is left.

**Reason:** on a phone the room above and below the messages is what makes a chat readable. The three things the owner named take that room and carry nothing the reader needs there: the product line's other parts, the participants (also under Manage) and the composer's hint. The full screen is for reading; on a phone it is the only way to see more than a few messages. Back is how a phone leaves anything that covers the page, so it must end the full screen and nothing more.

**Rejected alternatives:**
- `display: none` on the composer's label: the field would lose its name for a screen reader.
- The Fullscreen API (`requestFullscreen`): iOS Safari does not allow it on elements other than video, and it also hides the browser's own controls, which the owner did not ask for.
- A route of its own for the full screen (`…/chat/<id>/full`): a reload or a shared link would open a page with no way out but the button, and the router would draw the chat again on every switch.
- A history entry without the layer: the router draws the view again on every back (js/app.js `route.listen`), so the chat would be read again and lose its scroll position.

## The row of tabs has no New project tab; the tabs menu follows the tabs, a dragged tab's place is a line

**Id:** 4ff40142-df78-4c11-8f0c-c0024adecd79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-hp9gq9rmrdq2 (the owner, 2026-11-08: no "+ New project" tab, the "…" menu right at the end of the tabs); his word the same day, relayed by lotse#wtwy (seq 94519), that dragging works and he wants to see where a dragged tab lands, a line before or after the tab under it, by the drop's own half, the keyboard move unchanged; card tsk-45fhe2yrwzb7 (the owner, 2026-11-09: the "+" menu gets Runner, in the order Agents, People, Runner, Projects); card tsk-2a56j80p3p9h (the owner, 2026-11-09: on a phone the "…" stays at the right end of the tabs' row, never on a line of its own)
**Revisit when:** the row of tabs gets groups or pinned tabs, the "+" menu gets more than four items, or a drop learns a right-to-left order
**See:** views.md#the-project-tabs-are-the-browsers-own-moved-by-dragging-by-altshiftarrow-or-from-the-tabs-menu — cd4fe2ba-aaa7-47fd-aa04-43e97207d5d6 — as of 2026-11-08

The row of project tabs ends with the last tab; the tabs menu ("…") stands right after it. The tabs take their own width (`flex: 0 1 auto`), and a project's state keeps the far end of the row (`margin-inline-start: auto`). On a phone (600 px) the row wraps by the tabs' full width, which put the menu on a line of its own; there the tabs fill the room the menu leaves (`flex: 1 1 0`) and scroll, the menu keeps the row's right end, and the project's state takes the next row. New project is in the header's "+" menu, its last item since 2026-11-09 (Agent, User, Runner, then Project; Runner leads to `/runners` and its pairing form, tsk-45fhe2yrwzb7), which is named "Add an agent, a person, a runner or a project". The empty state's Create a project stays.

While a tab is dragged, a 3 px upright line in the accent colour stands in the gap beside the tab under the pointer: before it when the pointer is on its first half, after it on its second. The drop puts the tab exactly there; both read the same half (`dragTab.pastMiddle`). Only one tab carries the line at a time, never the dragged tab itself. The line goes on `dragleave`, on the drop and on `dragend`, wherever the drag ends. It is a `::before` or `::after` of the tab, placed absolutely 5 px outside it, so nothing in the row moves; the row keeps 6 px after its last tab, so the line after that tab is not cut off.

**Reason:** the owner's layout. A tab for one action among the projects read as one more project and kept the menu far from the tabs it manages. A line drawn by the drop's own rule is the place the drop takes, so what the eye sees is what happens. A border or a margin would shift the tabs under the pointer and so change the half it is on.

**Rejected alternatives:**
- New project as an item of the tabs menu: that menu is about the tabs, not about creating.
- The line as an element between two tabs: it would widen the row while dragging and move the tab under the pointer.
- An inset `box-shadow` on the tab: on the round tab it follows the curve and reads as a second border, not as a place between two tabs.

## Forge access is a section of the account, also at /settings/forge; a project's settings say which grant reads its repository

**Id:** 861705c6-539c-4d4c-9532-658311c463b7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-6pbe89e1yt50 with the maintainer's decision that the hosted instance carries no platform GitHub token, 2026-10-31; docs/api.md §11.4 (links, own token, step-up, the setup redirect to `/settings/forge`, the owner's confirmation), §16.11 (the path), §6.1 (`probe_via`, `owner_confirmed`)
**Revisit when:** installations on a forge organisation may serve a Maity organisation (§11.4 "Follow-up"), or a second forge is added

**Forge access** is a tab of the account's Security
(`/account/security/forge`), next to the sessions. It shows:
- the linked installations of the instance's GitHub App, each with its
  status and the repositories it covers;
- **Link the GitHub App**, offered only where `app_configured`;
- **Unlink**, which says it does not uninstall the App on GitHub and
  links to GitHub's page;
- the human's own fine-grained token: stored, replaced or removed,
  with a hint naming the read permissions the probe needs.

A token is never shown, only that one is set, its login and its status.
`/settings/forge`, the path the hub's setup redirect lands on, shows
that same tab at its own address. Its `?error=<reason>` is said
in words and dropped from the address. A project's settings say which
grant reads its repository (`probe_via` in words) and whether the
namespace owner confirmed it, with **Confirm this repository for my
grants** for the namespace owner (for an organisation's project any of
its owners, who may replace another owner's confirmation with their
own grants) and a link to Forge access.

**Reason:** the grants are the human's own and serve every project they
own, so they belong on the account, not on one project. The project's
settings are where an admin wonders why nothing is read. Without the
owner's confirmation their grants are never used for the repository,
so the confirmation stands next to the grant it unlocks.

**Rejected alternatives:**
- A page of its own at `/settings/forge`: a second "account" with one
  section, beside the account that has all the others.
- Redirecting `/settings/forge` to `/account/forge`: the contract names
  `/settings/forge` (§16.11), and a redirect would add a hop to the
  setup's return.
- Showing the probe's `details.reason` on the settings: it comes from a
  failed read, not from the project view, and the view's `probe_via`
  with the confirmation already says what is missing.

## The landing page is imported and exported as JSON in its editor; an import is checked by the preview call and saved only by Save

**Id:** c174a492-2691-4887-9507-e1ba2e805a1f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-36d575f5yybz (the maintainer, 2026-10-30: load the prepared landing V3 with one click; paste or file, the body of PATCH …/landing or one page; the hub's refusals per field; nothing saved before the admin confirms; Export the draft); how it is checked is the implementer's
**Revisit when:** the hub offers a check of a landing draft of its own, or imports grow to the legal pages

Under the landing editor, **Import or export JSON**: a field and a file
choice. **Export the draft** writes the draft as the hub takes it
(enabled, default language, pages, footer) into the field; **Copy**
copies it. **Load into the editor** reads either that body or one
language's page (title, description, sections), asks before it
replaces the whole draft or the page shown, draws the editor from it,
and sends it to `POST …/landing/preview`, the hub's own check, which
stores a draft for ten minutes and saves nothing. Its refusals are
said at their fields as a save's are; **Save** stays the only call that
saves, so the confirmation that counts is the admin's Save after
looking the import over. A field the imported body leaves out keeps what
the editor has, as a `PATCH` keeps the stored one: the prepared V3 file
has no footer, and an empty operator line is one the hub refuses
(`footer.operator` is 1 to 120 characters or none), so the editor sends
none instead of an empty one. The hub checks an import before the
editor is drawn from it; a body whose pages, sections or lists are of
the wrong kind leaves the draft as it was. That kind check covers every
value the editor binds to an object, not only lists: a button, a group
and each footer link must be an object, or absent where optional, or the
editor would break after the draft was replaced. A section's type is
looked up among the editor's own types only (`Object.hasOwn`), so a
`constructor` or `__proto__` in an import is drawn as an unknown section,
never taken for something every object inherits. Save asks for the
step-up (§2.8.4) the hub requires for this call.

**Reason:** the preview call already validates a draft exactly as a
save does, so the import reuses it instead of a second check in the
page that could drift from the hub's. Drawing the import into the
editor before anything is stored lets the admin read and fix it there.

**Rejected alternative:** saving on import, with a confirmation: one
click from a file to visitors, without the editor in between. A check
of the JSON in the page: a copy of the hub's rules that ages with each
new section type. Drawing inside try/catch and restoring the draft
afterwards: it would hide real drawing bugs and leave a half-built
editor behind.

## Landing variants are edited one at a time in the landing editor; campaigns sit beside the privacy hint, their counts in Statistics

**Id:** 43d9837f-64fd-44d8-9527-1e590092ad38
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-ets3x0c4ethg with the maintainer's request for A/B testing before the launch, 2026-10-31; docs/api.md §16.7.2 (contract #823)
**See:** https://github.com/oliver-zehentleitner/maity — b9dc57f9-7581-47ef-acc8-00b679f7aa1e — as of 2026-10-31
**Revisit when:** the hub serves more than five variants, or a variant gets a header or footer of its own

The landing editor edits one page at a time: the main page or one
variant, picked in a row of buttons above the languages, with the same
page editor. Only the path prefix of the hub's refusals differs
(`variants.<slug>.pages`). A variant starts with an empty page in the
default language, the one the hub requires. A language it lacks shows
its own default page, which the editor says. **Campaigns** are a list of
code and label next to the privacy hint the contract asks the dashboard
to show. Both travel with the setting in one `PATCH`, in the preview
and in the JSON import and export. **Statistics** shows the campaign
counts for the same window as the instance's figures and links the
hub's CSV. The fixture hub serves no file, so there is no link there.
The registration page sends `v` and `c` from its address as `origin`,
dropping a malformed part; the hub decides the rest.

**Reason:** a variant is a page like the main one, so the editor the
admin already knows serves it. Two editors would drift. The counts
belong with the other counts. The CSV is the hub's own, so the columns
cannot differ from what the contract names.

**Rejected alternatives:**
- A separate Variants section in the admin area: the same page editor
  twice, and header and footer, which variants share, would look
  editable twice.
- Building the CSV in the browser from the JSON: it works in fixtures
  too, but copies the hub's columns and quoting by hand.
- Sending `v` and `c` unchecked: the hub drops them silently anyway, but
  a malformed value would then sit in the request for nothing.

## A site file's placeholders are filled by the dashboard, and the hub refuses any left over

**Id:** 7c1e4a52-9d3b-4f06-8a27-5e0b6c9f1d34
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-yjbzd8wvwz4n (the maintainer's request: values kept in the backend, `{{name}}`, the finished text stored, no way past the check); which texts the hub's rule leaves alone is this entry's reading
**Revisit when:** a public page has to quote a `{{name}}` literally, or a value has to differ by language

`{{name}}` in a site file takes its value from
`/admin/settings/site-values` in the dashboard, before the file is checked.
The hub stores finished text and never replaces anything; it refuses a text
still holding a placeholder on the landing page, legal and registration
writes, so a section's own import or a direct call cannot publish one either.

**Reason:** the template is in a public repository and the operator's details
are not, so they live in the instance. Stored text keeps what a visitor reads
fixed until the next import, as the request asks. `[Name]` collided with
Markdown links. The hub's rule also catches a slip such as `{{ Name }}`, which
would otherwise reach the page; it leaves `{{ .Values.x }}` and `{{#if x}}`,
which a page about a template language may quote and no site file's
placeholder can be. The rule catches a slip, not intent: `{\{name}}`, a
Markdown escape, passes and shows as `{{name}}`.

**Known limit:** a value goes in as written, so Markdown in it (`*`, backticks,
a link) takes effect where the placeholder sits in Markdown. HTML cannot get in:
the finished text passes the hub's Markdown check and the renderer escapes.
Values are one line, so none can start a block of its own.

**Rejected alternative:** the hub replacing on every read: a later value change
would rewrite published legal text with no new version. A check in the
dashboard alone: the request names other ways round it. Refusing every `{{`:
it would hit legitimate quoted text. A value per language: not asked for, and
a name per language does the same (`{{country_de}}`).

## The public pages are in ten languages, each translated and checked as a whole

**Id:** 4b8e2d71-6a0c-4e39-9f15-c27d3a6e8b02
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's list `en de fr es pt it nl ja ko zh-Hans`, passed on in the message on the card tsk-q5f23gacz1mp (seq 30343), and on the same card that the legal pages are translated too; how the list is carried and checked is this entry's reading
**Revisit when:** a language writes right to left, or a legal text has been reviewed by a lawyer

`landing.LANGUAGE_NAMES` carries the list and each language's own name, which
the language bar shows, since ten bare tags read as a code list. The page's
frame words are in `render.WORDS`. The instance's own site file holds every
text in all ten; a command line in the demo, an agent's handle and a cookie's
name stay as they are. `hub/tests/test_site_values.py` and the e2e step import
a neutral file with the same shape (`web/tools/site-fixture.json`), filled with
made-up values, and read every language; **Check the file** covers a real file
when it is imported.

**Reason:** the operator asked that the import works for certain. A wrong
placeholder in one language would otherwise show only on the live page.

**Rejected alternative:** Right-to-left support: no listed language needs it,
and it touches the stylesheet's every side. Traditional Chinese answered with
Simplified: `Accept-Language: zh-TW` goes on to the reader's next language.

The translated legal texts are machine translations, reviewed by nobody with
legal training. The English and German are not changed by them.

## An instance's site file is not in the public repository

**Id:** 68502afd-2713-4ea1-b341-73a6efb50537
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction on the card tsk-pfn7yg91d1y7, 2026-11-01, and the coordinator's word on the same card that **Check the file** is enough for the real file; the maintainer named no reason for the move
**Revisit when:** a public template for operators is wanted again
**See:** views.md#the-whole-site-is-one-json-maity-site1-checked-part-by-part-and-saved-in-turn-by-the-dashboard — 3b7c4d67-90b2-497a-9dd7-1f7a7ddfb7bd — as of 2026-11-01

The site file of the instance the project runs is kept outside this
repository, and an operator writes their own. Tests, smoke and e2e read
`web/tools/site-fixture.json`: every section type, all ten languages for the
landing and legal parts and two for sign-in and sign-up, with
placeholder text and the seven placeholders, none of an instance's words. Git
history keeps the old versions, and nobody rewrites it.

**Rejected alternative:** Tests skipped when no file is there: CI would no
longer cover an import in every language. A public copy of the instance's
texts kept as a template: that is what the instruction ends.

## The whole site is one JSON, maity-site/1, checked part by part and saved in turn by the dashboard

**Id:** 3b7c4d67-90b2-497a-9dd7-1f7a7ddfb7bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions req-0cv1n7eaegay (o1: one JSON for landing, legal and registration, dashboard only, no hub endpoint) and req-39vmjgrq5s32 (o1: a template in the repository, the imprint with placeholders only, landing-v3-complete.json dropped for one source; the template in the repository ended with 68502afd-2713-4ea1-b341-73a6efb50537, 2026-11-01), relayed by the coordinator on the card tsk-xw8a2hd84x3a, 2026-10-31; the coordinator's word that placeholders go in square brackets; the coordinator's decision on the review of #961, 2026-10-31 (an unknown key anywhere refuses the whole file; variants and campaigns stayed out while the editor's import did not know them, until the coordinator's decision on tsk-ets3x0c4ethg, 2026-11-01, took them in); the coordinator's decision on #961, 2026-10-31 (the template carries no registration; registration is the instance's own); docs/api.md §2.8.4 (a step-up holds 10 minutes); the dashboard's implementation, 2026-10-31
**Revisit when:** the hub offers one call that saves several settings in a transaction, or a fourth setting joins the site file
**See:** views.md#the-legal-pages-and-registration-import-and-export-json-too-text-not-loaded-stops-a-preview — 951ed7bf-6f23-4279-a4c6-f2c03c7c31ea — as of 2026-10-31

Since tsk-fct4awzw3k30 it stands folded at the top of the admin's **Pages**
tab, over the sub-tabs, as it spans them; `/admin/site` is gone without a
redirect (alpha), and `/admin/pages/site` opens it.

The instance admin has **Import or export everything** for the landing
page, the legal pages and registration as one file, `maity-site/1`,
extended language by language and imported again. Each part has the shape
its own section imports; a part the file leaves out stays as it is, and an
unknown format or key is refused by name. A check runs each part through
the call its section uses (the previews, registration's own check) and
lists it as changes, the same, not in the file, or refused. One Save then
runs the existing PATCHes in turn (each changed legal page, registration,
the landing page). The second factor is asked for once, since a step-up
holds for 10 minutes; each call still goes through the step-up helper, so
an expired window asks again rather than fails. A save that stops says
what is saved and what is not and goes no further, with no rollback. The
template that replaced `landing-v3-complete.json` has since left the
repository (views.md#an-instances-site-file-is-not-in-the-public-repository).
A site file need carry no registration: registration is the instance's own,
and a file imported whole would otherwise close an open registration without
a word.
Placeholders were first in square brackets, since the hub's Markdown rules
read `<Operator>` as an HTML tag and refuse the text; they are `{{name}}` now
(`docs/api.md` §16.7.3).

An unknown key anywhere in the file refuses the whole file, named by its
path, down to each part and legal page (deeper, in a page's languages or
the landing page's pages, the hub's preview refuses the part with its own
field names); a landing value of the wrong kind refuses its part. `variants` and
`campaigns` are in the landing part, as in the landing editor's import
(views.md#landing-variants-are-edited-one-at-a-time-in-the-landing-editor-campaigns-sit-beside-the-privacy-hint-their-counts-in-statistics);
the format's name stays `maity-site/1`, since a file without them still
means what it did and nothing has to read an older one. Export and Download read the three settings again first: the admin
page builds every section when it opens, so a file exported from that
first read would carry the state from before an edit in another section,
and importing it again would revert that edit.

**Reason:** one file for the whole site is what the maintainer works with,
and the dashboard can do it with the calls the sections already have, so
it needs no contract change and comes a day sooner. The site file is
refused as a whole when any key is unknown, at the top or inside a part:
a key the dashboard drops without a word looks saved to the person who
wrote it, and a typo in `enabled` would leave the public page in the
wrong state.

**Rejected alternative:** a hub endpoint that saves all parts in one
transaction, a day later and a contract change. Keeping the three imports
apart, which gives no "one file for everything". Placeholders escaped as
`\<Operator\>`, which the hub's check still reads as a tag where a space
follows the first word.

## The legal pages and registration import and export JSON too; text not loaded stops a preview

**Id:** 951ed7bf-6f23-4279-a4c6-f2c03c7c31ea
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-knb9me77f32t (the maintainer, 2026-10-31, after importing Landing V3: the same importer for the legal pages and registration); the coordinator's note that a preview of an imported but not loaded draft should say so instead of flickering (2026-10-31); docs/api.md §16.4, §16.7.1; the dashboard's implementation, 2026-10-31
**Revisit when:** the hub offers a dry check for the registration setting, or a PATCH of the legal pages may change several pages at once
**See:** views.md#the-landing-page-is-imported-and-exported-as-json-in-its-editor-an-import-is-checked-by-the-preview-call-and-saved-only-by-save — c174a492-2691-4887-9507-e1ba2e805a1f — as of 2026-10-31

Each legal page has its own Import or export JSON, for its languages (or
the same under the page's key). A load is checked by the page's preview
call and replaces the page's draft after a confirmation. Registration has
one for the body of its PATCH: a load fills the form after a
confirmation, keeps the fields the environment or the legal pages set,
and names a field the setting does not have. A field the JSON does not
name keeps what the form shows, typed and not saved included, since the
load starts from the form; an empty limit is left out of the export, so
an export always loads again. A legal page's load from a file of several
pages takes only its own and names the others. The hub checks the values
when the admin saves. Both editors share one part (`js/json-io.js`). In
every editor, the landing page's included, a preview while the JSON
field holds text that was neither loaded nor exported says so and opens
no tab.

**Reason:** a PATCH of the legal pages changes one page per call, so one
import per page matches what a save can carry. Registration has no
preview call, and a PATCH would save, so the form is the place to look
the values over. A preview of the editor's draft beside unloaded text
looked like a broken preview: the tab opened and closed at once.

**Rejected alternative:** one import for all three legal pages, which
would need three saves the admin does not see. Checking registration by
the real PATCH, which saves on success. Moving the landing editor onto
the shared part in the same change: its import also takes one page of
several and redraws the section list, so it keeps its own for now.

## The jour fixe is a tab of its own: its rounds and what each reader may do under one; its series are the next entry

**Id:** 8310dfc9-6e1c-48ed-a069-4579214194da
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-6h70epze0906 with the maintainer's request to have the jour fixe before the launch, 2026-10-31; docs/api.md §20 (the hub implements it), §16.11 (`/<owner>/<slug>/jour-fixe/<round id>`)
**Revisit when:** an agent moderator's work (the statement, the report) is to be done in the dashboard
**See:** views.md#the-jour-fixe-is-kept-per-series-in-project-settings-and-the-tab-groups-its-rounds-by-series — d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998 — as of 2026-10-31

**Jour fixe** is a tab of the project. At `jour-fixe` it lists the
rounds, grouped by series (below). At `jour-fixe/<id>` it shows one
round as a member reads it (§20.7): the series' topic, phase and
deadline, moderator, the number of answers but never an answer,
participants and the absent with their reason, the steps, the
statement, the posts and the report with each proposal's triage. The
series themselves, their moderators and the start by hand are the next
entry's: the contract made them several per project (§20.1), and that
part of this entry, a single schedule in Project settings and a
moderator order, ended with it.

Under the round, each reader gets what they may do (`js/jour-fixe-act.js`):
- **A participant** answers while the window is open: three texts, by name
  or anonymously. Choosing anonymous shows what anonymity does not cover
  before anything is sent (§20.4). Afterwards they read their answer back
  and may withdraw it.
- **The moderator and the humans of the admin team** read the answers
  (an anonymous one names nobody) and remove one with a reason.
- **A human moderator** writes the statement (topics, who said what,
  proposals), adds a further step, and writes the report. In the report,
  each statement proposal goes to the owner, is decided with a reason, or
  is left out. A decision carries the rules version and the decider's
  preferences version as its basis (§19.4).
- **An eligible member** posts once per topic in the open step.
- **A human who was invited, or one of the admin team,** removes the
  report's summary, a finding or a proposal.

An agent moderator does its part through the API, not here. The report
form offers no `humans_only` flag and no proposals of the moderator's
own; both are open for a later change, not left out by decision. A
decision is offered only where the project names its `rules_version`,
so the basis never carries an invented one.

**Reason:** a round is read by every member, so it belongs in the
project's tabs. The contract keeps answers with their readers, so the
round's page never shows one, only the count.

**Rejected alternatives:**
- The rounds inside Project settings: members without `project:admin`
  read rounds too.
- The anonymity limits in a link or a tooltip: §20.4 asks for them to be
  shown before an anonymous answer is sent, so they open with the choice.
- Editing the former single schedule field by field (it was replaced
  whole, so a partial form would have reset what it left out): gone with
  the single schedule, since a series is its own resource.

## The jour fixe is kept per series in Project settings, and the tab groups its rounds by series

**Id:** d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §20.1, §20.2, §20.7, §20.9 (contracts #934 and #936); the card tsk-39sjeqre25gw
**See:** views.md#the-jour-fixe-is-a-tab-of-its-own-its-rounds-and-what-each-reader-may-do-under-one-its-series-are-the-next-entry — 8310dfc9-6e1c-48ed-a069-4579214194da — as of 2026-10-31
**Revisit when:** the hub names the link targets of the two jour fixe inbox items (§18.1), the shape of `pending_moderators`, `own_agents` and the 202 body is fixed, or a series' keeper who is no project admin is to keep it from the dashboard

Where that section sits is the next entry's since 2026-11-06 (folded at the top of the jour fixe tab); what follows about its content holds there.

**Project settings** has a section "Jour fixe series" for a human with `project:admin` (`js/jour-fixe-series.js`): the list of series with topic, circle, on or paused and the schedule as a sentence; one form for a new series and for editing one (topic, circle `owner`, `humans` or `all`, the circle owner among the human members, `enabled`, recurrence, time, timezone, the three windows, a reason). Circle and circle owner are fixed once created, so the form shows them disabled when editing. A hub refusal is shown at its field, the 10-series limit under the topic. Per series it lists the moderators and the grants waiting in `pending_moderators`, each with End, and a member selector with Grant; the grant's answer is not read from the status (201 takes effect, 202 waits) but the series is read again, which shows which of the two happened, and a pending entry says it waits for the agent owner's and a keeper's consent. An owner series of someone else shows an admin only the line "a private series of @owner" with its schedule and Delete, never its topic, moderators or rounds (§20.1).

The **jour fixe tab** shows one block per series the reader may see: the topic as heading, circle and schedule, the next slot or that none is scheduled, the open round and its rounds, a "Start a round now" for the series' keepers and moderators that shows the hub's 409 reason in words (`jour_fixe_open`, `project_closed`, `no_moderator`, `too_few`), and each member's own switches (§20.2, §18.1): opt out of the series and take part again, get the report or stop getting it, for oneself and for each of one's own agents (sent with `?member=`). Nothing is drawn for a series the reader may not see.

**Reason:** moderating, the schedule and the circle belong to one series, and a project may have ten, so a settings form for one schedule cannot hold them; a list with one form is the smallest thing that creates, edits and deletes several. The tab is where keepers and moderators start rounds and where every member, not only an admin, opts out, so those parts sit in the series block and not in the settings. Re-reading the series after a grant is used because the status is not available to the page (`M.api` returns the body) and the contract leaves the 202 body unspecified.

**Rejected alternatives:**
- One form with a series selector: creating and deleting several items needs a list anyway.
- Per-series moderators and the manual start in the settings only: the start is for moderators who are no admins, and the opt-out is every member's.
- Reading the series from `GET …/series`: its shape is not given in the contract, so the tab reads them from `GET …/jour-fixe`; the fixture hub serves both.
- A link for each of the two inbox items: §18.1 names no target type for them, so they fall back to the project inbox until the hub names one (`linkOf` in `notify.js` then needs a branch).

**Not covered, known:** a project owner who is the `circle_owner` of a series but no project admin cannot open Project settings, so the series section is not reachable for them from the dashboard. The contract has no call for a keeper to add other members to the report list, so the list is changed per member for itself or its own agent only. Likewise, §20.2 lets an agent's owner who is no keeper, and a human with `members:admin`, grant the moderator right, but the grant form is in Project settings (`project:admin`), so an agent's owner who is no admin cannot start a grant for their agent from the dashboard, and the fixture hub refuses it from anyone who is neither a keeper nor the agent's owner.

The fixture hub's start of a round by hand refuses in the hub's order (routes/jour_fixe.py `start`, then `rounds.prepare`): `circle_owner_gone`, `rate_limited`, `project_closed`, `jour_fixe_open`, `no_moderator`, `too_few`, so that a test sees the same first error as against the hub where two overlap. A moderator who opted out does not moderate, as `rounds.prepare` drops those members before it looks for one. `too_few` counts the circle without those who opted out, plus the moderator, also outside the circle; presence is not modelled, every member counts as present. Rejected: checking in the order the view needs them, which would let a test pass against the fixture and fail against the hub where two refusals overlap.

## The jour fixe series are kept folded at the top of the jour fixe tab; Project settings only link there

**Id:** b2047dbd-b2e4-4d5b-a7b9-e8c38819d3fc
**Type:** decision
**Status:** active
**Evidence:** unknown
**Source:** the maintainer's request on the card tsk-3526xb7mqg9r, 2026-11-06
**See:** views.md#the-jour-fixe-is-kept-per-series-in-project-settings-and-the-tab-groups-its-rounds-by-series — d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998 — as of 2026-11-06
**Revisit when:** a series' keeper who is no project admin is to keep it from the dashboard

The section "Jour fixe series" (`js/jour-fixe-series.js`) moved from
Project settings to the top of the jour fixe tab, above the series'
blocks, as a `<details>` that is folded by default. It is shown to the
same readers as before, a human with `project:admin`; others get the tab
as before, without it. The series are read only when the section is
first opened. A change made in it draws the series' blocks below again,
not the whole tab, so the section stays open. Project settings keep a
short section with the same title that links to the jour fixe tab.

The schedule's switch reads "Activated", with a hint below it on what it
does (rounds open on the schedule; switched off, the schedule stays
stored and a round can still be started by hand).

**Reason:** the move and the folded default are the maintainer's request.
The card gives no reason for the placement beyond the request, so that
part is `unknown`. For the label it does: the German "Runden nach diesem
Zeitplan eröffnen" did not say clearly that it switches the series on.
The remaining choices are this change's own (inferred): a link in
Project settings, so a keeper who looks there for the series still finds
them; reading the series on first opening, since most visits to the tab
are to read rounds; and drawing only the blocks again, since drawing the
whole tab would fold the section back while a keeper works in it.

**Rejected alternatives:**
- Keeping the section in Project settings: the maintainer asked for the move.
- Removing it from Project settings without a link: the card allowed it;
  the link was kept for keepers who look for the series there.
- The section open by default: the card asks for it folded.

## All projects has two pages, Inbox and Chats, as a project has its views

**Id:** c72e8c45-838f-4304-bf9f-9e1d3a7693a7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-gw59z3w3fenf (the maintainer, 2026-10-31: the existing chats page as a second page under All projects, beside the Inbox, with unread counts); the row of pages is the implementer's
**Revisit when:** All projects gets a third page, or the Chat button and the Chats page part ways

Under the header, where a project shows its views, All projects shows
its two pages: **Inbox** (`/all`, the requests across projects) and
**Chats** (`/chats`, every chat across them), each with the hub's
count for it (`counts.inbox`, `counts.chat`, §18.2), refreshed with
the other counts. On either page **All projects** stays current in the
project row and the header names it as on the Inbox; the Chat button
leads to the same page. A chat notification already leads into its
chat. Rejected: Chats as a scope of its own outside All projects, as it
was: the reader found the chats only through the Chat button, not
where the requests across projects are. A tab inside the inbox view:
the inbox and the chat list are views of their own, and a page address
for each keeps the back button and links working.

## The memory provider is changed in Project settings, with a reason

**Id:** de95eb84-842b-4476-95c6-dcbaf3a98064
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-41hpr02cvej8 (the maintainer, 2026-10-31: a project under `none` cannot make Keep the Why required, and the dashboard offered no way to change the provider); docs/api.md §6.1 (a change by `PATCH`, `project:admin`, bumps `rules_version`, makes and cancels no setup card), §6.23
**Revisit when:** a second provider arrives, or the hub sets something up or cancels setup cards on a provider change

In Project settings, a human with `project:admin` changes **Project
memory** (Keep the Why, None) with a reason; the form sends
`{memory: {provider}, reason}` and says that the change reaches the agents
at their next resume, makes no setup card and cancels none, and that
setting Keep the Why up in the repository, or removing it, stays work for
an agent on a card. Others see the provider and its explanation read
only. After a switch to Keep the Why the commitment below offers
`required` and reads it unless someone set it; under None it is
`optional` and locked. The reason is asked although the hub takes the
change without one: it lands in the `rules_changed` event, as a policy
change's reason does.

**Reason:** without the change a project created under None could never
have Keep the Why required (§6.23 refuses `required` there), and the
maintainer could not set it for this project. The panel says plainly
what the change does not do, which was the reason it was read only.

**Rejected alternative:** keeping the provider read only with a pointer
to a card (a8e479be's earlier rule): an agent cannot change the
provider either, only a human with `project:admin` can, so the pointer
led nowhere. Making the setup cards on a switch: the hub does not
(§6.21), and the dashboard does not invent cards the contract leaves out.

## The Keep the Why personal settings are left out under no memory provider, and show no values

**Id:** 2e30b22e-1cf1-4559-a77a-16f8237bb53b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-j8gwrdy9d5c2; docs/api.md §6.23 "The dashboard's part"; a review of the pull request

Project settings offer `policy.keep_the_why_defaults` only while the
memory provider is Keep the Why, and name the repository's
`.keep-the-why` as the origin without showing its values.

**Reason:** without the provider no agent is told about personal
settings at all, so the choice would have no effect. The commitment form
above it stays visible and disabled there because it explains why Keep the
Why cannot be required, which this one has nothing to add to. The values
are not shown because the hub does not read that file.

**Rejected alternative:** a read-only view of the defaults with a link to
edit them, which the card asked for: §6.23 asks only for the origin, and
so it was dropped.

## A project's own links stand beside the repository, which reads "Repository" whatever the forge; the form sends only what changed

**Id:** 10a77061-c980-4990-b44b-cb7f518cd4eb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-ayaav7naskbe, taken over from #846 with its review; the maintainer's decision recorded with 11b7e786, relayed by the coordinator (the repository button reads "Repository"), 2026-10-31; docs/api.md §6.11; the maintainer's request for an Actions button between Repository and Pull Requests, card tsk-kdkdy864q11r, 2026-11-10
**See:** https://github.com/oliver-zehentleitner/maity — 11b7e786-ecf7-4971-ae04-48760fd1fd41 — as of 2026-10-31
**Revisit when:** a fifth kind of link is added, or the header row has no room for the buttons on a phone
**See:** views.md#on-a-phone-the-projects-links-are-one-row-that-scrolls-the-state-stands-beside-it — df210b31-e55a-47c9-93da-2d139e9ded89 — as of 2026-11-03

The header's row shows the repository, then Actions, then Pull Requests, then the
project's own links that are set (issues, wiki, discussions, chat, each
with its mark), then the
Keep the Why dashboard, and after them, at the right end, the state: the
maintainer asked for the state on that side and for the Pull Requests
button (tsk-hf70q6maf8cv, 2026-11-01; no reason was recorded). Unlike the
own links, Pull Requests is derived in the browser from the repository's
URL and forge, and a forge outside the table gets no button; the hub knows
only GitHub today, so the other three targets wait for it (tsk-sqpcbndm0tvd).
Actions, which the maintainer asked for (tsk-kdkdy864q11r, 2026-11-10), is
derived the same way, but only for the forges that call their workflows
Actions (GitHub, Gitea): GitLab and Bitbucket call theirs Pipelines, a word
of its own that no card has asked for yet. Its screen-reader name says the
forge ("Actions on GitHub"), as the repository's does. A second derived
button is not the "fifth kind of link" the Revisit condition below means
(an own link of §6.11, which the hub stores): it follows the forge table,
and on a phone the row still holds every button in one row that scrolls
(e2e at 390 and 360 px, light and dark). Neither derived button is on the
overview's Project tab, which shows the own links only.
Each link is plain https
only and opens in a tab of its own with `rel="noopener noreferrer"`. The
repository's button reads "Repository" for every forge. Its mark and
its name for a screen reader ("Repository on GitHub") still say which
forge. The overview's Project tab shows the same links as buttons
beside the repository. They are not in the header's list of projects:
each entry there is itself a link, which cannot hold four more, and `/me`
does not carry a project's links; §6.11 was changed to name the header
beside the project's state instead (review of #884). Project settings have four fields that send only
the links that changed; an empty field clears its link, and each refusal
of the hub is said at its field.

**Reason:** with up to six buttons in the row, the forge's name as the
label took room the four new ones need, and the mark already shows the
forge. The hub merges links by key (§6.11), so a form that sent all four
would overwrite another admin's change to a link it did not touch.

**Rejected alternatives:**
- The forge's name as the label, as before (the old header): wider, and
  it said twice what the mark says.
- Sending all four links on every save (#846): it loses another admin's
  change made meanwhile.


## The chat lists' pin buttons are a mode for managing pins: hidden on every load, stored nowhere

**Id:** 8d534643-d67c-4da0-b383-075c5cc4e6a0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-4nf344w4c52c; the maintainer's description, relayed by the coordinator: the pin buttons show only while he manages pins, then he hides them again (chat 102521, 2026-11-10)
**Revisit when:** someone wants the buttons kept shown across reloads or devices, or the hub stores display choices for a human

Pins themselves are the hub's, per human (§9.3), and a pinned chat keeps its 📌 mark in the list
whatever the mode. The pin/unpin button on each row of the project's chat list and of /chats is
hidden until the toggle in the list's heading row shows it; pressed again, or after a reload, the
buttons are hidden again. The choice lives in the page alone (`pinColumn` in `js/chat.js`), shared by
both lists while the page stands. On /chats the toggle stands after the Lead's slot, so that on a
phone the heading keeps its row and the Lead its place under it at the left edge.

**Rejected alternatives:**
- Keeping the choice in the browser (localStorage, as the board's column filter is): the
  maintainer uses the buttons only to set pins up, so a choice that outlives the page would leave
  the column shown when he no longer wants it.
- A field on the account (`PATCH /me`): a contract and hub change for the same unwanted
  persistence, across devices as well.
- Hiding the pin mark with the buttons: the mark says which chats are pinned, which the list's
  order alone does not.

## The settings form says what an unset agent_owners reads now, from the page's public_page and state

**Id:** deb3b4e8-266a-42c8-ab30-6cdeeb0da50c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.1, §6.2; the card tsk-25q1kv8xwnfj; the hub's `policy.of` and `agent_owners.effective`
**Revisit when:** the project view carries the effective value or the namespace owner's suspension

The form shows an unset `agent_owners` as "Not set, follows the public page (now: …)", worked out in the page from `public_page`, `state` and `moderation`, since the hub's policy returns only the stored value. Once set the option is gone, as the hub never takes null again. The roles offered are the four bases of §6.1 and project roles on them; a role already stored stays offered, so that saving cannot drop it unseen.

**Rejected alternative:** a new hub field for the effective value: a change of contract for one sentence. The page reads a hide by moderation from the project view's `moderation`, present only while a hold stands (§16.8), and then says `members`. The cost that remains: the page does not know a suspension or deletion of the namespace owner, in which the hub reads `members` while the sentence says `anyone`.

## Two-factor sign-in sits on the account; a session that must enrol gets the setup as its one page

**Id:** ed407146-2c2b-4686-87ef-a5d8e6d020e2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.1, §2.8.5, §2.8.7; the card tsk-94jtz06aps4b; #1004
**Revisit when:** mail as a factor gets a section of its own

A session in `enrolment_required` gets the setup drawn by `render()` like the second-factor step, not routed, so the address asked for stays, often `/`. The secret and the recovery codes live only in the DOM of the step that shows them and go with it; the codes leave the page only by the human's **Download**. Setup, new codes and **Turn off** go through `M.stepUp.run`, as the hub asks for the password or the factor and the page repeats the call.

**Rejected alternative:** a route of its own for the setup: a session in enrolment reaches nothing else, so the page must be the same either way. Keeping the codes until the next visit: §2.8.1 shows them once.

## The enrolment page is guarded only while it is on the page

**Id:** 056d57c5-e0d5-4fc1-83d1-d4042c55dab8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.5; review of #1004; tsk-xtnxws153a7x

A refusal `second_factor_enrolment_required` draws the setup through `render()`; a flag stops a late refusal from drawing it over itself, which would throw away the secret being typed. `render()` clears the flag and only `renderEnrolment` sets it for good, so it says "the setup is on the page". The first form, cleared only when the setup succeeded, left a tab that signed out, or whose hub let go of the requirement, deaf to the next refusal.

**Rejected alternative:** tying the flag to the session epoch: a hub that releases the same session keeps the epoch, and the tab stays deaf.

## The reset form stays open and names no enrolment state

**Id:** a5c7675b-8785-4a40-b088-b0a0022818c5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.3, §2.8.7; tsk-xtnxws153a7x

Admin → Users offers **Reset two-factor sign-in** on every row but one's own, and the hub's `409 conflict` says when the person has no factor: `GET /admin/users` does not carry whether someone enrolled. The form is one under the list, not one per row, and stays through a search, so the warning to confirm by another channel is read beside the reason, not skimmed in a table cell.

**Rejected alternative:** a confirm dialog: it has no room for the reason and the warning, and a modal is the wrong place for a text someone has to think about.

## Availability and cover hang under the presence as one note

**Id:** a242b4f7-0f84-459e-bb59-84934ed93cd3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.12; #980

On Members, the Agents tab and a member's page, availability and cover
hang under the presence as one note: away until when and why (the hub
already drops a human's reason outside `show_reason_in`), resting when
every instance is dormant, who covers this member and whom it covers.
`available`, `offline` and `paused` get no note: presence and the paused
pill already say them.

**Rejected alternative:** a column of its own on Members: it would be
empty in nearly every row and does not fit the narrow layout.

## The join panel reads all of a human's profiles and offers only those a project is allowed for

**Id:** de22411f-43b5-4a4e-b21f-eb1b03b61fdb
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.3; the card tsk-4sm441es9nwe

The join panel asks `GET /agents` and `GET /agents?allowed_in=` and offers the second list. A handle is taken among all of a human's profiles, whichever projects they may join, so the handle check keeps reading the first.

**Rejected alternative:** only `?allowed_in=` as the contract's sentence reads: the check would then call the handle of a profile not offered free, and the hub would refuse it after the form was filled in.

**Add to a project** on Your agents compares the list in the page, with a project's full name and its aliases: the page does not know the owner's old handles, so a project allowed under one is missing there and stays offered in that project's own join panel. An `?allowed_in=` read per project was rejected: one request per project for a rare case, on a page that lists them all.

## Add and Join are two buttons, the same on a project's Agents and on /agents, each opening its form

**Id:** 1ac94340-cc4e-4d87-9ec0-c26fbdf57e96
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer on the card tsk-mzaf9w83emn6, 2026-11-01; the split of the two words proposed on the card and accepted by the coordinator
**Revisit when:** a member's limit needs its own wording on the button, or profiles and joins merge into one form
**See:** views.md#ones-agents-have-a-page-of-their-own-in-the-gear-menu-adding-one-to-a-project-is-that-projects-join-panel — 1031c11b-7642-4ed9-87ce-de504b2044fc — as of 2026-11-01

Both pages have **+ Add an agent** and **Join an agent** at their head, and
a click opens the matching form, one at a time. Add makes a new profile. Join
is the join panel, for this project on a project's Agents, with a project to
choose on `/agents`. The section that stood open on `/agents` and the form
under its list are gone. This narrows the earlier use of "add" for the join
flow (1031c11b): on these two buttons add means a profile. A profile made on
a project's Agents goes straight on to the join panel, chosen there, since
it is in no project yet and would not show in that project's list.

The join panel still opens at once in three cases: `/<owner>/<slug>/agents/join`,
`/agents?project=`, and a project without an agent of one's own. A member
without `members:admin` sees the same **Join an agent** instead of **+ Add my
agent**; the limit beside it is unchanged.

Members' **Join an agent** leads to the project's Agents with the panel open,
no longer to `/agents`, and **All projects** has an **Agents** tab to `/agents`
(tsk-8sdgr8fbrn5v), which keeps its tabs on that page.

**Reason:** the maintainer wants the two pages as alike as possible, with the
forms folded until asked for. Add already opened the join panel on the
project's page, so a separate Join there needed Add to mean something else.

**Rejected alternatives:**
- Two buttons that both open the join panel on the project's page: the same
  action twice.
- Leaving the join section open on `/agents`: the maintainer asked for the form
  to open on the click.

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

## A membership's links stand only where they open

**Id:** b805d135-78b3-47b7-b293-1d42fe4fc04c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-svqsdp6qf0f3; reviews of #1020

On a profile, the project and rulebook links stand only where the human is a member, and Join link also needs a project that takes the agent. `member_agents` is not in `GET /me`, so a member can still follow Join link into a project with it `off`; the project's page then says there is no form.

**Rejected alternatives:** always linking, which ends on a 404 or in silence; reading the policy per project on `/agents`, too many reads for one link.

**Known limit:** a click on Join link at the same address does nothing, as `M.route.go` ignores that.

## Jour fixe and Why across projects: one read per project

**Id:** c095fb26-7aa5-4529-a42a-08896de2d032
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's cards tsk-qnsmjbpdkm1t and tsk-jpe6vzyq39mg, which name reading per project as the way without a read across projects and forbid widening who sees what; the coordinator's agreement, 2026-11-01; docs/api.md §11.3, §20.9
**Revisit when:** the hub gets a read across projects for either, a reader's projects make the reads slow, or the contract lists rounds for an agent's owner outside the project

`/all/jour-fixe` and `/all/why` read `GET …/jour-fixe` and
`GET …/keep-the-why` once for each project in the reader's list. Each
section fills when its own answer comes, and a failure stays in its section.
The Why page never sends `max_age=0`: it takes the hub's cache. Both paths
are under `/all`, a word already reserved (§16.11).

**Reason:** the hub filters each answer by that project's rules, so nothing
becomes visible that the project page does not show. Two limits are known:
N requests per view, and an owner outside a project whose agent takes part in
a round (§20.7) sees that round nowhere here, since no listing is open to them.

A series without a topic, an owner's series an admin may not read (§20.1), is
"A private series." here, never its ID. The project page also names the owner;
this page reads no member list, so `handle` would print the raw member ID.

**Rejected alternatives:**
- Falling back to the series ID, or naming the owner by that raw member ID: an
  ID is no name.
- A new `GET /me/jour-fixe` or a read across projects for Why: a contract
  change the current number of projects does not need.
- First-level `/jour-fixe` and `/why`: each would reserve another word that
  handles may no longer take.
- Waiting for every project before drawing: the slowest export would hold up
  the page.


## Memory is a view of its own, and holds the role memory

**Id:** 476c7232-ef6b-431b-8d28-7726d5860a64
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.11, §19; the maintainer's chat seq 6883; tsk-6tqytgmcp17p; supersedes the section on Settings → Mine of #1026

`/<owner>/<slug>/memory` is one tab for team, role and community memory, and the role memory moved there from Settings → Mine within the day it landed, so that there is one place. A slug `memory` is now reserved as every view's name is. Souls stand on the same page, for their owner only, read when opened; delete offers a reason in the row, not a browser dialog, because the reason is shown afterwards.

The tab row's room on a phone, the argument of f9ef2098, was outweighed by one place for one store; a tab was accepted at that price.

**Rejected alternatives:** keeping the role section on Mine beside the view: two places for one store. Three separate views: the reader asks what was written, not in which store.

## The landing editor keeps its own copy of the hub's list of agents, and smoke compares the two

**Id:** dc4639b9-91bf-464e-8592-4009f935e46d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.7 (the agents a `works_with` section names are a fixed list in the hub's code); the card tsk-6wch92201m39; why a copy over a call is this entry's reading
**Revisit when:** the hub serves the list, or a second place in the dashboard needs it

The editor offers the agents of a **Works with** section from a list in
`js/landing.js`, the slugs and names of `AGENTS` in
`hub/src/maity_hub/landing.py`, in the same order. The check before a save
has the slugs as `LANDING_AGENTS` in `js/api.js`. `tools/smoke.js` reads the
hub's file and fails when either copy differs from it.

**Reason:** the contract serves no such list, and adding an agent is a change
in the code anyway, so a comparison catches a drift when it is made.

**Rejected alternatives:**
- An endpoint for the list: a contract change for one picker.
- A free text field for the slugs: every typing mistake would come back as the hub's refusal.

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

## The public page's form appears for the namespace owner, and its link cannot know the instance's switch

**Id:** 7e873b54-6e5d-45de-b8e3-4db3621e7588
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.9, §6.26; tsk-0vccw54gj8e6
**Revisit when:** the project view carries `page_served`, as `GET /people/{handle}` does

The project's Settings show **Public page** only to the human who owns the namespace, or to an owner of the organisation that does (`GET /orgs/{handle}`, `my_role`); a slot fills when that answer comes. The account page shows **Public profile** to every human. Both say what becomes public before the switch. The project's **View public page** link shows while `public_page` is `on`, the project is not archived and it has no hold, with a note that the hub's operator must have public pages on. The profile's link follows the hub's `page_served`.

**Reason:** a project admin who is not the namespace owner would only get a refusal from the hub, because the page is published under the owner's name. The project view has no `page_served` and `MAITY_PUBLIC_PAGES` is not readable from it, so the page cannot tell whether the instance serves pages; the note says so instead of implying more.

**Rejected alternatives:** a hub field `page_served` on the project in this PR: a launch blocker should not wait for a contract change, and the card asks for the web. Fetching `?as=public` and telling the stored page from the app shell: guessing from HTML.

The profile links' form is `novalidate`: a browser's bubble on one bad address would stop the whole save, and the hub's refusals are said in words at their fields.

## A proxy's action request shows the body twice: pretty-printed, and exactly as sent

**Id:** 77f97db2-6696-4d9f-8c74-8e65065f7fdb
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("rendered on the request"), §7 `action`; the hub's #1030; tsk-tx9qcehevfnk

The inbox entry lists the method, path and query and the pretty-printed body, and under **Exactly as sent** the stored text with its SHA-256. Inside a project someone who is not the owner sees the call and no buttons, with a sentence saying who answers. Across projects the trust is not known, so the buttons stay and the hub's `action_needs_owner` is what they hear.

**Reason:** the owner is approving the exact bytes the hub later compares. `JSON.parse` keeps only the last of a repeated key and rounds large numbers, so a pretty-printed body alone could show something other than what the go allows; a proxy is the one writing that text.

A body whose parsed form differs from its text (compared without the white space between tokens) opens **Exactly as sent** and says so; an escape or a moved key counts too, so a harmless difference can warn. A C0 character written as a JSON escape raises only that difference, not the warning about hidden characters, as the pretty-printed text writes it back as an escape; a literal `[U+202E]` in the text differs from the mark only by the mark's formatting. Control, format and separator characters, the default-ignorable ones and the blank braille cell (bidi overrides, zero-width characters, no-break spaces, fillers among them) appear as a marked `[U+XXXX]` in the method, path, query and both bodies, with a sentence above them, also when the body carries them as a JSON escape. Not `\uXXXX`: a body can hold those six plain characters, with another SHA-256. Someone who is not the owner keeps **Later**, which touches nothing at the hub, and loses **Talk**, which the hub refuses them too. Look-alike letters are not marked: they are visible characters.

**Rejected alternatives:** the raw text only: hard to read, and the contract asks for pretty-printing. A sentence only under Exactly as sent, closed by default: the owner reads the open form first. An allow-list of printable ASCII for what counts as visible: a path or a body may carry real non-ASCII text the owner must read as it is. Refusing to show a body whose parsed form differs: the hub stores it as valid JSON, and the owner can say No.

## Role memory is a part of Mine, not a view

**Id:** f9ef2098-cadd-452c-ac4e-5945baa145d4
**Type:** decision
**Status:** superseded
**Superseded by:** 476c7232-ef6b-431b-8d28-7726d5860a64
**Evidence:** inferred
**Source:** docs/api.md §16.11, §19.2; tsk-hx8cbm2eqg45

The role memory is a section on Settings → Mine, the one page every human member reaches in a project, with a role picker for trust owner and admin. No new address: §16.11 names Settings as one view with two tabs, and a view of its own would be a contract change for a list of a few entries.

**Rejected alternative:** a third Settings tab or a project tab: both need §16.11 changed, and a tab row is already short of room on a phone.

## Admin → Sign-in keeps the question for the mailed code open, and names no value it cannot take

**Id:** 7c2e5a14-9b3d-4f60-8a71-2d6e0b94c3f8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.6, §2.8.7, §2.8.8; `hub/src/maity_hub/auth/sign_in_settings.py`; PR #996's second part

The section (`js/admin-sign-in.js`) lists the sign-in methods with each value's source. **Mail for everyone** is in the list only while `missing` names neither `mail` nor `signing_key`, or while it is the current value, as the list would otherwise lie. Choosing it says that a code is mailed first and advises the admins to set up an authenticator app. The `PATCH` answers 202 and has changed that value only after the code: the form gives way to one question for the code with **Send again** (a new `PATCH`, which replaces the open confirmation) and **Leave it as it is**, which sends nothing, as nothing has changed and the code runs out. Other values changed in the same form are saved with the 202.

**Reason:** the contract makes the code the proof that a mail of this hub arrived, so the page must not read as saved before it. The refusals `mail_not_ready` and `no_verified_address` can still come, as the state may change after the page was read; they are said at the field.

**Rejected alternatives:** offering the value always and relying on the refusal: the contract says it is offered only while mail is ready. A cancelling `PATCH` on leaving: it would need a value to write back and a step-up for a change that never happened. Reading the settings again before showing the question: if that read failed, the mailed code would have no field.

## The words of sign-in and sign-up are instance content; the forms stay the dashboard's

**Id:** 133731df-a4ac-453d-923a-5df0878e69f0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on tsk-fct4awzw3k30 and decision req-885kx86hhab4 on tsk-ya56x9gx986r, 2026-11-01; the plan the coordinator approved; docs/api.md §16.7.4

The site file gives `/login` and `/register` their pitch per language: title, subline, three points and a note. Every word of the forms comes from the dashboard's catalogue, which is translated with the rest of the portal, and the catalogue also supplies a key left out or a failed read. The hub chooses the file's language as for the landing page.

**Reason:** `next`, the device code's polling, the second factor and a session that ends under a page all live in the dashboard, so a second renderer would be a second sign-in path. No sign-in may depend on reading words.

**Rejected alternatives:** the dashboard taking its own language from `GET /auth/pages`: that answer picks among the languages the file has, so a form could change language with the instance's content; the dashboard draws in its own language and passes it as `lang`. A missing key filled from `default_language`: the answer would mix two languages under one `language`; the catalogue fills it, in the language the dashboard draws in. Form labels and buttons in the file too, with the file winning over the catalogue: two sources for one text, and an imported file would pin a form's words against later catalogue changes. The hub rendering the two pages as it does the landing page: a second path, above. Free HTML or sections from the file: the forms are a security surface. A format `maity-site/2`: it would invalidate files in use, and a part left out already stays as it is. Words in the `registration` part: those are settings, with their own environment rules. A table of its own with versions: unlike legal texts nothing needs to be proven later, so one setting row is enough.

## The sign-in and sign-up sub-tabs share one editor, and Save sends both pages

**Id:** 42fcba86-1e4e-43dd-b028-62de42cd1258
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** PR #1136 (tsk-fct4awzw3k30); docs/api.md §16.7.4: a `PATCH` of `/admin/settings/auth-pages` replaces the setting as a whole

`js/auth-pages.js` reads the setting once per admin page and both sub-tabs draw from one draft, so Save in either sends both pages. An empty field and a language without text are left out. JSON for one page is checked with `/check` (no second factor) before it reaches the editor, and only Save stores it. In the site file the two parts become one `PATCH`, at the first changed part; a part the file leaves out is sent as saved.

**Reason:** the hub has one row and no partial update. Two editors, each with its own read, would let a save in one tab overwrite what the other just saved.

**Rejected alternatives:** a `PATCH` per page: the contract has none, and the second would overwrite the first. Sending empty strings: the hub refuses them as `invalid`.

**Known limit:** like the landing editor, the draft is read when the Pages tab opens. After importing the whole site file in the same view, reload before saving in a sub-tab.

## Going from chat to chat in the global chat changes the pane alone

**Id:** ced4e992-460a-4cde-844f-4f558c832ae7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** a tester's report that switching chats is painfully slow (tsk-cdc3m5g1ew81), measured in Chromium against a local hub, 2026-11-02
**Revisit when:** a project's own Chat tab gets the same treatment, or the hub offers one read for a chat's head and newest page

A click on a chat in `/chats` no longer runs the page's `render()`. The
view registers `ctx.followRoute`, and the pane is drawn into a detached
holder and put in place once it is ready. Meanwhile the list already
marks the new chat and the pane being left stands dimmed and inert. Direct chats take
their unread count, newest message and one's own participant entry from the list as last read; what
came since is the forward read's, and a chat left before that read starts is not marked read by it. The list is read again after the pane
is drawn, and nothing waits for it. A project or chat not in the list as last read,
or a failed read, still draws the page anew, which reads it or says what is wrong.
A chat's timers and listeners are the pane's own, ended when it is left.

**Reason:** every click cost 16 requests, 13 of them in 10 steps one after
the other before the messages were drawn, with the old chat frozen and no sign of loading: 1.8 s at
150 ms of latency, against 0.33 s at none, with no long task in drawing. So the waits in sequence
were the cost, not the hub or the drawing. The pane alone takes three
steps: about 0.55 s at the same latency.

**Rejected alternatives:** making the steps of `render()` parallel: session
and `/me` decide what may be drawn, so the steps stay, and the frozen view with them.
A loading line in place of the pane being left: at these times it only flickers, and on a phone
the list stays until the chat can replace it.

**Known limit:** member lists are read every 30 seconds rather than on each click, so a
new member's name can lag that long. A project's own Chat tab still draws the whole page.

## The mail address asks for the password beside it, optional, and the hub decides

**Id:** 1f725886-4f1f-47a3-b1cd-a74bf82aedb2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4 "Changing a verified address" and §2.6.3, the web mail section of tsk-x9g29m2rcx72, 2026-11-02
**Revisit when:** the session or `GET /me` says whether the human has a password

The mail address sits on `/account/notifications`, only where `mail_available` is true;
the personal language above it stays either way. Changing or removing a confirmed address
shows a password field marked "if you have one", and `current_password` is sent only when
something was typed. The hub's `current_password: "required"` or `"mismatch"` is said at
that field. A change the hub holds (`202`, `address_change` naming the address just sent)
is said as waiting, with a link to the sessions on the same page, where it is approved or
rejected; an older held change shown there is not taken for this one.

**Reason:** the dashboard cannot tell whether a human has a password: neither the session
nor `/me` says so, and §18.4 treats the two cases differently (password in the request, or
the age of the session). An optional field covers both, and the hub's answer tells which
case it was.

**Rejected alternatives:** a field in `/auth/session` saying whether a password is set: a
contract change for one hint, and it would tell any script in the page something about the
account's sign-in. Asking for the password always: a human who never set one could not
change the address at all. Never asking and waiting for the refusal: one failed request
on every change of a confirmed address.

## When mail goes out: the page sends only what changed, the browser's zone only offered

**Id:** 444115c8-aaaf-408e-a16c-571aa48f69cf
**Type:** decision
**Status:** superseded
**Superseded by:** 44009d6f-ff99-4f8a-b51e-cb9531702422
**Evidence:** inferred
**Source:** docs/api.md §18.4 "Defaults and what was saved", the web mail section of tsk-x9g29m2rcx72 (#1223), 2026-11-02
**Revisit when:** the hub can reset a kind to its default

The modes and times on `/account/notifications` are compared with the hub's merged answer, and
the `PATCH` names only what differs: in `email.kinds` only the kinds that changed, each with only
its changed part (`mode` or `content`). The time zone is the account's. When the browser reports
another one, a button offers it, but the page never sets it unasked.

**Reason:** the hub stores only what the human set, and a kind it was sent counts as set even if
the value is unchanged. Sending the whole form would pin every kind at today's default, and a
later change of the default (as the digest defaults of 2026-11-02) would no longer reach them. The
zone decides when digests and quiet hours fall; a browser on a trip should not move them.

**Rejected alternatives:** sending the whole `email` object on each save: it pins every default.
Setting the browser's zone when the account still has `UTC`: a person who chose UTC on purpose
would see it changed.

**Known limit:** a mode changed and later set back to the default stays set; the contract has no
reset.

## When mail goes out: the page sends only what changed; the time zone is set under Settings, the browser's only offered

**Id:** 44009d6f-ff99-4f8a-b51e-cb9531702422
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4; the web mail section of tsk-x9g29m2rcx72 (#1223), 2026-11-02; the owner's decision on the account time zone (message seq 94723) and the approved plan on card tsk-j8s6n725a06r, 2026-11-08
**See:** views.md#when-mail-goes-out-the-page-sends-only-what-changed-the-browsers-zone-only-offered — 444115c8-aaaf-408e-a16c-571aa48f69cf — as of 2026-11-08
**Revisit when:** the hub can reset a kind to its default

The modes and times on `/account/notifications` are compared with the hub's merged answer, and
the `PATCH` names only what differs: in `email.kinds` only the kinds that changed, each with only
its changed part (`mode` or `content`). The time zone is no longer a field there: it is the
account's, chosen in Account → Settings, and the mail page names it with a link there, or says
the mails follow UTC while none is set. In Settings the browser's zone is offered first, as a
button and at the top of the list, but the page never sets it unasked.

**Reason:** the hub stores only what the human set, and a kind it was sent counts as set even if
the value is unchanged; sending the whole form would pin every kind at today's default (unchanged
from the earlier entry). The zone now decides every time the dashboard shows as well as when
digests and quiet hours fall, so it belongs with the language under Settings, not under mail
(the owner's decision, confirmed); a browser on a trip should still not move it.

**Rejected alternatives:** sending the whole `email` object on each save: it pins every default.
Setting the browser's zone while the account has none: the dashboard already shows times in it
then, and storing it would turn a guess into a choice the human never made. Keeping a second zone
field on the mail page: two places for one value.

**Known limit:** a mode changed and later set back to the default stays set; the contract has no
reset.

## The frame's stylesheets are switched on only where the sign-in or registration stands signed out, its header and footer beside the app's

**Id:** e9ddc07e-71c0-47c7-bd12-6a7e4d2c35f0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-74rvy49kbv6s and the designer's approved draft (`public-pages.css`, 2026-11-02); the agreement with the hub's side that the dashboard links the hub's two stylesheets rather than copying them (2026-11-02); `web/js/site-chrome.js`, 2026-11-03; lotse#wtwy's decision on #1287 (message seq 65368, 2026-11-03)
**See:** https://github.com/oliver-zehentleitner/maity — 41837936-d085-4592-88d7-b1708a8b4b3a — as of 2026-11-03
**Revisit when:** `landing.css` scopes its rules to the frame, or the dashboard gets a second page in the frame (the form pages of mail links)

Signed out, the sign-in and `/register` draw their form into gj6k's door layout, then ask
`GET /site/chrome` with the address's `?lang=` (or the last one this page saw, `M.i18n.frameAddress`),
and take the frame's language from its answer. While the page stands, the hub's
`/assets/landing/landing.css` and `public-pages.css` are linked (without `?v`, so the hub answers
the current file with an ETag), and `html` carries `public-frame`. The frame's header and footer
are elements of their own beside `#header` and `#main`, built from the model as the hub's
`render.py` builds them; the app's bar is hidden meanwhile and comes back where the read fails.
The sign-in stands in the frame wherever it is drawn without a session: `/login`, the root after a
sign-out, an address of the app opened without a session and without a stored public page, and
the sign-in drawn when a session ends. While no session is known, `render()` keeps a frame that
stands, so a page drawn again (another language, the same address) does not lose it in between.
Every view that is not the sign-in takes it down itself: the invitation, the mail's second step
without a session, a public page once it is drawn, the maintenance page, a failed page, and every
drawing once a session is known. The scope is confirmed: lotse#wtwy decided it on 2026-11-03 (on
#1287, after the review found the frame at those addresses). It was chosen over drawing the
frame at `/login` and `/register` alone; why it lost is inferred, not stated: that choice would show
the same form in two designs depending on the address.

**Reason:** `landing.css` sets `:root`'s tokens, `body`, headings and links for the whole
document, so it may not stay on under the app. Once a session is known, `render()` takes the
frame down in one place before any view draws; without one, it stays standing while the view is
decided, and each view that is not the sign-in or registration leaves it itself. The app's `#header` rules (sticky, its own
background and padding) would beat `.site-header` by specificity, so the frame does not reuse
that element.

**Rejected alternatives:** copying the landing's rules into `app.css`, scoped to the frame: a
second copy of the design that drifts from the hub's, which the agreement ruled out. Drawing the
frame's header into `#header`: the specificity fight above, and an override per rule. Watching
`#main` with a MutationObserver and leaving the frame when its page is gone: it needs no rule in
`render()`, but the smoke test's DOM has no observer, so it would ship untested. Waiting with the
form until the frame is read: sign-in may never depend on that call (§16.7.4).

The frame's footer stands in place of the dashboard's product line (§16.13). `render()` hands
its wish to `M.siteChrome.line()`. A drawing without a known session holds the line back, and so does every read `enter()` starts, also one a page starts without `render()` (the
login's language picker), until that read decides. The line stays away while a frame stands. It comes back only
where the frame is left (`leave()`) or not drawn (a failed read, a model without header or
footer, which both run `drop()`). The choice itself is confirmed: the maintainer's decision
req-5k1gvfsmcg9k (2026-11-03), against keeping the product line under the landing footer. His
reason is not recorded. Inferred: two footers on one page would both name the product.
**Rejected:** showing the line in `render()` and hiding it in `enter()` once the read answers. That
showed it under the landing footer for one round trip on every drawing in the frame, and under the
form on the way in (#1287 review, `b5142212`). Also rejected: a route check in `product-line.js`,
which does not know whether the frame stands or its read failed.
**Known gap:** `M.api.get` has no timeout. A `GET /site/chrome` that never answers leaves the
page without the frame and without the line, as §16.13 says for a read that waits. A timeout was
not added: it would put a second clock beside the API's own error handling, and a hub that does
not answer leaves the sign-in itself unusable anyway (review of #1287 by
maity-review-team-grok#dzse).
**Known gap:** a session that ended on the hub without the page being told (signed out in
another tab, expired) stays in `M.api.session()`. A 401 on `GET /auth/session` is a public call
and does not clear it (`js/api.js`; only `endSession` does), so `render()` takes the frame down
and lets the product line go on each such drawing: the app's bar and the line show for one round
trip of `/auth/session` before the sign-in enters the frame again. The stale session itself is
older than #1287 (`js/api.js` answered that 401 the same way before it); the flash is #1287's,
since only #1287 leaves the frame and holds the line by the session. Found in the review of #1287
by maity-review-team-grok#spq4. Recording it rather
than clearing the session on that 401 here was lotse#wtwy's decision (message seq 66307,
2026-11-04); the reason is inferred, not stated: the case is rare, the page recovers after one
round trip, and a change to the session's lifetime belongs in a change of its own. Workaround:
reload the page, or sign out and in again.

The frame's mark (`home()` in `js/site-chrome.js`) is the hub's SVG without its style attributes;
it keeps the class `mark`, and its colours come from `public-pages.css` (`.site-header .mark
rect`, …), because the dashboard's policy is `default-src 'self'` with no inline style. **Rejected:** the
style attributes as the hub inlines them (web-e2e failed on them at `cc402ec1`), classes in
`app.css` (a second copy of the hub's design, reverted in `7b63d015`), and an `<img>` (it cannot
take the header's theme tokens). Source: the author's notes on #1287, round 2 (card
tsk-gsk31zvpfv02).

The footer's languages (`language()`) are this page's own path and query with `lang` set,
written through `M.route.href`, and a click chooses the language (as the page's picker does) and
draws the page again at that address. **Rejected:** a bare `?lang=`, which under the shell's
`<base href="/assets/">` resolves to `/assets/` (a 404) and loses a sign-in's `next`; a page load
to `/?lang=`, which leaves the sign-in. Source: the same notes on #1287.

Under 960 px, a pitch panel that has none of the pitch's parts (subline, points, note) is hidden
(`hub/src/maity_hub/landing_assets/public-pages.css`, the narrow-screen rule), so a phone gets no
empty dark band. Every key of §16.7.4 is optional, so a panel with only a note or only points
stays. The title is the form's heading, not a part of the panel. A new part that `pitch()` draws
must be added to that rule. **Rejected:** hiding on subline and points only (it hid a note-only
pitch, the ChatGPT reviewer's P2 on #1287); a class set by the script (a second source of truth);
keeping the empty band. **Known gap:** the smoke case renders only a note-only panel, so dropping
one of the rule's `:has()` parts, or a new part not named in it, stays green. Source: the author's
notes on #1287, round 3 (card tsk-gsk31zvpfv02).

## A consent line names who is asked and calls saved only what the member, read again, already has

**Id:** 71dc43d7-fef5-4123-83de-841dcc06c2bd
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-0dhk4wdt111m (the owner set another owner's agent to `red-team` and the form showed `coder` again; events 64676 and 64711); the lead's decision on the card; docs/api.md §6.2 ("Another owner's agent"); hub/src/maity_hub/foreign_agent.py, cross_owner.py; web/js/members.js `consentWords`; the review of #1312
**Revisit when:** the hub's 202 says which fields it applied and whose consent each request waits for, or a member shows its open consent request

A `PATCH` of another owner's agent answers 202 with one consent request
while part of the change may already have applied: the hub takes a
`reports_to` to a boss of the agent's own owner, or none, at once, and
holds trust, role, areas and capabilities for the owner's go. The 202 names
the asked human as `human:<id>` and says nothing of what applied. So the
members view reads the member again after the call and calls saved only the
fields it now has ("Saved: reports to. The rest is not changed yet: …"), and
names the asked human by name where they are a member here, otherwise as the
agent's owner (its `owner_id`) or, when the answered request is another
human's, as a boss's owner. In a `PATCH` that also changes a held field the
hub files that field consent, which goes to the agent's owner, first and
answers with it; only a `reports_to` to a boss of another owner on its own
is answered with an edge request, the boss's side unless the caller is that
human, then the agent owner's (hub/src/maity_hub/routes/members.py,
cross_owner.py).

**Reason:** the hub's answer is the request alone; without reading the
member again the line either claimed nothing changed while the boss had, or
claimed a save the hub had not made. The raw `human:hum-…` was what the
owner read on 2026-11-03.

**Rejected alternatives:** showing the hub's `to` as it comes (the raw
address); keeping "Not changed yet" for the whole change; assuming that
`reports_to` always applies at once (a boss of another owner waits too).

**Known limit:** where several requests are filed (fields and a cross-owner
edge, or an edge both of whose owners are asked), the line names only the one
the hub answers with.

## The project's Why view mounts the Keep the Why views, loaded on the first visit; their own words stay English for now

**Id:** 9e70b2ab-5fbf-44ad-9d4e-7e1b54319519
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-9kns2as984et (KTW M3), 2026-11-03: the proposal on the card and the lead's ruling on its two open points (the library's language, loading)
**See:** stack.md#the-keep-the-why-views-are-vendored-from-the-pinned-pypi-wheel-by-their-manifest-and-hashes-not-taken-as-a-package-dependency — f3b6fe34-f86e-490c-afe6-f03ee3263ab3 — as of 2026-11-03
**Revisit when:** the Keep the Why library takes its UI words from its host (a words hook), or a second view needs the library

The project's Why tab is Keep the Why's own dashboard views, mounted by `js/ktw-host.js` from the vendored library: the overview, graph, timeline, thoughts, family, topics, entries and search, at paths below `/<owner>/<slug>/why`. The library reads through a provider over the hub's §11.5 reads, moves through the dashboard's paths (`js/route.js`), keeps its settings in the browser and takes Maity's colours through its `--ktw-*` tokens. Its scripts and stylesheet are loaded on the first visit to Why, in the manifest's order (checked by `make check`), and stay for the page's life. Its own UI words are English and the mounts carry `translate="no"`: an interim step until the library takes words from its host; entry text is the repository's data either way. The digest view the tab showed before (the hub's §11.3 summary per member) remains on All projects → Why. What the old view did for a failed read stays: when the hub cannot read the export, its last good read is shown with the reason, and Read again drops what the page holds and reads anew. A link from data is used only when plain https, as for every link from data (rendering.md), in two places: the export's link fields (the project's and the config's canonical, dashboard-state, a git remote and the repository it forks, a See or superseded_by into another repository) are checked before the library sees them, and every `href` the library writes into the mounts, entry text included, is checked again as `dom.h` checks Maity's own (a path of the dashboard or plain https); a `ref` place reads nothing for a repository in the address that is not plain https. Since 0.11.44 the library writes a route's `centre` as `centre/public/<canonical>/<root>/<place>`; the host's router drops an empty path segment, so it never reads a repository's root back from that form with certainty. An entry at another repository of the family is therefore written by the host as its own place `at/<uuid>/<canonical>[/<root>]`, which reads that repository's export (at that root) through the family and draws the entry with the library's pages over a scene of that export; `routeOf` also takes the library's `centre/public/…` form when a link arrives from elsewhere (a segment after the canonical is the root unless it names a place of the library's grammar, so a root named like a place, `graph` say, reads as that place: a known limit of links from elsewhere, never of `at/`), and any other place at another repository is the family page. A `ref` place the library resolves goes on to that place, replacing the ref in the history. The repository in the address must be plain https and the root a relative directory, or nothing is read.

Since keep-the-why-dashboard 0.11.44 the library takes contrast tokens: text on its accent is `--ktw-on-accent` over `--ktw-accent-fill`, and accent-coloured text (links, counts, the type pill) is `--ktw-accent-text`. `css/app.css` maps the first pair to Maity's own `--accent-text` on `--accent` (5.32 to 1 light, 6.0 to 1 dark) and drops the eight overrides that wrote `--accent-text` over the library's literal `#fff`; they were a workaround until such a token existed. `--ktw-accent-text` is not `--accent` itself but `--accent` a fifth of the way to `--text`, as `--ktw-warn` already is: plain `--accent` is 4.11 to 1 light and 3.98 to 1 dark on the type pill's 18% accent tint, under AA, while the mix is 4.84 to 1 at least on `--bg`, `--surface` and that tint over either, in both themes. Mapping `--ktw-accent-text` to Maity's `--accent-text` was rejected: in Maity that name is the text *on* the accent (white in light, near-black in dark), not accent-coloured text, so links would turn white or black. `--ktw-status-active-text` is `--ok`, as `--ktw-status-active` is. Since 0.11.45 each of the library's state colours has a `-text` twin for its words (`--ktw-ok-text`, `--ktw-warn-text`, `--ktw-status-open-text` and eight more); the colour keeps drawing borders, dots and the graph. Upstream draws those words on the pills' solid `--ktw-surface2`, and on the surface and the page, never on a tint, so `css/app.css` maps them to Maity's text-on-plain-ground values: the state colour itself where it passes there (`--ok`, `--bad`, `--muted`), else the colour a fifth of the way to `--text` (`--ktw-warn`, `--ktw-accent-text`, `--ktw-accent2`). Plain `--accent` was rejected for the open and info text: it is 4.53 to 1 on dark `--surface-2`, too close to the line. The lowest pair is `--ok` on light `--surface-2`, 5.00 to 1. `--ktw-fg3-line`, the library's faint lines and marks, is `--muted` like `--ktw-fg3`, so nothing shifts; `--seat` was rejected, at 2.5 to 1 it is under the 3 to 1 a mark needs. Likewise, controls the library labels only by `title` (the timeline's playhead and speed) get an `aria-label` from that title in the host, where `sweep` holds its links, and a later title refreshes the name the host set, while a name the page sets afterwards is kept when it differs from the host's (one equal to it cannot be told from the host's and follows the title); dropping axe's `label-title-only` rule for the mounts was rejected, as it would hide the next unlabelled control too.

**Known limits:** what the page has read of a project stays for the page's life, per project and per signed-in reader; a newer export shows after Read again or a reload. The library's own words are English until it takes them from its host. A link in the library's `centre/public/…` form to a repository whose root is named like a place of the library's grammar reads as that place.

**Reason:** one update of Keep the Why reaches Maity unchanged, so the project's decision record looks and behaves as in its own dashboard; Maity adds only the host (provider, paths, settings, colours). Loading on the first visit keeps about 350 KB of scripts off every other page. Marking the library's words `translate="no"` keeps the pseudo-locale check strict for Maity's own words without pretending Maity translates text it does not hold.

**Rejected alternatives:** the library in `index.html` for every page: its weight on pages that never show it. Its ~200 words copied into Maity's catalog: a second copy that drifts from the library's on every release; the words hook in Keep the Why is the lasting answer. Keeping the digest view and the library side by side in the tab: two answers to one question, the digest the poorer one. Checking only the export's fields, or only what the library writes: the fields keep a bad link from shaping what the library builds from it, the check of the mounts covers links in entry text and any field a later library adds. An elsewhere view of Maity's own for a `centre`: a second rendering of an entry the library's pages already draw. A centred entry as its `ref` place: the library's `ref` resolves the entry and goes to it at that centre, which was the same address again, so the page never left "Looking for …"; and a child root had no place in it.

## The organisation's Paths face draws only edges the members API gives; an event's usual edges are marked as usual

**Id:** 04ce10bd-5160-46e3-bb6d-7c3f760f4167
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-j9ktmj7e4fxq, 2026-11-05: the lead's answer to the request on the card (req-x3hgj0b7xzy3), choosing the members API as the only source and usual edges marked as such; the designer's approved draft for the layout
**See:** views.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-11-05
**Revisit when:** the hub names an event's recipients itself (a routing read), or a team's lead has more than one role group too wide for the canvas

The Team page's Organisation tab has two faces, Tree and Paths, the choice kept per browser. Paths (`js/paths.js`) draws the team top-down from `reports_to`, humans first, a lead centred over its members, and more than six members of one role under one lead folded into one box that opens in place. The reporting lines are a chip of their own, on by default; four more chips draw where one event goes, from the routing of docs/api.md §8.2 and §8.4: a review result to the reviewer's lead, not listening to the agent's lead, the admins and the owner (never a meat proxy), a request to a human to the agent's owner, and a card assignment from a lead to the member and the member's owner. Every edge is computed from what `GET /members` returns. Where the hub's routing depends on something the members list does not carry (who assigned the card, who wrote the reviewed PR), the edge is drawn as usual, dotted and named "usual" in the legend, or only said in the chip's note. At phone width the drawing gives way to a list of cards, each naming whom the member reports to and what it gets.

**Reason:** a picture of the routing that the hub does not do is worse than none; the members list is what the dashboard already reads, and the usual edges answer the question readers ask (who hears about this) without claiming the hub computed them.

**Rejected alternatives:** a routing table of the dashboard's own, kept beside §8: a second copy that drifts from the hub. Leaving out the edges the members list cannot settle: card assignment, the most asked about, would show nothing. A force layout: it moves on every redraw and hides who reports to whom; the draft's tidy tree keeps the hierarchy readable.

## Join an agent asks for the second factor in its form, and names the project and the missing right

**Id:** 2e60e51f-5e0e-4bd0-bc46-365b3c050d13
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's reports on tsk-trb99kkhv1rk (an owner could not create a join and saw only "you lack the rights"; the maintainer saw "this call needs your second factor first" with the second factor set to mail for everyone), 2026-11-05; hub/src/maity_hub/routes/joins.py (`create_join` calls `require_step_up`), docs/api.md §2.8.4; web/js/step-up.js
**Revisit when:** the hub stops treating join creation as a sensitive call, or the dashboard gets one step-up place for every view

Creating a join goes through `M.stepUp.run`, the same as every other
sensitive call in the dashboard: on `step_up_required` the form asks for
the code (by app, or the mailed code under the mail factor) and sends the
join again; Cancel ends without a refusal. A bare `forbidden` with
`scope: members:admin` (no admin rights, and members may not bring
agents) is said in words that name the right. The panel names the project
the join is for, by name and full name.

**Reason:** the hub has always asked for the second factor on
`POST …/joins`, but the join form showed it as a refusal: in English
the hub's own sentence, translated as the generic "you do not have the
rights for this", so an owner who had done nothing wrong could not add an
agent at all. With several projects open the target project was only the
tab's.

**Rejected:** a hub change (the hub's rule is right; a sole owner may not
make themselves admin either, the maintainer confirmed); a generic words
entry for `step_up_required` in js/errors.js alone, which would say the
cause but still leave no way to give the code.

## The account is in tabs, each at an address of its own; the addresses before them lead to their tab

**Id:** 36bfb48e-ae7c-41f4-9e73-b0abfef34bce
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3banvfzv3nvs (the maintainer and the lead, 2026-11-05): the tabs Profile, Settings, Notifications, Security and Organisations, Linked accounts shown as to come, the profile menu as the tabs, a sideways-scrolling row on a phone, the hub unchanged; Security's own tabs proposed to the lead on the card (2026-11-05); the scroll carried over from the page before, reproduced on main (`/account` opened at 2481 of 4535 px)
**Revisit when:** linked accounts arrive, the hub's mails and redirects name the new addresses, or a tab grows long enough to want tabs of its own

The account page is in tabs (`js/account.js`), each tab at its own address. The profile menu is
the same list as the tabs, followed by Sign out.

| Tab | Address | What it holds |
|---|---|---|
| Profile | `/account` | name, handle, picture, meat proxy, public profile |
| Settings | `/account/settings` | preferences, the site's and the personal language, theme |
| Notifications | `/account/notifications` | mail, when mail goes out, agents that stop listening, browser notifications; a line leads to the language under Settings |
| Security | `/account/security` | its own tabs: Sign-in (second factor, then password), Sessions (`/sessions`), Another device (`/device`), Forge access (`/forge`), Your data (`/data`) |
| Organisations | `/account/orgs` | `js/orgs.js`, as before |
| Linked accounts | none | greyed, to come |

Security and Organisations are a human's alone, as in the menu before. On Sign-in the second
factor stands above the password form: the hub's mail and bell item about a changed or failed
second factor link to `/account/security` (`hub/src/maity_hub/notifications/mailer.py`,
`items.py`), and the hub stays unchanged on this card.

The addresses of the single page before the tabs are still reached from mails already sent, the
bell and the hub's links:
- `/account/picture`, `/account/preferences`, `/account/theme`, `/account/password`,
  `/account/sessions`, `/account/sign-in-device`, `/account/forge` and `/account/data` each lead
  to their tab. The new address replaces the old one in the history, the query goes along, and
  the heading of that part is focused.
- An unknown address leads to Profile, and an unknown tab of Security leads to Sign-in.
- `/settings/forge` is no old address: the contract names it as the setup's return (§16.11), so
  it shows Forge access itself (see the Forge access entry, 861705c6).

A change of view starts at the page's top (`js/app.js`, the route listener). Before, the
browser kept the scroll position of the page one came from. The board and an opened card count
as one view, so the card panel and the board's place on return stay as they were.

**Reason:** the account was a single page of eleven parts. One looked for a part by scrolling,
and the menu's entries were anchors into that page. Tabs show one part at a time, and each one
can be linked.

**Rejected alternatives:**
- Keeping the single page with the menu's anchors: this is what the card replaces.
- Letting the hub send the new addresses: the card leaves the hub unchanged, and mails already
  sent carry the old addresses anyway.
- Wrapping the tab rows: on a phone they would take two or three lines. The card asks for one
  row that scrolls, with the fade on the side that has more.
- Resetting the scroll on every change of address: opening a card on the board would jump to
  the top, and the board's place on return would be lost.

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

## An agent's motif is chosen beside its picture, named with the hub's English label

**Id:** d5f1e318-5368-4516-9d10-06a2194aaafd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-q155psrk6tzz, step 3 (the dashboard's part of the hub's motifs, 1c51a4c6); docs/api.md §6.10, "An agent's motif" (the dashboard shows its catalogue's `avatar.motif.<name>` where it has one)
**Revisit when:** the catalog gets the motifs' names in other languages, or the set grows past what one list can show
**See:** views.md#ones-agents-have-a-page-of-their-own-in-the-gear-menu-adding-one-to-a-project-is-that-projects-join-panel — 1031c11b-7642-4ed9-87ce-de504b2044fc — as of 2026-11-07

The owner chooses an agent's motif in the same picture editor as the upload, on the agent's card on
Agents and in its Manage row on Members, with `PATCH /agents/{id}` (`avatar_motif`, `null` to clear
it). It is one list of `GET /avatars/motifs`, its themes as groups headed by the catalog's
`avatar.motif.theme.<theme>`, plus a preview of the chosen motif from its public address with the
hub's `alt`. A motif is named with the hub's own `label`. The catalog holds no
`avatar.motif.<name>` yet, so the names stay English in every language, as the contract allows.

**Reason:** the catalog's keys must be literals in the code (`make check` reads them there), so
naming 36 motifs would mean a table of 36 keys in the view, kept in step with the hub's set by
hand. The hub's label is always there, current with the set it serves, and the theme headings are
two fixed words.

**Rejected alternatives:**
- A grid of all motifs as pictures, chosen by a click: every opened card would load 36 images at
  once, and the choice would need its own keyboard handling, which a `<select>` already has.
- Catalog keys for every motif now: a table that falls out of step with each new motif in the set.

## A project's inbox reads its open requests first; the answered ones only when asked for

**Id:** 874d4952-a257-4cd1-ac51-34b410b0a9a1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-y8gkq1kvt63c (the owner's request: the inbox took 7 s on prod); the measurement and plan on tsk-fxjtwmkc4md5 (notes nte-dpe78x619re6, nte-n1rj7s15xw3f: 4.6 s of the 7 s were three serial pages of the full request history); web/js/inbox.js `load`, `closedOf`
**See:** views.md#the-inbox-is-the-requests-alone-activity-is-on-the-bell-the-chat-button-and-notifications — 2ff6afe9-ed47-4ffd-b12d-947cfb7774ca — as of 2026-11-08
**Revisit when:** the hub's request list gets a page size or an order that makes the full history cheap, or the inbox shows the answered ones by default

A project's inbox asks its list with `status=open`. **Show** → all reads the
answered and withdrawn requests then (`status=answered,withdrawn`, §7),
once per view, and draws again. Choosing all again while that read runs
waits for it; a failed one is let go, so the next choice asks again. One
that answers after the view was left draws nothing and leaves the shared
selection to the view that stands; so does every read on the way in. A link to a request that is not open
(`/<owner>/<slug>/inbox/<id>`) reads that one request (`GET …/requests/{id}`)
and shows it among the answered, as before. The cross-project inbox always
showed the open ones alone and reads as it did.

**Reason:** the inbox read `status=all`, every request the project ever had,
page after page, before it drew anything; what it shows by default is the
open ones. Reading those alone keeps the first drawing's cost flat as the
history grows.

**Rejected alternatives:** a smaller page of the full history, which still
reads closed requests nobody asked to see and needs a second read for the
open ones it cut off; reading the answered ones in the background after the
first drawing, which spends the same reads on every visit. Both are
inferred, the card did not discuss them.

## The boot reads the window and the session together; /me still after the session

**Id:** 63c48583-5f47-4beb-93be-d4426d45f57b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-y8gkq1kvt63c (item 4 of the plan on tsk-fxjtwmkc4md5); lotse's choice of option 2 (message seq 94765, 2026-11-08) after the full e2e found the early /me failing by design; web/js/app.js `render` (`early`); the boot case in web/tools/smoke.js
**Revisit when:** the hub answers /auth/session and /me in one read, or a session that owes the second factor may read /me

`render()` starts `GET /auth/session` together with the window's read (`M.maintenance.fresh()`)
instead of after it, and handles the answers in the old order: the window first, then the session.
`GET /me` still waits for the session's answer. The invitation and registration pages read the
session themselves, so the drawing starts no early read for them, and only the newest session read
sets the language: an older answer, a 401 above all, that came back after it switched a newer
session's language back (review of #1524).

**Reason:** two round trips in a row before the session was known. The answers stay in their order
because each one decides whether the next matters (a running window, no session, a session that
owes the second factor). The window is cached for a minute, so later drawings mostly save nothing;
the first load saves one round trip.

**Rejected alternatives:** /me early as well (the card's first plan), gated by the hub's readable
session cookie and quiet towards the page. It fails by design for a session that still owes the
second factor (403) and for a cookie that outlived its session (401), which e2e's check for failed
answers reported; allowing those would have meant a harness exception that could hide a real
failing /me. Without the cookie gate it was worse: a visitor's 401 drew "your session has ended",
and an enrolment 403 redrew the setup in an endless loop. Asking /me with a fetch of its own,
outside `M.api`: a second client with its own error handling.

## A handle field's hint is a sentence of fixed words, with no handle or address filled in

**Id:** e9c2136d-efa9-4222-b013-6042a56ec86c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-srzrkf2parzt (the owner's decision req-3wdzdcvcbf7s: every field that asks for a handle explains the word); the ChatGPT reviewer's P2 in the review of #1488 (seq 91149) and the Grok reviewer's P3 (seq 91705); web/js/handles.js `explain`; e2e `handle_hints_step`
**Revisit when:** a hint has to name the reader's own handle or address, or the phone widths the e2e step measures change

Under every field that asks for a handle, `M.handles.explain(kind, input)`
adds one sentence of fixed words for its kind (your own, an agent's, an
organisation's, the person invited), which the field names in its
`aria-describedby`. Nothing is filled in: no handle, no host, no example
address. e2e `handle_hints_step` measures all seven kinds of field at 390
and 360 px, light and dark: at most two lines, no overflow.

**Reason:** the first version filled in the instance's host and the
reader's handle as an example (`maity.team/<handle>`). On the English
Account page that took three lines at 360 px, and a 31-character handle
three lines at 390 px, against the card's two lines on a phone. Fixed
words keep every hint's length known whatever the handle or the host.

**Rejected alternatives:** a filled-in example cut to a length, which
still varies with the host and reads oddly when cut; a filled-in example
only on wide screens, which gives two texts to keep true. The example
`agent-e` or `oz-team` as a fixed word was dropped too: it read as a fact
about the reader's own agent or organisation.

## A message's seq is drawn with its "#" from the stylesheet, so a copy takes the number alone

**Id:** 10d6fda7-c01c-4087-80e5-3c0a8ea4253c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-0aadqqwe8jvt and #1311 (the seq beside each chat message); the Grok reviewer's P3 on #1311 (seq 66303), collected on card tsk-gsk31zvpfv02; the code comment in web/js/chat.js at `msg-seq`; web/css/app.css (`.msg-seq::before`)
**Revisit when:** a seq becomes a link in the chat, or the number is to be read out with a word

Each chat message shows its seq beside its time as `#4202`. The span holds the number alone
(`.msg-seq`); the `#` is drawn by the stylesheet (`.msg-seq::before { content: "#"; }`), so it is
no part of a selection.

**Reason:** agents cite a message by its seq ("seq 54246", card tsk-0aadqqwe8jvt), so a copy of
the visible text should give the number they need, without the sign. The code comment says so;
the rejected alternatives below are inferred, nobody stated them.

**Rejected alternatives:** `#` as text in the span, which a copy takes along; a word such as
"seq", which the dashboard's other texts do not use for it; a link, as the join panel's
"message #seq", since a chat message has no address of its own to link to.

**Known gap:** a screen reader can hear "· #4202" (the stylesheet's `#` is read out too) with no
word for what the number is, and the list
is `aria-live`, so it is announced with each new message (the Grok reviewer's nit, optional; axe
reports nothing).

## All projects reads each project's members once per page drawn, shared by the Lead button and the inbox

**Id:** e66cb966-b6f3-417b-bb0a-0bd84ce1899d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-f78z1dvbs26a: prod's access log (17fce84f, 2026-11-09) counted `…/members` twice on a page, and the smoke harness found the double read on All projects, not on Settings; the lead's go for one shared per-render read (2026-11-10)
**Revisit when:** the hub offers one call for the members of several projects, or a page outside a project keeps project data across drawings

`M.membersOnce(ctx, slug)` (web/js/app.js) reads a project's member list once for one ctx,
which is one page drawn. On All projects the Lead button (`targetsEverywhere`, web/js/lead-chat.js)
reads every project's list, and the all-projects inbox (web/js/inbox.js) reads the lists of the
projects its requests come from; both take them from there, so for a project with requests in the
inbox `GET …/members` runs once instead of twice (one without requests was read once before too).
The next drawing has a ctx of its own and reads afresh.

**Reason:** All projects is the start page for anyone with two or more projects, and the members
read takes about 150 ms median on prod, so reading it a second time for each project with
requests in the inbox costs that page's load directly.

**Rejected alternative:** weighed while building it, a members cache kept across drawings of
All projects. A switch inside one project already keeps its members for at most a minute
(`KEPT_MS` in web/js/app.js) and reads them again behind the view; a cache without that re-read
would show a member list from before a change on the next visit, and adding it was more than the
card asked for. Alternatives beyond that were not discussed.

## The board draws once the open groups have answered; the closed columns follow

**Id:** e58ffe3b-1855-4e2b-ab65-b9cc9c693fe7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-a5pxwgkgr73e: the owner's feedback on deploy 6 (2026-11-10, the board one of two pages still over 1 s); the operators' per-call measurement of the board on rev 30 (2026-11-10: the five group reads start together and take 83–203 ms each; the closed group then pages serially, 4 pages of 200, about 0.9 s and 550 kB); the coordinator's go for this change the same day
**See:** views.md#the-board-reads-its-column-groups-side-by-side — 145f0bf3-3024-414a-8026-19dad1960ff7 — as of 2026-11-10
**Revisit when:** the hub serves the closed window in one page or a smaller shape, the closed window changes, or the board's first draw is measured over 1 s again

The board still asks its five groups at once and reconciles as before
(the entry above). What changed is when it first draws: once the four open
groups (`proposed`, `open`, `in_progress`, `blocked,review`) have
answered, with their cards, while the closed group (`done,cancelled` with
the 14-day window) is still paging. Until the whole read is in, the Done
and Cancelled columns hold no count and say that the closed cards are
being read; if that read fails, those columns say so and the open ones
stay as drawn. Then the board draws again with every card. The control
that had the focus keeps it, and a board left from a closed card finds
that card now. A reload after a write supersedes the first read: an
answer is drawn only if no later read's answer has been.

**Reason:** on the maintainer's project the closed window was 783 cards,
the largest group by far, and its pages follow each other through a
keyset cursor, so it held the first draw by about a second while the open
columns, the ones a reader works in, had long answered.

**Rejected alternatives:**
- Waiting for every group, as before: the reason above. The objection
  recorded then, that the closed columns and counts change under the
  reader, is met by showing no count and a loading line in those columns
  until they are complete.
- A leaner card shape for the board, or a shorter closed window by default:
  each a contract or product change, held until this change and a faster
  200-card page on the hub have been measured.

