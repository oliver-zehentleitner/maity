# Inbox

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

## A project's inbox reads its open requests first; the answered ones only when asked for

**Id:** 874d4952-a257-4cd1-ac51-34b410b0a9a1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-y8gkq1kvt63c (the owner's request: the inbox took 7 s on prod); the measurement and plan on tsk-fxjtwmkc4md5 (notes nte-dpe78x619re6, nte-n1rj7s15xw3f: 4.6 s of the 7 s were three serial pages of the full request history); web/js/inbox.js `load`, `closedOf`
**See:** inbox.md#the-inbox-is-the-requests-alone-activity-is-on-the-bell-the-chat-button-and-notifications — 2ff6afe9-ed47-4ffd-b12d-947cfb7774ca — as of 2026-11-08
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
