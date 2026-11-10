# Chat

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

## Group chats live in the chat view's own two panes; the hub says which kind a chat is, and the history before one joined is read on demand

**Id:** 46abbbf3-40b9-4802-a22f-1a85293a9b8f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the group-chat contract (docs/api.md §9.2, §9.3, §8.5; PR #153) and the coordinator's card for the dashboard's part (tsk-b2dv60tsexjf), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub sends live events to an owner who reads along, a chat gets more than twelve people, or the list needs filters by kind
**See:** chat.md#the-chats-history-days-apart-a-senders-run-grouped-and-the-line-before-what-was-unread-when-it-opened — abe93ad2-1a75-4abc-a5d0-70e074d17335 — as of 2026-10-22

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
**See:** chat.md#group-chats-live-in-the-chat-views-own-two-panes-the-hub-says-which-kind-a-chat-is-and-the-history-before-one-joined-is-read-on-demand — 46abbbf3-40b9-4802-a22f-1a85293a9b8f — as of 2026-10-23

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

## The header's Chat badge counts unread chat messages from the notifications, not chats

**Id:** 3ad5cf20-0240-4536-aaef-3bd8b411288f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25 for Chat and Notifications buttons in the signed-in header (tsk-wnk7wv6p4se7), and the coordinator's ruling the same day on the badge; docs/api.md §9.3, §18.2; the dashboard's implementation, 2026-10-26
**Revisit when:** the hub counts conversations with unread messages (a per-conversation count on /me/notifications), or the message count proves misleading in practice

Where the theme menu was, the signed-in header has Chat; since
2026-10-31 the order is Chat, Lead, "+", the gear, the bell and the
profile (shell.md#the-header-gets-a--menu-to-bring-someone-in-invitations-get-their-own-page-runners-lose-their-tab — 3f6eadd3-d1d5-4389-bb65-626e9cdbc1dc). Chat leads to `/chats` and carries
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
**See:** chat.md#the-lead-is-reached-by-a-lead-button-left-of-chat-not-by-chat-itself-or-a-strip — 0ff66bde-7c26-412a-a856-069b52764910 — as of 2026-11-03

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

## A chat's meat-proxy switch sits between Attach and Send; it draws from its own answer, and Follow my profile gives the choice back

**Id:** 393898d2-62e1-4e5d-a1b7-8eacb859ea01
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §9.3 "Meat proxy per chat" after the contract #922 and the hub's #956 (`PUT …/conversations/{id}/meat-proxy` with `true`, `false` or `null`; the participants' entries carry `meat_proxy` and, for oneself, `meat_proxy_chat`; no event); the coordinator's card tsk-n872zkxmwbec (a switch beside Attach and Send in direct and group chats for human participants, a way back to `null`, the designer's two icons, on in the accent on `--out-bg`), 2026-10-31; the coordinator's word to use the designer's final3 icons, 2026-11-01; the button's shape and the Follow my profile link are the implementer's, 2026-11-01
**See:** account.md#the-meat-proxy-switch-has-its-two-parts-under-it-each-sent-alone-the-hub-decides-the-switch-and-the-note — e9c14296-f8da-4f83-871b-056a0d3ab6ed — as of 2026-11-01
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
**Source:** card tsk-j10w2hsm1h90 (the owner, 2026-11-03: the chat no longer ended at the window's bottom edge after the product line of #1290; the Chats list column too; "Sending…" to move beside the meat-proxy switch); browser measurements at 1280 × 800 and 390 × 844 in the PR
**Revisit when:** the chat stops sizing itself with `--chat-h`, or the product line moves out of the page's flow
**See:** chat.md#a-chats-composer-hides-for-reading-on-a-phone-and-grows-on-a-wide-screen-both-are-the-browsers-choice — 5af3970c-0f6a-42e7-a211-13ba27fbae5d — as of 2026-11-03

The open chat's height (`--chat-h`, `fitToScreen` in `js/chat.js`) is the window's height less where
the chat layout starts on the page and less what stands below it down to the end of the page
(main's padding, the product line of §16.13). The page then ends at the window's bottom edge, the
product line under the composer is in sight, and only the history and the chat list scroll. It is
measured again on a resize and whenever the page around it changes size (a `ResizeObserver` on the
body: a banner above, the product line below). It is never less than what the open chat cannot
shrink (its heading, the composer) plus 60 px of history, about three lines: on a screen too small
for that, the page scrolls and the product line stays below the composer, never over it. The
observer measures in the next frame, not in its own round, where a new height would resize the
body again and the browser would report a ResizeObserver loop. Besides the body it watches the
pane's fixed parts and the panes the layout holds: folding the composer or making it taller, and on
Chats a group chat taking a direct chat's place, change the floor without resizing the body; only the
current pane's parts are watched. A layout not yet in the page,
as Chats builds it while its view is still drawn, is measured once it is there, a few tries at
most, and then lets go of its listeners; the holder a pane is drawn into on Chats is not measured
at all, Chats measures the layout the pane moves into. While a
message is sent, "Sending…" and a failure stand in the composer's row, after the meat-proxy switch
and before Send, so no line appears below the row and nothing moves.

**Reason:** the earlier measure took the header's bottom and 16 px. It left out what stands between
the header and the chat and everything below it, so the product line pushed the composer past the
window's edge. On Chats the first measure came before the layout was in the page and stopped for
good, leaving the CSS fallback `calc(100dvh - 140px)`.

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
**See:** chat.md#a-chat-fills-the-window-from-where-it-starts-less-what-stands-below-it-sending-stands-in-the-composers-row — 21fd7884-0462-49dc-8e47-da59f57ef557 — as of 2026-11-08

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
