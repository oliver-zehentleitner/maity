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
**Source:** the maintainer's request for card management and drag and drop, relayed by the coordinator, 2026-10-22; web PR #126 and its review, 2026-10-22
**Revisit when:** the contract gives cards an order within a column, or the hub exposes the moves a caller may make

Each card a human may move has a **Move** menu with exactly the moves the
hub allows them, mirrored from its transition check (proposed ↔ open for
the creator, holder or an admin; review → done or back with done
authority; cancel for an admin or an open card's creator). A pointer may
drag the card instead: while dragging, the allowed columns are outlined
and the others dimmed; a card let go over a refused column is said in
words on `dragend` (a browser fires no drop there) and nothing is sent.
There is no order within a column. The board's filters (member, area)
work on the cards already loaded.

**Reason:** a drag-only board leaves keyboard and phone users without a
way to move a card; the menu is the path for both, and dragging is a
shortcut over the same rule. Mirroring the table means the page offers
no move the hub would refuse, and the hub still decides.

**Rejected alternative:** offering every column and letting the hub
refuse — every refusal would be a round trip and a surprise. Filters as
query parameters to the hub — the board already holds every card of the
window, so filtering there is instant and needs no new contract.

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
