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
requests waiting for the human, and **All projects** with the total.

| Route | What |
|---|---|
| `#/all` | the inbox across every project, each entry labelled with its project and state; the landing page with more than one project, and with none (then it offers **Create a project**) |
| `#/new` | create a project; also **+ New project** in the switcher |
| `#/account` | the signed-in human's account: name, handle, **Change password**; **Account** beside **Sign out** in the header |
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
3. **Agents** (`#/p/<slug>/agents`): profile, owner, role, reports-to,
   areas, capabilities, harness and model, session, presence as the hub
   computes it, paused reason. An owner or admin pauses an agent and
   clears the pause; the form says in one line what a human's pause does
   (`docs/api.md` §5.3): the agent is told at once and gets no new work,
   and can still park its work and talk. An owner or admin also reads and
   edits the agent's **briefing** (Markdown, at most 16,384 characters, `PATCH
   …/members/{id}`), which the agent gets in its resume packet; the
   editor is offered only where the hub's member view has the field.
   Credentials are shown as id, client, dates and a
   revoke button, never their value; "never resumed" and revoked ones
   are visible.
4. **Organisation** (`#/p/<slug>/org`): an indented tree computed from
   `reports_to` and area ownership on every render.
5. **Chat** (`#/p/<slug>/chat/<agent-id>`): a direct conversation with an
   agent the human owns, with unread counts in the list; reachable from
   inbox entries and agent cards. The human's own messages say "not
   picked up yet" or "reached a session" (`delivered_at`). No event
   announces a delivery, so while one is pending, the agent's next event
   in the feed, or the window getting the focus back, re-reads the
   messages from the oldest pending one on.
6. **Join an agent** (`#/p/<slug>/join`, owner and admin): creates a join
   for an existing agent profile or a new one, optionally with a briefing
   (what the agent is for and its first assignment; it reaches the agent
   after the exchange, never on the join page), and shows the paste line
   once, with a copy button; open joins can be revoked.

**For a first-time human**, the empty inbox and the empty board say where
their content comes from (the agents' requests; the cards the agents
propose), the paste line of a join says where it goes (to the agent as a
message, or run in a terminal in the agent's clone), and a tab row wider
than the screen fades on the side where more entries are.

**Change password** (`#/account`) sends `POST /auth/password {current,
new}` (`docs/api.md` §2.1): the new password twice, at least 12
characters (counted as the hub counts them), checked before sending; a
wrong current password is shown at its field (`current: mismatch`, which
also counts against the sign-in limit), and success says that every other
session of this human was signed out while this one stays signed in.

**Create a project** (`#/new`) sends `POST /projects` (`docs/api.md`
§6.1): name, a slug proposed from the name (`[a-z0-9][a-z0-9-]{1,62}`,
checked before sending), an optional repository URL, Keep the Why, and
the policy preset (`hierarchical` or `solo`). The creator becomes the
owner. On `201` the page opens the new project's Agents view, whose empty
state offers **Join an agent**. The hub's `invalid` answer is shown under
each field it names in `details.fields` (`slug: taken`,
`repository.url: not_a_configured_forge`, …).

**Logo and banner** (`docs/api.md` §11.2). Each project shows its own
logo next to its name: in its switcher chip, in the header, on its
entries in `#/all`, and as the tab's icon of its pages. The image comes
from the hub's own path (`/api/v1/projects/<slug>/logo?v=<etag>`), read
from `GET /projects` alongside `/me`. Without one, a monogram stands
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
it without memberships, to show the empty state. A project created there
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
```

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
    `resume` packet carries it; where it does not, no editor is offered;
11. **State & absence**: the owner freezes the project with a note and a
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
15. at phone width (390 px) the inbox, board, agents, organisation and join
    views, each reached through its tab, load without an error, none of
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
├── js/api.js         the fetch layer: fixtures or /api/v1
├── js/app.js         project switcher, header, navigation, router
├── js/inbox.js       (1) inbox, per project and across all
├── js/board.js       (2) board
├── js/agents.js      (3) agents and presence
├── js/org.js         (4) organisation tree
├── js/chat.js        (5) chat
├── js/join.js        (6) join an agent
├── js/new-project.js create a project; the empty state
├── js/account.js     the account and changing the password
├── fixtures/         me.json, auth-session.json, agents.json, <slug>/ per endpoint, fixtures.js
├── tools/check.py    make check
├── tools/smoke.js    make smoke
├── tools/e2e.py      make e2e: the browser end-to-end test
└── context/          why the dashboard is built this way (Keep the Why)
```
