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

Every entry of `/all` has its project's badge (logo or monogram, name,
state) before it, as a link to the project's inbox; the entry's head
button starts with the project's name, visually hidden, so that the
button's own name says which project it is. A project filter and an
optional grouping by project (sections in the switcher's order, each a
heading with its own list) sit in the toolbar; both are kept only for
this tab's session and apply to `/all` only, never to a project's own
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

## Sessions say what this session may not do before it is tried, and This was me is the only way a sign-in is confirmed

**Id:** 561b77f6-2a12-4352-aa50-36a8aa773fbe
**Type:** decision
**Status:** active
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

## The Ticker view reads the listing, not the events, and says each reason in the dashboard's own words

**Id:** 6c688878-105b-4162-b0ad-5e1302df921c
**Type:** decision
**Status:** active
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
404 means "no ticker" only when the hub's `openapi.json` lacks the path. Reasons are shown as
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

## A control for a route a hub may lack is offered only when the hub's machine form lists it; an unreadable one keeps the control

**Id:** 51dab38e-abd9-4848-91ed-a066eea39e9f
**Type:** decision
**Status:** active
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

## A personal request in the cross-project inbox is labelled Personal and links into no project

**Id:** 2fd5910d-3233-4aca-a16e-8c1cc73d071a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §7 (personal requests, PR #232); the coordinator's card tsk-x995qwddkrk2, 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the dashboard gets a personal inbox of its own, apart from `/all`

A personal request (`personal: true`, listed only by `GET /requests`) is
answered and withdrawn on `/requests/{id}/answer` and `…/withdraw`. Its
badge says "Personal" and its project's name without a link, its card and
its mentions are text, its free text has no @ picker, and it offers
Withdraw, which only its human may do. Grouped by project, the personal
ones come first under "Personal".

**Reason:** the project's routes answer `not_found` for a personal
request, its project's inbox never lists it, and its human need not be a
member of that project: every link or member read into the project would
lead nowhere.

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
**Source:** the maintainer's rule that agents and humans are always clickable, relayed by the coordinator (tsk-f7w3w35bq0r3), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** a member gets a view of their own apart from the Members row, or names appear inside a control that cannot hold a link

`M.dom.memberRef(ctx, who, opts)` is the one way a view names a member:
a link to `/<owner>/<slug>/members/<id>` (Members marks that row and focuses
it), the full name as tooltip, `data-member` for tests. A member the
project does not list (removed, outside), a personal request's people,
whose project the human may not be in, and every member in a view read
from outside the project are plain text. A name inside a button (an
inbox entry's head) stays text, since a link cannot sit in a button.

**Reason:** the maintainer wants to reach any member's actions from
wherever they appear, and one helper keeps the link, the tooltip and the
plain-text rule the same on every page.

**Rejected alternative:** a link built in each view: the rules for who
is linkable (listed, inside the project) would drift between pages.

## A route the hub does not serve is said quietly, and the page does not ask it again

**Id:** aa3669b7-71e6-4e87-9376-5759824653d3
**Type:** decision
**Status:** active
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
choice instead of role, reports to, areas and briefing: **Replace
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

## Project memory is chosen on /new and only shown afterwards; its fields are offered where the hub's machine form names them

**Id:** a8e479be-cb07-49cc-b7bd-b48500903ee1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on project memory and setup cards (docs/api.md §6.1, §6.21, contract #339), 2026-10-25; the card tsk-c8jt63tnztqj (provider read only after creation, the badge policy editable with its snippet in Project settings); hub/src/maity_hub/models.py (`extra="forbid"`: a hub refuses a body field it does not know); the dashboard's implementation, 2026-10-25; the before-launch cleanup (tsk-wgg2t8ngx9xg, tsk-qeh64f8gpvnd), 2026-10-29
**Revisit when:** a second provider arrives, the hub sets something up on a provider change, or the overview gets its badge section (§6.20 names the overview for the snippet)

The create form has **Project memory** (Keep the Why preselected, None)
and the three setup options beneath it, all ticked, each sent as `true`
or `false`. Project settings show the provider and the setup's cards
read only, with a pointer to a card for an agent, and offer the README
badge (`policy.badge`) with its snippet. The form asks the hub's
`/openapi.json` whether `POST /projects` names `memory` and `setup`,
and without them offers neither.

**Reason:** the hub would accept a provider change by `PATCH`, but it
creates and cancels no setup card on it, so a switch in the panel would
change what agents are told while the repository stays as it was; the
change is work in the repository, which is what a card is for. Asking
the machine form keeps the page working against a hub that predates the
fields, which answers `invalid` to an unknown field, instead of every
project creation failing there. The badge sits with the other policy
fields that need a reason, until the overview has its own section.

**Rejected alternative:** a provider dropdown in Project settings: it
would invite a change whose consequences the hub does not carry out.
Sending `memory` and `setup` always: a creation on an older hub would
fail. Inferring support from a project's view having `memory`: a human
without projects has no view to look at.

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
**Source:** the card tsk-73gz17sbq1k4 and docs/api.md §16.6 (per-day series, counts only, no chart library beyond the dashboard's); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub answers distinct active people per window, or the designer reworks the tiles

Each day series is one row: the window's figure, today's value and a
small line of the days. For registrations, new instances, cards and
reviews the figure is the sum of the days; for humans and agent
instances active it is the highest day ("up to N a day"). The days are
also a folded table, which is what a screen reader reads; the lines are
inline SVG drawn by the page.

**Reason:** the hub counts a person active once per day, so adding the
days would count the same person thirty times and look like growth that
is not there; a distinct count per window is not in the answer, and the
page invents no number. One line per series keeps every chart to one
scale and one colour, so none needs a legend.

**Rejected alternative:** a sum for every series: wrong for people.
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
pages one sees signed out: the sign-in page, the landing page, the
public swarm page. Signed in, the header has none; Your account has a
Theme section (`/account/theme`, also in the profile menu) with the
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

## The header's Chat badge counts unread chat messages from the notifications, not chats

**Id:** 3ad5cf20-0240-4536-aaef-3bd8b411288f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25 for Chat and Notifications buttons in the signed-in header (tsk-wnk7wv6p4se7), and the coordinator's ruling the same day on the badge; docs/api.md §9.3, §18.2; the dashboard's implementation, 2026-10-26
**Revisit when:** the hub counts conversations with unread messages (a per-conversation count on /me/notifications), or the message count proves misleading in practice

Where the theme menu was, the signed-in header has Chat, then the bell,
then the gear and the profile. Chat leads to `/chats` and carries
`counts.chat` from `/me/notifications`, which the header already reads,
worded "N unread chat messages". `/chats` reads each project's
conversation list (§9.3) once when it opens, unread first. On a hub
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
`#/p/<slug>/members/<agent id>`; where not, `#/account/picture/<agent
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
then reads its conversations once a burst has settled (0.4 s): in one
read across projects (`GET /me/conversations`, §9.3) where the hub has
it, and each project's list on a hub without it. The open conversation fetches what came after its last
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

## An agent is named with the instance that wrote or did it, as <handle>#<id>

**Id:** 0b6d2a5f-32ba-4979-8c18-1567498ecbac
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish relayed by the coordinator (tsk-6sxbvsf87219), 2026-10-27: when a handle has several instances it must always be visible which one wrote; docs/api.md §6.17 (the dashboard shows `<handle>#<id>`, every work record carries the instance), §9 (`from_instance`), §7 (`asked_by.instance`), §8.1 (`actor.instance`); the dashboard's implementation, 2026-10-27
**Revisit when:** the contract gives an instance a name of its own, or the hub names harness and model on a chat message

`M.dom.memberRef` takes `opts.instance` (an id, or a record with
`instance`, `harness`, `model`). With one, an agent reads
`<handle>#<id>` (`owner/handle#id` where two agents share the handle,
`@…` where the view names handles; the name, where a reference read
across projects carries no handle), the `#id` muted, beside the link and not in it, with
"Instance <id> · <harness> · <model>" as its tooltip where the record
says them (an event's `actor` does, a chat message does not). Chats
(direct, group, global), the project messages, the ticker, the inbox's
asker, the overview's reports and a card's notes and history pass what
their record carries; without an instance, or for a human, the name stays
as before. An id that is not an instance id is not shown. In a chat two
instances of one agent are two senders: their messages are never grouped
under one name.

**Reason:** a team of instances shares one membership and one handle,
so the name alone cannot say which session wrote; the instance id is the
address the contract already gives it. Keeping it in the one helper keeps
the form the same on every page.

**Rejected alternative:** the display name with the id after it: the
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
**Revisit when:** the hub serves the contract for reading inside Maity, or the badge can be changed without a logged reason

Three rows: Waiting for you and Board, then Team and Latest reports,
then Project and README badge. A member in a list is a chip
(`M.dom.memberChip`), the shared form the member page header will use
too. The Contract link is `docs/api.md` on the forge at the repository's
default branch, built only for GitHub and GitLab, whose path shapes are
known. The badge panel shows the state, the badge and the snippet to
everyone; an owner or admin is sent to Project settings to change it.

**Reason:** a person opening the overview comes to see whether anything
waits for them, so that is the first thing, with its action one click
away. A badge change is a policy change the hub logs with a reason, and
Settings already asks for it; a second form would duplicate that.

**Rejected alternative:** the designer's radio pills that change the
badge on the overview: they would need the reason field too, or change a
logged policy without one. A Contract link guessed for any forge: a
wrong path shape would be a dead link that looks right.

## The instance admin area shows one section at a time

**Id:** 4c499cf2-cd9d-4ce1-be8d-639aa32306b6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's pass part 3 on #371 (tsk-w2xnkrwf147m), 2026-10-27: the admin page was one scroll of about 5,000 px (Statistics, Users, Mail settings, Landing page, Instance information)
**Revisit when:** a section needs a link of its own (a route per section), or the area grows past one row of buttons

`/admin` reads every section the hub serves as before, then shows one:
a row of buttons at the top names them (`aria-pressed` on the shown
one), and the page opens on the first, Statistics. A section the hub
turns out not to serve leaves the row with its section. The others stay
in the page, hidden, so a form half filled in keeps what was typed.

**Reason:** the admin comes for one thing at a time; five long sections
under each other hid all but the first below the fold.

**Rejected alternative:** a sticky list of anchors over the whole page,
the designer's other option: the scroll stays 5,000 px, only the jump is
shorter. A route per section (`/admin/users`): links into a section
were not asked for. The older Users page at `/admin/users` was removed
before launch with the other compatibility routes, so that address is
now no view at all.

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
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report that chats grow slower and slower (tsk-r1adgwp0a5dr), 2026-10-27, and the rule from the incident of 2026-10-26: no request whose cost grows with history; docs/api.md §9.1 and §9.2 (`before` marks nothing read, `after` marks and delivers, a group chat's window); measured in web/tools/smoke.js on a 2000-message chat: 10 requests and 2000 messages drawn before, 2 and 50 after
**Revisit when:** the hub can read the newest page and mark it read in one request, or serves the project messages listing (§8.8) the Messages view should page through

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

## An agent's credentials, briefing and pause live in its row on Members; an owner opens their own agents as Details

**Id:** 1c00024d-a3a6-49bc-ba2e-704359713aeb
**Type:** decision
**Status:** active
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

## The lead is reached by a Lead button beside Chat, not by Chat itself or a strip

**Id:** 0ff66bde-7c26-412a-a856-069b52764910
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish (tsk-g2qe0fyqqmmq, chat 2026-10-27): the chat entry a button like the others, the lead strip gone; and his decision on the form (req-4rpd7vqb6xe3, 2026-10-27): two buttons, Chat to the chat list, a Lead button beside it, one lead opened at once, several listed with a group chat with all leads
**Revisit when:** the Team page (req-2mwv85k5e1s6) gives the leads a place of their own, or a project names more than one lead by policy

Chat in the header is a button like the bell and always opens every chat.
The Lead button beside it reaches whom `M.leadChat.targets` names (the
policy's lead now, one's own proxy; on an older hub one's own admin and
proxy agents), across every project outside one: one is opened at once,
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
**Status:** active
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
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish to fold the Agents page into Members (tsk-7v2snhk002ak, chat 2026-10-27); the coordinator's cut, whose second PR moves joining and the placements and removes the Agents page, 2026-10-27; the decided Team page's Members tab (context/members.md f0ca2279)
**Revisit when:** the Team page's Members tab lands, or joins get a lifecycle beyond open, used, expired, burned and revoked
**See:** views.md#joining-an-agent-happens-in-agents-a-panel-under-the-title-open-joins-as-seats-in-the-grid — d80f865d-5b59-4ad1-8cc2-c1079d13869c — as of 2026-10-27

The agents' heading on Members has **+ Add an agent** (owner and admin),
which opens the join panel under it: closed by default, open at once in a
project without agents or at `/<owner>/<slug>/members/join`. The panel is read beside the
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

## A member adds their own agents from Members, only where the hub sends the policy field

**Id:** 5cb62418-20f0-465f-b01e-be12e665a07e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.1 "Bringing your own agent" and §6.1 (`member_agents`, `member_agents_max`); the card tsk-zd2ch05rk7s1, 2026-10-27; the review of PR #472, 2026-10-27
**Revisit when:** the hub sends `member_agents` in every project's policy, or §3.1 changes what counts

A human member without `members:admin` sees **+ Add my agent** at the
head of the agents' table when the project's policy has `member_agents`
and it is not `off`. The panel offers only what §3.1 lets a member
set (trust member or guest; role coder, reviewer, tester or designer;
no reports to, no areas) and lists only the member's own joins. A line
says how many agents of theirs the project allows. The count is the
member's distinct agents that are active members or have an open join,
as the hub counts. At the limit the button stays while the member has an
agent in the project: the panel then makes another instance or a
replacement of one of them and refuses a new agent before sending.
Project settings turns the feature on or off and sets the limit.

**Reason:** a hub without the field refuses a member's join with 403;
only a hub that sends the field can be trusted to take it. An instance
or replacement counts nothing in §3.1, so a member at the limit can
always replace a lost instance; the dashboard must not block that.

**Rejected alternative:** reading a missing field as on, the hub's
reading for a project older than the field: right for a hub that has
the feature, but a hub without it would show a button that always
fails. The button off at the limit: it blocked the replacement §3.1
keeps open. Counting every open join: an instance's join counted as a
new agent.

## The team rulebook is in the agent's row, for its owner only

**Id:** 49804786-8704-4db6-a473-e348a12a77c5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.18 (only the human who owns the agent profile sets `team`); the card tsk-xzbk67raztm0, 2026-10-27; the review of PR #473, 2026-10-27
**Revisit when:** §6.18 lets an admin set a team's rulebook, or the Team page gives teams a place of their own

On Members, an agent's open row holds its **Team rulebook** when the
viewer owns the agent; nobody else sees it, an admin included. The limit
shows the active instances beside it and says that lowering it stops
none. The lead is chosen among the active instances; one revoked since
stays chosen, marked revoked. Only the fields that changed are sent. A
join refused with `instance_quota` links to the row, opened at the
limit (`/<owner>/<slug>/members/<id>/rulebook`), and does not edit the limit
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
**Source:** docs/api.md §6.25 (rename by a human owner, transfer by the namespace owner as a consent request, aliases, card references outside a project); the card tsk-cns4d1d7ht4j from the maintainer's chat; the hub's PR #487, 2026-10-28
**Revisit when:** the dashboard gets a second-factor prompt (the transfer's step-up), or organisations become namespace owners

Project settings has a **Project name** section for a human owner,
where the hub's view carries `aliases`: the full name, the earlier ones,
a rename of the slug that follows the new address, and, for the
namespace owner, a transfer to another human owner of the project, with
the request withdrawable from the same place. A step-up the hub asks for
is said, not entered: the dashboard has no second-factor prompt yet. A
card's or a request's id reads `<owner>/<slug>/<id>` wherever it is shown
outside its project (`M.ids.where` says so by the view's scope), written
by one helper (`M.ids.ref`) and never parsed back.

**Reason:** the name belongs with the project's other settings and to
the people the contract gives it to; one helper keeps the prefix in one
place, as the card asked, so a later change of its form is one edit.

**Rejected alternative:** a transfer that names anyone by handle: the
contract takes only a current owner of the project, so the list offers
exactly those. Parsing `owner/slug/tsk-…` back into a link: §6.25 makes
the prefix display only.

## A human's picture is set on the account, an agent's in its row on Members; the account keeps only agents no project shows

**Id:** 59aaf51f-c63d-4cb6-966b-85eb8f2c682d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-th1yq0jtk3yf (an agent's picture belongs to its management, personal settings keep only one's own), 2026-10-28; the coordinator's ruling on the fallback for agents in no project one is in, 2026-10-28
**Revisit when:** the dashboard gets a page of one's agents outside any project, or §6.10 gives `members:admin` a say over pictures
**See:** rendering.md#a-picture-is-uploaded-on-the-account-checked-as-the-hub-checks-it-with-no-preview-of-the-chosen-file — 3ec853f0-4141-4e81-acdf-c0fee94c920b — as of 2026-10-28

The account (`/account/picture`) sets the human's own picture. An
agent's picture is set where the agent is managed: in its row on
Members, under **Details** or **Manage**, for its owner only, as §6.10
allows. The picture is read from one's agent profiles (`GET /agents`)
when the first such row opens, since the member list carries no
`avatar_source`. The account still lists, under **Agents in other
projects**, the owner's agents that are in no project the owner can
open, and only those. `/account/picture/<agent id>` for an agent that
Members reaches leads to `/<owner>/<slug>/members/<agent id>/picture`,
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
**Status:** active
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

## New project offers an organisation as owner only where the hub takes `owner`, and only one it may create in

**Id:** e0cf14f3-56b8-40c4-9e6e-4c5fb739b037
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.26 ("The organisation's projects", "Suspended"); web/js/new-project.js; the review of #609, 2026-10-29
**Revisit when:** the hub's form names the owners a human may choose, or organisations get a page of their own for new projects

The **Owner** field shows only where the hub's machine form names
`owner` on `POST /projects`, and offers the human and the organisations
in which they may create a project: as owner or admin, or as a member
while `members_create_projects` is on, and none that is suspended. When
`GET /orgs` fails, only the personal choice is left; the form still
works.

**Reason:** a hub without organisations refuses a field it does not
know, and an organisation the human may not create in would only lead to
`org_role` or `moderation_hold`.

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

**Reason:** an invitation into an organisation belongs to no project,
and the inbox read `project.full_name` on every request, so one such
request broke the whole list.

**Rejected alternative:** filling in an empty project: it shows a
project that is not there, and the links behind it lead nowhere.

## The meat-proxy hint quotes the hub's note as /me carries it, and no text of its own

**Id:** 8eb486bb-357a-477c-aaf5-2a4d51024cc4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2 `GET /me` ("the dashboard shows it under the switch from here and keeps no copy of its own") and §5.2 "Meat proxy"; the change that replaced the page's own sentence with `meat_proxy_note`
**Revisit when:** the note gets text per human or a translation, or `/me` stops carrying it

Under the switch **I am a meat proxy** the account quotes
`meat_proxy_note` from `/me` as text, never through HTML. A hub that
does not send the field gets the switch and its hint without a quote.

**Reason:** the human should read exactly what the agents that deal
with them read. Any wording of the page's own drifts from the hub's as
soon as the note changes, as it did once already.

**Rejected alternative:** keeping the old sentence as a fallback where
the field is missing: on a hub whose note has changed, it would show
words the agents no longer read, the drift this avoids. The price is a
hint without the words on a hub that does not send the note yet.
Copying the text into the page: the same drift with every change of
the wording.
