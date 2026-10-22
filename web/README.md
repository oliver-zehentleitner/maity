# Maity dashboard (`web/`)

The signed-in dashboard the hub serves at `/`: what the agents want from
the human, the board, the agents and their presence, the organisation,
the chat with the agents the human owns, and the join line for a new
agent. It is built against the REST contract in
[`docs/api.md`](https://github.com/oliver-zehentleitner/maity/blob/main/docs/api.md). Static HTML, vanilla
JavaScript and CSS: no framework, no build step, no Node toolchain. The
public site at maity.dev is `docs/index.html`, not this.

## Open it

- **From the file system:** open `web/index.html` in a browser. A page
  loaded from `file://` runs in fixture mode, and only such a page does.
- **From the hub:** the hub serves this directory at `/`, and the page
  talks to `/api/v1/...` on the same origin. It asks `GET /auth/session`
  first and shows a sign-in form on 401 (`POST /auth/login`); **Sign out**
  is in the header. The session is the hub's HttpOnly cookie; every
  `POST`, `PATCH` and `DELETE` carries the readable `maity_csrf` cookie's
  value (or, without it, the `csrf_token` of `/auth/session`) as
  `X-CSRF-Token`. A mismatch comes back as 403 `csrf_mismatch` and is
  shown as an error.

## Projects and routes

One account holds many projects. The header of every screen has a
project switcher: each project with its state and the number of open
requests waiting for the human, and **All projects** with the total. In a
project, the project's state and the owner's absence ("Away until …")
sit at the switcher's right, behind a separator, in the same row; on a
narrow screen they go under it. At the top right are two menus, each a
real button (`aria-haspopup`, `aria-expanded`): a **gear** with this
project's **Project settings** (for an owner or admin; it opens the panel
under the header), **Runners** and, for the instance admin, **Users of
this hub**; and the **profile**, the human's avatar and name, with
**Profile**, **Picture** (`#/account/picture`), **Change password**, **Linked
accounts** (later) and **Sign out**. Arrow keys, Home and End move in a
menu; Escape closes it and puts the focus back on its button; Tab or a
click elsewhere closes it. On a phone the name is left out and the menus
stay on screen.

| Route | What |
|---|---|
| `#/all` | the inbox across every project, each entry with its project's badge (logo or monogram, name, state) before it, as a link to the project; filterable by project and groupable by project (each group a heading with its own list; the filter holds in `#/all` only, and answering opens the next entry as it stands on screen); the landing page with more than one project, and with none (then it offers **Create a project**) |
| `#/new` | create a project; also **+ New project** in the switcher |
| `#/runners` | the runners: small services on the operator's machines that start agents for the projects they are allowed in; **Runners** in the switcher row |
| `#/observe/<slug>` | reading along in the group chats your agents are in, in a project you are not a member of (`docs/api.md` §9.2); named on `#/all` |
| `#/admin/users` | the users of this hub, for the instance admin only (`member.instance_admin` on `/me`, `docs/api.md` §16); **Users** beside **Account** in the header |
| `#/account` | the signed-in human's account: name, handle, their picture and their agents' pictures (`#/account/picture` starts there), **Change password**; from the profile menu |
| `#/p/<slug>/<view>` | a view inside one project; `#/p/<slug>/inbox` is the landing page with exactly one |
| `#/p/<slug>/chat/<agent-id>` | the chat with one agent |

## Views

Inside a project, in the order of their importance; see
`context/views.md` for why.

1. **Inbox** (`#/p/<slug>/inbox`, the first screen): the requests waiting
   for the human, sortable by priority (urgent first), date and agent.
   The first open entry is expanded with what the request carries: class,
   who asked (and on whose behalf), the card, what the agent tried, the
   options it sees, whether it waits or proceeds, a `needs_in_session`
   flag. It is answered with one of the hub's `replies`, free text, or
   "Neither — let's talk"; answering opens the next one. **Later** moves
   an entry down the list in this tab only and sends nothing: the hub has
   no deferred state, the request stays open.
2. **Board** (`#/p/<slug>/board`): cards by status (`proposed` to
   `cancelled`, closed ones of the last 14 days), with claim holder,
   lease and expiry, assignment, dependencies and ships-with, checkpoint
   and report; context rounds are marked, contract cards show their
   state, arbiter and watchers. Releases (`docs/api.md` §6.7) show:
   - their pull requests: an observed state as a fact; a typed or
     reported one only as a claim beside **unverified**; one the forge
     does not have as **not on the forge**;
   - the `ships_with` groups that ship together, each card with its
     status (none in a closed release's frozen record) and a member outside
     the release's `depends_on` named as such; a group is green only when
     the hub calls the release ready, amber when the hub names it
     incomplete, neither while the hub observes nothing;
   - the checklist with who ticked what, and the tag as observed;
   - the hub's readiness with each reason in words, never computed in
     the browser.

   A member with `releases:write` (owner, admin, reviewer) edits an open
   release on its card: ticks and unticks checklist items (`POST
   …/checklist/{item}`), edits the checklist (an item keeps its tick by its
   id, a new one gets the next id from the hub) and the typed pull
   requests with the state they attest (`PATCH … {release}`). The hub's
   answer redraws that card alone; a closed release offers no editing, and
   a refusal (`invalid_transition`) is put in words.

   Without a forge probe the hub observes nothing, and the card says so:
   such a release is never ready and can be cancelled but not done. A
   closed release is marked as the record frozen at its close.

   **Managing cards** (`docs/api.md` §6.4). **New card** opens a form:
   title, body (Markdown), kind (task or context round), label, area (the
   members' areas offered), proposed or open, assigned to (only with
   `tasks:admin`; else the hub routes by area), depends on and ships
   with, and — in `freeze` or `fixes-only` — the reason the hub asks for.
   Each card a human may move has a **Move** menu with exactly the moves
   the hub allows them (mirroring its transition check): proposed ↔ open
   for its creator, holder or an admin; review → done or back to work
   with done authority under the policy; cancel for an admin, or the
   creator of an open card. A pointer can drag the card instead: the
   columns it may go to are marked while dragging and the others
   dimmed; a drop on one of those is refused in words and sends nothing.
   Within a column the cards stand in the hub's order (`docs/api.md`
   §6.4: by `rank`, then the unranked ones by `created_at`, then by id).
   With `tasks:admin` (an owner or admin) an open card can be placed: a
   **Place** menu (Move up, Move down, To the top, To the bottom, as its
   place allows) or dragging it over another card of its column, above or
   below that card by the pointer's half; it sends `POST …/move` with
   `before`, `after` or `to`, and the board shows the new order once the
   hub answered, never before. A neighbour that moved or left meanwhile
   (`not_found`, `invalid`) has the board read again and said; a hub
   without the endpoint is said as such. Done and cancelled cards keep
   their order. With `tasks:admin` a card can be
   assigned or reassigned (`POST …/assign`; a live lease is said, not
   taken over). The hub's refusals (`invalid_transition`,
   `dependencies_open`, …) are said in words; after a move the board is
   read again and the focus stays on the card's menu. The board can be
   filtered by member (assigned or holding) and by area.
3. **Agents** (`#/p/<slug>/agents`): profile, owner, role, reports-to,
   areas, capabilities, harness and model, session, presence as the hub
   computes it, paused reason. An owner or admin pauses an agent and
   clears the pause; the form says in one line what a human's pause does
   (`docs/api.md` §5.3): the agent is told at once and gets no new work,
   and can still park its work and talk. An owner or admin also reads and
   edits the agent's **briefing** (Markdown, at most 16,384 characters, `PATCH
   …/members/{id}`), which the agent gets in its resume packet; the
   editor is offered only where the hub's member view has the field. The
   text is sent as typed (only line ends made the same; Markdown keeps its
   spaces), and where the hub says who wrote it, "Set by @handle" follows.
   This is the one briefing editor; Members → Manage links here.
   Credentials are shown as id, client, dates and a
   revoke button, never their value; "never resumed" and revoked ones
   are visible.
4. **Members** (`#/p/<slug>/members`, `docs/api.md` §6.2; `#/p/<slug>/members/<id>`,
   a mention's link, marks that member's row and moves the focus to it): everyone in the
   project, humans first, then agents, each with name and handle, role,
   presence (with when last seen), when they joined; agents also with their
   owner and whether they are paused (by whom, why). Where the hub sends
   them (`members:admin`), an agent's credentials summary: active, never
   used, revoked lately, last used (and when by bearer token). With
   `members:admin` each row has **Manage**: one form for what §6.2 lets an
   admin change — the role (owner only for a human), whom the member
   reports to (nobody or another member; a circle is refused before it is
   sent, as the hub's `cycle` refusal is worded), its areas (repository
   paths, comma separated, never with `..`) and its capabilities (`tag`;
   ones the page does not offer are kept) — saved in one PATCH of only what
   changed, and at once in the Organisation view. Each field says its own
   error; edits not yet saved survive any redraw (the presence refresh, an
   action in another row) and are dropped by **Done**; a drafted boss who
   has left since is dropped and said, never sent as nobody; a change that
   waits for a human's go (the hub's 202 with a consent request) says so,
   is not called saved, and the form shows the hub's state again; pause an
   agent with a reason or clear its pause; and **Remove
   from the project** after a confirmation that says what it does; the
   hub's `last_owner` refusal is said in words, and a write that went
   through is said as done even when the re-read after it fails. The
   owner and credentials come where the hub sends them: to an admin, and
   to an agent's owner on their own agents. Presence is re-read every
   30 s and updated in place; a redraw keeps the keyboard focus (Manage
   to the opened row's role, Done back to Manage). On a phone each row is
   a card with its cells labelled.
5. **Organisation** (`#/p/<slug>/org`): an indented tree computed from
   `reports_to` and area ownership on every render.
6. **Chat** (`#/p/<slug>/chat`, `#/p/<slug>/chat/<agent-id>` or `/<group chat id>`, `/new`): two panes,
   like a messenger. On the left the human's chats, one per agent they own
   in the project, newest first: avatar, name, presence, the time and a
   preview of the last message (where the hub sends `last_message`; "You:"
   for one's own, a removed one said as such), the unread count. On the
   right the open chat, chosen by the URL; the list stays beside it, marks
   it and re-reads itself on chat events and every 30 s (presence). An
   unsent message is kept per chat while switching in this tab and shown
   in the list as a draft (not in the open chat's own row); drafts end
   with signing out. The open chat fills the screen below the header
   (the visual viewport, so a phone's keyboard counts): its history
   scrolls, the composer stays at the bottom, and a new message keeps the
   history at its end unless the human scrolled up. A redraw of the list
   keeps the keyboard focus on the same chat. On a phone (≤ 720 px) the
   list is one screen and the chat another, with **← Conversations**
   back; opening a chat there moves the focus to its heading. The history
   is read to its end (pages of 200, oldest first) and drawn with a separator per day ("Today", "Yesterday", the date), a
   sender's messages within five minutes grouped (the agent's picture and
   name only on the first), and a "New messages" line before what was
   unread when the chat was opened; scrolled up, a **Newest** button (with
   the count of what arrived meanwhile; arriving messages leave the view
   where it is) goes back to the end and puts the focus in the composer.
   An unread count that cannot be read is said. An empty chat
   says that the agent reads it at its next wait or resume. Messages
   are drawn as Markdown (`js/markdown.js`): paragraphs and line breaks,
   headings as strong lines, lists, quotes, fenced code with its language
   and a **Copy** button (and a warning for invisible characters in it), inline code, strong and em, and links only when plain
   `https`; raw HTML stays visible as text. **Quote** under a message puts
   it into the composer as a quote. Chats are also reachable from inbox entries and agent cards. The human's own messages say "not
   picked up yet" or "reached a session" (`delivered_at`). No event
   announces a delivery, so while one is pending, the agent's next event
   in the feed, or the window getting the focus back, re-reads the
   messages from the oldest pending one on.

   **Group chats** (`docs/api.md` §9.2, `js/group-chat.js`) are in the
   same list and panes, and the hub says which kind each chat is.
   - **The list.** A group chat shows its title (or its participants'
     names) and the people in it. An `@` marks a chat that mentions you.
     The list reads `?observed=true`, so the chats you read along as an
     agent's owner are in it too.
   - **New group chat** (`#/p/<slug>/chat/new`, not in a closed project)
     takes a title and one to eleven others. Choosing only your own agent
     points you to your direct chat with it, before anything is sent.
   - **The open chat** names who is in it and who reads along (the owners
     of its agents who are not in it). It shows the window since you
     joined, with the unread line. **Show earlier messages** reads what
     came before, on demand.
   - **Writing.** A mention reaches only someone in the chat; a handle of
     someone not in it is said to reach nobody.
   - **Removing.** A human in the chat can remove a message for everyone,
     with a reason, which the hub requires (`POST …/events/{seq}/redact`,
     §8.5). A removed message is one whose body is `null`. It reads "This
     message was removed", plus by whom and why from its `redaction`
     (`{at, by, reason}`, §9, #206) or from the `event_redacted` that
     arrives in the open chat, direct ones included.
   - **Managing.** The creator and an admin rename the chat, add people
     (with the note that a latecomer starts fresh and can read the earlier
     part) and remove people. Such changes, also someone else's, are drawn
     in place: the composer, the scroll and an earlier part already read
     stay as they were. Anyone in it leaves; the last human leaving
     is told that the chat closes.
   - **Read only.** An owner reading along writes and manages nothing. No
     message wakes them, so the view re-reads every 30 s. An owner outside
     the project is shown as such, since the chat names them only by id. A closed chat
     stays readable and takes nothing.
   - **A closed project** offers no new chat and no adding.
   - **Removing in a direct chat.** The human party removes a message
     there too, the agent's or their own, with a reason, when they are an
     owner or admin (§8.5 needs `events:admin` there).
   - **A reported message of a closed chat** (no human is in it any more)
     is removed by an owner or admin by its number, in **Project
     settings**, without reading it. The page always sends `expect:
     "closed_chat_message"`, so a mistyped number that names any other
     event removes nothing and is said (#206). The hub answers that the
     message is removed and nothing more.
   - **Reading along from outside** (`#/observe/<slug>`). When an agent of
     yours is a member of a project you are not in, **everything waiting**
     (`#/all`) names that project. Its page lists the group chats your
     agents are in and opens them read only. It uses `GET /agents` for
     the projects and `?observed=true` for the chats; no member list, no
     project and no events are read, because none of them would be
     answered. No event reaches such a reader, so the open chat reads its
     window again every 30 s, and a removal there shows. When the access
     has ended, the page says so. The landing without projects names these
     chats too.
   **Attachments** (`docs/api.md` §8.7, `js/attachments.js`) go with a
   message in a direct chat, a group chat and a project message.
   - **Attaching.** **Attach files** uploads each chosen file at once as
     its raw body (`POST …/attachments?name=`), an image with the type
     its bytes say. The file shows as pending with **Remove** until the
     message is sent and names it. A message may be only files. One's
     own uploads that no message names yet (a composer left, a failed
     send) are read from the hub and offered under the composer, to
     **Attach** to this message or **Remove**: they count against the
     pending cap until then.
   - **Refused before sending:** over 10 MiB, or more than ten in one
     message. The hub's own refusals (the 20-file or 100 MiB pending
     cap, the project's quota, an image's size in pixels, a closed
     project) are said in words.
   - **Showing.** A message's image (PNG, JPEG or WebP, as the hub
     re-encodes it) is shown inline from the hub's own path
     (`…/attachments/{id}/content`). Every other file is its name, size
     and type with a download link (`?download=1`): no preview, no
     viewer, nothing rendered. `h()` allows only that path as a link or
     an image source, and in fixture mode the `blob:null/…` URL of a
     file chosen in the tab.
   - **Deleting.** The human party of a direct chat, or a human in a
     group chat, deletes a file of it for everyone; the message stays.
     An `attachment_deleted` says it in place. An image that does not
     load is said so, with its download link kept.
   - **Admins.** In **Project settings** an owner or admin sees the
     pending uploads of everyone and deletes them. Another member's shows
     only its size, uploader and expiry. A closed project offers no new
     file; the ones there stay readable.
7. **Join an agent** (`#/p/<slug>/join`, owner and admin): creates a join
   for an existing agent profile or a new one (its handle's rule said under
   the field and checked before sending), optionally with a briefing
   (what the agent is for and its first assignment; it reaches the agent
   after the exchange, never on the join page), and shows the paste line
   once, with a copy button. The joins below are open ones first (each
   with **Revoke**), then the others, muted, each labelled with its state
   from the join's fields, in the hub's order: revoked, used, burned
   (refused after three wrong codes), expired. Expiry is judged by the
   hub's clock (this browser's, corrected by the `Maity-Server-Time` of
   the last answer) while the view is open, so a join that expires on
   screen moves down without a reload; for a minute after it expired it
   keeps **Revoke**, and the hub decides. A Revoke the hub refuses
   (`invalid_transition`) is said and the list re-read.
8. **Why** (`#/p/<slug>/why`, where the hub has the Keep the Why export,
   `docs/api.md` §11.3): the project's published Keep the Why dashboard
   state as the hub read it, read-only. A headline says how many entries
   need attention (open, needs review, pending confirmation) out of how
   many, in how many parts of the family (the repository's root and the
   children its `.keep-the-why` names), with the linter's counts and when
   the hub read it; **Read again** asks for a fresh read (`max_age=0`), in
   every state, and is off while its read runs.
   The entries that need attention follow, grouped by part, each linking
   to its entry in the published dashboard (only a link under that part's
   own dashboard is used); then one row per part with its
   counts and a link to its dashboard. A part that could not be read is
   named with the reason in words and its last good read. When the root
   cannot be read, the last good answer is shown and said so; when the
   project publishes none (`ktw_not_configured`), the view says what the
   hub reads (the root `.keep-the-why`'s `dashboard-state` line). Every
   string from an export is text; a link is used only when it is plain
   `https`.
9. **Runners** (`#/p/<slug>/runners`, owner and admin, `docs/api.md`
   §15.4): the runners allowed to start agents for this project, by name,
   each in the words of the Runners view (presence, what it runs on, its
   tools, who can see what) with when it was allowed and how many agents
   it runs here. A revoked runner says it starts nothing until it is
   paired again, one never paired (attached through an enrollment) that it
   starts nothing until it is; one whose own configuration does not list
   the project says it starts nothing here, whatever the hub allows.
   **Allow it here** attaches one of the human's own runners not yet
   attached (`POST /projects/{slug}/runners`; one attached meanwhile is
   said, not a failure); **Detach** asks first, naming the agents whose
   placements the hub then closes and the runner stops, counted when it is
   pressed. After either, the status line has the focus and says what
   happened. The 30-second refresh redraws only what changed and keeps the
   focus on the same control (in the **Allow** form too, when it is rebuilt
   for a new runner) and the runner chosen there. Without runners, the view
   points to pairing one; a refusal of the list fails loud like every
   view. The tab is the project admin's; a runner's owner who is no admin
   here (possible once invitations exist; not in V1) cannot detach it
   from the dashboard although the hub would let them.
10. **Overview** (`#/p/<slug>/overview`, `docs/api.md` §6.11; its tab is
    the second, next to the inbox): the project at a glance.
    - Links: the repository and each Keep the Why dashboard of the family,
      with its attention count and a part's error, plus the policy preset.
      A link is used only when it is plain `https`, in a new tab with
      `rel="noopener noreferrer"`; anything else is text.
    - Members by role, with how many are humans, agents and online.
    - The board's count per column, over the board's 14-day window for
      done and cancelled, each linking to the board (the board has no
      route to one column or card yet, so a report links there too).
    - Open requests, those for oneself and by priority, linking to the
      inbox.
    - The latest reports: author, card, when, the pull request with the
      state the probe saw, and a mismatch said.

    Links and members come from what the header already read. The counts
    come from `GET …/overview`, which is read again on `task_*`,
    `request_*` and `probe_observed` and redrawn in place, with no Reload;
    for a viewer who is neither owner nor admin (in few events' audiences)
    also every 60 seconds and when the tab or its window comes back. Triggers during a
    read give one more read after it; the focus stays on the same link. A
    family cut at the hub's limit and a failed Keep the Why read are said.
    Each part has its empty state. Without a repository or a published
    dashboard, an owner or admin gets **Set the repository** (it opens
    Project settings at the repository) and is told where the Keep the Why
    link comes from. A hub without the endpoint
    still shows the links and members, and says that the counts are
    missing.
11. **Messages** (`#/p/<slug>/messages`, `docs/api.md` §8.4): the
    project's messages the reader may see, every type but chat, newest
    first, with a filter by type and **Message the project**.
    - Each says its type, who wrote to whom, the card it is about (linking
      to the board) and when; the text as Markdown, the members it
      mentions as links to them, and its files (§8.7: images inline,
      everything else as a download). The sender or an admin deletes a
      file.
    - An owner or admin removes a message with a reason (§8.5); a removed
      one says by whom and why, and shows only without a type filter.
    - The contract has no message listing: the view reads the project's
      events from the start with `wait=0`, page by page, and keeps the
      messages. New messages, removals and deleted files arrive with the
      project's feed.

**For a first-time human**, the empty inbox and the empty board say where
their content comes from (the agents' requests; the cards the agents
propose), the paste line of a join says where it goes (to the agent as a
message, or run in a terminal in the agent's clone), and a tab row wider
than the screen fades on the side where more entries are.

**Runners** (`#/runners`, `docs/api.md` §15.2–§15.3). One card per runner
in plain words: online, away or offline with when it was last seen, or
revoked; what it runs on (this machine, hosts, or pods in a namespace);
for each host or pool how many agents run of how many, and whether it is
reachable; its tools with versions, how each is kept in bounds (its
command allowlist, or only its pod) and how it runs (a session you can
attach to, or woken by events with no open session), and the ones that
are not installed; who can see what (one user for all agents, a user per
agent, or a pod each); which projects and repositories its own
configuration allows; its credential's id and dates, never its value.
**Pair a runner** creates a pairing (`POST /runners/enrollments`) with a
name, the projects to allow it in and how long the line stays valid, and
shows the steps for the machine (the name follows the handle rule, said
under the field): install the CLI (from the repository's
current main, which has `maity runner pair` and `maity runner check`;
the page says so),
save the **starter configuration** generated in the browser as
`~/.config/maity-runner/runner.toml`, run the pairing line (shown once,
gone after leaving the view, and replaced by a note once it is used or
expired), then `maity runner check` and `maity runner serve` (available
once the runner track lands; the page says so). The
configuration holds only the keys without a default: this pairing's hub
URL, the chosen projects and their repositories, the local backend's
layout and Claude Code's modes and models; no secret. Its "copy as a
command" form never overwrites an existing file (`set -C`) and writes
it owner-only (`umask 077`). The panel
says when the runner has paired (for a re-pair: when its credential is a
new one) and when it is online (the view re-reads every 30 s). Open pairings are listed and
revocable. Each runner can be renamed, re-paired (a new line for the same
runner; the old credential ends at the exchange), revoked, and removed;
removing lists the agents that were still running on it, which are then
the operator's to end on that machine (`maity runner stop-all`, available
once the runner track lands).

**Users of this hub** (`#/admin/users`, `docs/api.md` §16.1) lists the
instance's humans for the instance admin, by handle: name and handle
("(you)" for oneself), whether instance admin, active or disabled, when
created, last signed in and last seen, and how many projects they are in
and how many agents they own — counts and times only; being the instance
admin opens no project, and the view links into none. A search by handle
or name (case-insensitive, 1–64 characters, read 300 ms after typing
stops) and a filter by active or disabled ask the hub (`q`, `disabled`);
**Load more** follows its cursor. A hub without the list (404) says so;
anyone else gets neither the link nor the list. On a phone each row is a
card.

**Pictures** (`#/account/picture`, `docs/api.md` §6.10). The account
shows the human's picture as it shows now, where it comes from (uploaded,
the linked forge account, or generated from the member id), an upload and,
for an upload, **Remove the upload**; below it the same for each of the
human's agent profiles (`GET /agents`, `PUT`/`DELETE /agents/{id}/avatar`).
The file is checked as the hub checks it before it is sent: PNG, JPEG or
WebP by its first bytes, at most 1 MiB; it goes as the raw body with the
sniffed type (`PUT /me/avatar`). The hub's refusals (`dimensions`,
`undecodable`, the hourly limit, a hub without the endpoint) are said in
words. After a change the page is drawn again from `/me`, so the header's
picture follows at once. There is no preview of a chosen file before the
upload: the hub's CSP allows no `blob:` images, and what shows afterwards
is what the hub made of it (a square of at most 256 pixels).

**Change password** (`#/account`) sends `POST /auth/password {current,
new}` (`docs/api.md` §2.1): the new password twice, at least 12
characters (counted as the hub counts them), checked before sending; a
wrong current password is shown at its field (`current: mismatch`, which
also counts against the sign-in limit), and success says that every other
session of this human was signed out while this one stays signed in.

**Create a project** (`#/new`) sends `POST /projects` (`docs/api.md`
§6.1): name, a slug proposed from the name (`[a-z0-9][a-z0-9-]{1,62}`,
its rule said under the field and checked before sending), an optional repository URL, Keep the Why, and
the policy preset (`hierarchical` or `solo`). The creator becomes the
owner. On `201` the page opens the new project's Agents view, whose empty
state offers **Join an agent**. The hub's `invalid` answer is shown under
each field it names in `details.fields` (`slug: taken`,
`repository.url: not_a_configured_forge`, …).

**Logo and banner** (`docs/api.md` §11.2). Each project shows its own
logo next to its name: in its switcher chip, in the header, on its
entries in `#/all`, and as the tab's icon of its pages. The image comes
from the hub's own path (`/api/v1/projects/<slug>/logo?v=<etag>`), read
from `/me`'s projects where the hub puts `logo` there (`docs/api.md` §5.1), else from `GET /projects` alongside `/me`. Without one, a monogram stands
there: the project's initials in white on one of twelve colours (each at
least 5.2:1), chosen by the slug. The mark is decorative next to the
project's visible name (`alt=""`, `aria-hidden`); a monogram cannot be the
tab's icon (the hub's CSP allows no `data:` or `blob:` images), so that
tab keeps the browser's default. The banner, where the project has one,
heads the project's inbox. In **Project settings** a human with
`project:admin` sees what shows now and where it comes from (uploaded or
the repository's forge), uploads a logo or a banner (PNG, JPEG or WebP,
at most 1 MiB; the type is read from the file's first bytes, as the hub
reads it, and sent as the raw body) and removes an upload, after which
the forge's image applies again. A hub without the fields offers no
upload and the dashboard draws monograms.

**Repository** (`docs/api.md` §6.1) is in the same panel, for an owner
or a human admin (`project:admin` is held by humans only). It shows the
project's repository URL and changes it with `PATCH /projects/{slug}`
(`repository: {url}`); an empty field removes it (`repository: null`).
The page accepts only `https://<host>/<owner>/<name>`, drops a trailing
slash, and says the hub's `not_a_configured_forge` at the field. A
change or a removal is confirmed first, because the probe, the Keep the
Why dashboard and the runners' new clones all follow the repository.

**Agent signing** (`policy.signing`, `docs/api.md` §2.2, §6.1) is in the
same panel for owner and admin, where the hub's policy has the field:
optional or required, with a reason. Before it becomes required, the
panel reads every agent's credentials and lists those last used as a
bearer token (`last_used_via`, §10): they would be refused with
`signature_required` until they sign, and the switch then needs an
explicit confirmation. The Agents view shows on each credential how it
was last used, signed or as a bearer token.

The project state (build, freeze, fixes-only, accepted, archived) is in
the header of every screen; owner and admin change it there with a
reason (**Project settings**), and the owner sets and clears the absence
shown under it.

**Avatars**: every member has a picture, generated from its member id —
a mirrored 5×5 pattern and a hue (FNV-1a of the id), so every client draws
the same one — as SVG nodes, decorative next to the name; the theme sets
its lightness and background, so it reads in light and dark. A member
that carries an `avatar_url` the page may load (only the hub's own
`/api/v1/avatars/<id>?v=…`, never another origin) shows that one instead,
and falls back to the generated one when the image does not load (a
`404` once access has ended). On the agents' cards, in the
organisation and in the chat list.

**Message the project** (`#/p/<slug>/message`, no tab: **Message the
project** in the inbox's toolbar, and from a chat: an `@name` typed there
is said to notify nobody, with a link to a project message that has it
already written) posts a message (`POST /projects/{slug}/events`, `docs/api.md`
§8.4): to everyone, a role or one member (never oneself), of one of the
hub's types (a notice by default), optionally about an open card. The
hub scans the body: a mention adds that member to whom it reaches and
tells them (§8.6), and the page says whom, from the event's mentions; it
never sends a mentions list. The body has the @ picker (below).
An empty message, or one over 16,384 characters, is not sent; the hub's
mention cap and rate are said in words.

**Mentions** (`docs/api.md` §8.6). Where the dashboard shows a text the
hub scans — a request's summary, what it tried and the answer's text,
a report's summary — each mention the hub stored for that field is a
link to the member (`#/p/<slug>/members/<id>`), taken from the text at
its offset (code points) only where it reads `@` and the stored handle;
nothing typed becomes a link. The **@ picker** in the inbox's free text
offers the project's members by handle (`GET …/members`, read on the
first `@`), never the writer: arrow keys choose, Enter or Tab puts
`@handle ` in, Escape closes; an `@` inside a word or in inline code
offers nothing. The picker only helps to type; the hub resolves.

**Buttons** sit at the right edge of their form, panel or card. In a row
the secondary ones come first and the primary one last (Cancel, Save;
Later, "Neither — let's talk", the replies with the primary one last;
Hide, Copy), in that order in
the page too, so the tab order is the order on screen; destructive ones
(Revoke, Remove) stand apart. On a phone (≤ 600 px) they stack, full width.

## Fixture mode

`js/api.js` is the only place that knows where data comes from: a page
opened from `file://` reads the fixtures, a page served over `http(s)`
reads the API at `/api/v1`, and nothing switches between the two. The
fixture bundle is not referenced from `index.html`; `api.js` loads it on
the first fixture request, so the hub's origin never has it, and an API
error offers no way into fixture mode (`context/fixtures.md`). Fixture
mode is labelled **Fixtures** in the header. Every write in fixture mode (answers, messages, revocations,
pauses, state, absence, joins, created projects) changes an in-memory copy and is gone on
reload. `?signed_out=1` starts fixture mode without a session, to show
the sign-in (handle `maintainer`, any password); `?no_projects=1` starts
it without memberships, to show the empty state; `?as=<member id>` makes
the mock take membership changes as coming from that member, to show how
the hub answers an admin agent (`docs/api.md` §2.3 ᵃ: a reviewer's role or
pause and any removal answer 202 with a consent request to the owner). A project created there
gets empty fixtures and the github.com forge rule.

The fixtures are in `fixtures/`: `me.json`, `auth-session.json`,
`agents.json`, and one directory per project (`maity/`, `sample/`) with
one JSON file per endpoint, in the shapes of `docs/api.md`:

| Endpoint (below `/api/v1`) | Fixture |
|---|---|
| `GET /auth/session`, `POST /auth/login`, `POST /auth/logout` | `auth-session.json` |
| `GET /me` | `me.json`; `open_requests` and `server_time` are derived |
| `GET /agents` | `agents.json` |
| `GET /requests` (cross-project) | derived: the open requests of every project, each with `project` `{slug, name, state}` |
| `GET`, `PATCH /projects/{slug}` | `{slug}/project.json` |
| `GET /projects/{slug}/members`, `PATCH …/members/{id}` (`paused`) | `{slug}/members.json` |
| `GET /projects/{slug}/requests`, `POST …/requests/{id}/answer` | `{slug}/requests.json` |
| `GET /projects/{slug}/tasks` | `{slug}/tasks.json` |
| `GET /projects/{slug}/members/{id}/credentials`, `POST …/credentials/{id}/revoke` | `{slug}/credentials.json`, keyed by member |
| `GET`, `POST /projects/{slug}/joins`, `DELETE …/joins/{id}` | `{slug}/joins.json`; a created join gets a made-up `FIXTURE` line |
| `GET /projects/{slug}/conversations` | derived from `{slug}/conversations.json` |
| `GET`, `POST /projects/{slug}/conversations/{agent-id}/messages` | `{slug}/conversations.json`, keyed by agent |

Lists follow `next_cursor` (`Maity.api.getAll`); the fixtures answer in
one page. Because a page loaded from `file://` cannot `fetch()` a local
file, the page reads `fixtures/fixtures.js`, a generated bundle of the
JSON files. After editing a fixture, run `make fixtures`; `make check`
fails while the bundle is stale.

## Refresh

- `GET /me` every 15 seconds and after every answer, for the switcher's
  counts. When the number of open requests on screen changes, the page
  offers **Reload the list** rather than replacing it while the human is
  reading. A list with no open entry on screen, where nothing is being
  read or typed, reloads on its own and says "1 new request." in its
  status line, for a screen reader too, unless the **Project settings**
  panel is open or a header control has the focus. Only the switcher is redrawn: an open **Project settings** panel,
  what is typed in it, and how far a tab row is scrolled stay.
- In a project, the project's events (`docs/api.md` §8.3): the head is
  read with `after=latest&wait=0` together with the project and its
  members, then `after=<cursor>&wait=0` every 5 seconds, page by page.
  Not the long-poll: `context/refresh.md`.
  - a request event re-reads `/me` at once;
  - a card event (`task_*`) on the board, a member, session or
    credential event on Agents, a member event on Organisation, and a
    state, absence, policy or rules change anywhere offer **Reload** when
    someone else caused them;
  - a chat event of the open conversation fetches its new messages
    (`?after=<cursor>`).
- Presence emits no event; the Agents view re-reads the members every
  30 seconds and updates presence and "last seen" in place.

## Checks

```sh
make check   # structure, Python standard library only
make smoke   # behaviour, needs a node binary (no packages)
make starter-configs   # the Runners view's configurations through maity runner check
```

`make starter-configs` runs `tools/starter_configs.py`: the starter
configurations the Runners view generates for one project, two (one
repository URL with `.git`, one with a host in capitals), a project
without a repository and none, each written by the page's own "copy as a
command" into a throwaway HOME under umask 002. The file has to be
exactly the configuration, owner-only, not overwritten by a second run,
and loaded by `maity runner check --offline` without a word about the
file; what check says about the machine is ignored. It needs `node`,
`bash` and `maity` from `cli/` (Python 3.11+); CI runs it in the
`web-e2e` job, where the CLI is installed.

`make smoke` runs `tools/smoke.js`: the page's scripts against a minimal
DOM shim, walking every view in fixture mode and against a fake hub in
API mode (`context/stack.md`). CI runs both in the `web` job of
`.github/workflows/ci.yml`.

Python 3 standard library only (`tools/check.py`): every project in
`me.json` has its fixture files, fixture JSON, bundle freshness; `index.html` structure (balanced tags, doctype, lang,
charset, viewport, title, unique ids, labels, local references, every
script loaded, no inline script, style or handler); JavaScript bracket
balance and a lint that refuses `innerHTML` and the other HTML-parsing or
code-evaluating calls (`context/rendering.md`), the native
`append`/`prepend` outside `js/dom.js` (it would insert the text "null"
for a missing child), `var`, `console` and `debugger` — and at run time
`Maity.dom.h` refuses a string `on*` handler and any `href`/`src` that is
neither a route nor an `https://` URL; CSS brace
balance and defined custom properties; whitespace.
When a `node` binary happens to be on the PATH, each script also goes
through `node --check`; it is not required, and the check says when it
was skipped.

The structure check is not a full HTML conformance validator, and the
smoke test is not a browser: layout, CSS and real events are outside
both. The browser end-to-end test below covers one path through them;
what else a change looked like in a browser is stated in its pull
request.

## Browser end-to-end test

```sh
pip install -e hub -e cli playwright==1.64.0   # from the repository root
python -m playwright install chromium          # --with-deps on a fresh machine (root)
make -C web e2e                                # or: python web/tools/e2e.py --artifacts DIR
```

`tools/e2e.py` starts a real hub (`maity-hub`) on a free loopback port
with a throwaway SQLite file, serving this checkout's `web/`, and drives
the dashboard in headless Chromium with Playwright for Python; the agent
is the `maity` CLI in scratch git clones (`context/stack.md`). One run:

1. the owner is created with `maity-hub owner create`; sign-in; the empty
   state;
2. **Create a project**; the join line from **Join an agent**; the agent
   runs it (`maity join`) and is listed under **Agents**;
3. the agent creates and claims a card; the open board offers
   **Reload** and then shows the claim;
4. the agent asks (`maity ask --task`), which blocks the card; the empty
   inbox reloads on its own and shows the request, and the switcher counts
   it; the agent starts `maity wait`;
5. the owner answers with a reply button; the inbox empties, the count
   goes, `maity wait` exits with `request_answered` for that request, and
   the card is no longer blocked;
6. a second project, the same agent profile joins it from a second clone
   and asks there, and asks once more in the first, with priority `high` (`urgent` needs `requests:answer`);
7. the switcher counts both projects and **All projects**; switching
   lands in the other project with its request open;
8. `#/all` lists both requests, the `high` one first, each with its project,
   and answers them there, one in free text, one with `go`; the agent's
   `maity resume` sees that answer;
9. **Chat**: the agent writes with `maity say human`, the message appears in
   the open conversation; the owner answers there, the agent's `maity wait`
   wakes with that message, and after a reload it is "reached a session";
10. **Pause**: the owner pauses the agent with a reason; the agent's own
    `PATCH /me` is refused (`forbidden`, a human paused it), its `resume`
    does not lift it and its packet shows it (`membership.paused`, by the owner); the owner
    clears it, and the agent then sets and lifts a pause of its own; the
    form and the paused card say what a human's pause does. Where the hub
    knows briefings, the owner writes one on the card and the agent's
    `resume` packet carries it; where it does not, no editor is offered.
    **Members**: the owner in the humans table, the agent in the agents
    table (credentials only where the hub sends them); the agent's role
    changed to reviewer and back through **Manage**; the agent put under
    the owner, which the Organisation view shows at once; the owner put
    under the agent refused as a circle before it is sent; reports-to set
    back to nobody;
11. **State & absence** (in **Project settings**): the owner freezes the project with a note and a
    reason and sets an absence; the header shows both, the switcher's state
    dot differs from the building project's, and the agent's `resume`
    packet carries the state, the note and the absence; then back to build
    and "I am back", which the packet shows too;
12. **Release and contract**: a reviewer joins through the dashboard
    (role `reviewer`), opens a release over the claimed card and a
    `ships_with` partner, types PR #7 as merged and adds a contract card
    watched by the first agent. Without a forge probe the board shows #7
    as unverified (not merged), the reason in words and that the release
    cannot be done; the group, the tag as not observed, and the contract's
    watchers. The owner then adds a checklist item on the board, ticks it
    and types PR #8 as open; the hub's task view shows the tick by the
    owner and both typed PRs. Cancelled, the release moves to Cancelled as
    a frozen record without any editing, and the hub refuses an edit
    (`invalid_transition`);
13. **Signing**, where the hub has `policy.signing`: the agent makes one
    call with its bare bearer credential; the Agents view shows it, and the
    switch to required lists the agent and refuses to send without the
    confirmation; once required, the bearer call answers 403
    `signature_required` while the CLI's signed calls go on; then back to
    optional. Without the field, no switch is offered;
14. **Logo and banner**, where the hub has them: the e2e project has no
    repository, so a monogram shows; a text file named as PNG is refused
    before sending; a generated PNG becomes the logo in the header, the
    switcher and the tab's icon (loaded from the hub at its real size); a
    banner heads the inbox; the hub's project view says both are
    uploaded; removing the logo brings the monogram back. Without the
    fields, monograms and no upload;
15. **Runners**: the empty view; a pairing for `e2e-runner` with the
    starter configuration (this hub, both projects) and the line; the
    line's exchange done as `maity runner pair` would (`POST
    /runners/pair/{token}`), after which the panel says the runner is
    paired and its card says offline, never connected, with the credential
    id from the exchange; rename; re-pair, whose exchange replaces the
    credential; revoke; remove with nothing left running. Only a hub
    that answers 404 on `GET /runners` skips this step. Before the
    revoke, in **Project → Runners**: the runner (allowed while pairing,
    then detached, where the hub can) is allowed in the project and
    detached again, each detach confirmed with "Nothing runs on it
    here."; a hub without attachments has to say so in the tab;
16. **Why**, where the hub has the export: the e2e project has no
    repository, so the view says it needs one (the hub's
    `ktw_not_configured`); without the field, no Why tab;
17. at phone width (390 px) the inbox, board, agents, members, organisation, join and (where offered) Why
    and Runners views, each reached through its tab, and the instance's Runners view load without an error, none of
    them scrolls sideways, the current tab and project stay visible in
    their rows, the tab row shows its scroll fade (and at 1280 px neither
    row does), and every Revoke label stays on one line.

**Accessibility:** axe-core (`AXE_VERSION` in the script, the npm tarball
checked against its pinned sha512 and read without npm; `context/stack.md`)
runs on each view as the scenario reaches it: sign-in, the empty state,
Agents (empty, with an agent, with a human pause, with a briefing where
the hub has one), Join with a paste line, the board (a claimed card, a
release with a contract, the release edited, a typed-PR editor open),
the inbox with an open request, `#/all` with requests, chat, the header
in freeze with an absence, Organisation and Create a project. Each check
runs at 1280 and 390 px in the light scheme and at 1280 px dark, with the
tags WCAG 2.0/2.1 A and AA, WCAG 2.2 AA and best practices. A serious or
critical violation fails the run after the last step; every finding is in
`a11y.json` and `a11y.txt` next to the screenshots. `--axe-cache` names
where the tarball is kept between runs (default: a directory in the
system temp dir).

Every step leaves a screenshot (`NN-<step>.png`) in `--artifacts` (by
default a temp directory, kept), with the join line painted over; the
hub's output (`migrate`, `owner create`, `serve`) goes to `hub.log` next
to them. Any console error, page error, failed request (other than one
the page cancelled) or API answer of 400 or more fails the run, except
the 401 of the signed-out session check. The hub is the one process the
script starts, and it is stopped by its own PID, also on Ctrl-C; port
8090 is refused, and a port that another server already answers on is
refused too. The caller's own `MAITY_*` variables are dropped for the hub
and the CLI. Option `--headed` shows the browser, `--port` fixes the port.

CI runs it in the `web-e2e` job of `.github/workflows/ci.yml`. It installs
the headless shell only (`playwright install --only-shell chromium`) and
checks it with `ldd`; only when a library is missing does it install a
fixed minimal list from apt (`libnss3`, `libnspr4`, `libasound2t64`), and a
library still missing then fails the job before the test. The job uploads
the screenshots and `hub.log` as the workflow artifact
`web-e2e-screenshots`, also when a step fails.

## Layout

```text
web/
├── index.html        the page; loads the scripts in order
├── css/app.css       one stylesheet, light and dark tokens
├── js/dom.js         element builder, text only; https-only links
├── js/markdown.js    Markdown as DOM nodes, for chat messages
├── js/avatar.js     generated member pictures (identicons)
├── js/menu.js       the header's menus (a button and its menu)
├── js/mentions.js    the @ picker
├── js/api.js         the fetch layer: fixtures or /api/v1
├── js/app.js         project switcher, header, navigation, router
├── js/inbox.js       (1) inbox, per project and across all
├── js/board-edit.js  managing cards: new card, the allowed moves, assign
├── js/board.js       (2) board
├── js/agents.js      (3) agents and presence
├── js/members.js     (4) members: humans and agents, managed by an admin
├── js/org.js         (5) organisation tree
├── js/project-message.js message the project (§8.4)
├── js/attachments.js  files on messages: attach, show, delete; the admin's pending list
├── js/chat.js        (6) chat
├── js/group-chat.js  (6) group chats: create, open, manage, remove a message
├── js/observe.js     reading along in a project one is not in
├── js/join.js        (7) join an agent
├── js/why.js         (8) why: the Keep the Why export
├── js/overview.js    (10) overview: the project at a glance
├── js/messages.js    (11) the project's messages, by type
├── js/new-project.js create a project; the empty state
├── js/account.js     the account: pictures and changing the password
├── js/admin-users.js the users of this hub, for the instance admin
├── js/runners.js     the runners: pair, list, rename, revoke, remove
├── js/project-runners.js  Project → Runners: allow and detach
├── fixtures/         me.json, auth-session.json, agents.json, <slug>/ per endpoint, fixtures.js
├── tools/check.py    make check
├── tools/smoke.js    make smoke
├── tools/starter-configs.js  the starter configurations, as JSON
├── tools/starter_configs.py  make starter-configs
├── tools/e2e.py      make e2e: the browser end-to-end test
└── context/          why the dashboard is built this way (Keep the Why)
```
