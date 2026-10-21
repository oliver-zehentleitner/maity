# Maity dashboard (`web/`)

The signed-in dashboard the hub serves at `/`: what the agents want from
the human, the board, the agents and their presence, the organisation,
and the chat with the agents the human owns. Static HTML, vanilla
JavaScript and CSS: no framework, no build step, no Node toolchain. The
public site at maity.dev is `docs/index.html`, not this.

## Open it

- **From the file system:** open `web/index.html` in a browser. A page
  loaded from `file://` runs in fixture mode on its own.
- **Over HTTP without the hub:** `make serve`, then open
  `http://127.0.0.1:8070/?source=fixtures` (`HOST=` and `PORT=` override
  the address).
- **From the hub:** the hub serves this directory at `/`, and the page
  talks to `/api/v1/...` on the same origin with the hub's HttpOnly
  session cookie. Every request that is not GET or HEAD carries the
  readable `maity_csrf` cookie's value as `X-CSRF-Token` (double submit);
  a mismatch comes back as 403 `csrf_mismatch` and is shown as an error.

## Projects and routes

One account holds many projects. The header of every screen has a
project switcher: each project with its state and the number of open
requests waiting for the human, and **All projects** with the total.

| Route | What |
|---|---|
| `#/all` | the inbox across every project, each entry labelled with its project and state; the landing page with more than one project |
| `#/p/<slug>/<view>` | a view inside one project; `#/p/<slug>/inbox` is the landing page with exactly one |
| `#/p/<slug>/chat/<agent-id>` | the chat with one agent |

## Views

Inside a project, in the order of their importance; see
`context/views.md` for why.

1. **Inbox** (`#/p/<slug>/inbox`, the first screen): each agent's open requests,
   sortable by priority, date and agent. The first open entry is expanded
   with its context (task, what the agent tried, the options it sees) and
   is answered with a prepared reply, free text, or "Neither — let's talk";
   answering opens the next one.
2. **Board** (`#/p/<slug>/board`): cards by status with claim holder, lease and
   dependencies; releases are a card kind with their pull requests as the
   hub observed them, and a readiness line computed from that state.
3. **Agents** (`#/p/<slug>/agents`): profile, owner, role, reports-to, scopes,
   harness and model, live session, last seen, paused reason. Credentials
   are shown as id, creation date and last use with a revoke button,
   never their value.
4. **Organisation** (`#/p/<slug>/org`): an indented tree computed from
   `reports_to` and scope ownership on every render.
5. **Chat** (`#/p/<slug>/chat/<agent-id>`): a direct conversation with an agent the
   human owns; reachable from inbox entries and agent cards.

The project state (build, freeze, fixes-only, accepted, archived) is in
the header of every screen.

## Fixture mode

`js/api.js` is the only place that knows where data comes from:

| Page opened from | Source |
|---|---|
| `file://` | fixtures |
| `http(s)://` | the API at `/api/v1` |
| any, with `?source=fixtures` or `?source=api` | as given |

The source is chosen once per page load. When the API fails, the page
shows the error and a link to open it with fixtures; it never switches to
fixtures on its own, and fixture mode is labelled **Fixtures** in the
header. Answers, chat messages and revocations in fixture mode change an
in-memory copy and are gone on reload.

The fixtures are in `fixtures/`: `me.json`, and one directory per project
(`maity/`, `sample/`) with one JSON file per endpoint, shaped like the
answer the views expect:

| Endpoint (below `/api/v1`) | Fixture |
|---|---|
| `GET /me` (memberships with `open_requests`) | `me.json`; the counts are derived from the request fixtures |
| `GET /requests?scope=all` | derived: the open requests of every project, each with `project` `{slug, name}` |
| `GET /projects/{slug}` | `{slug}/project.json` |
| `GET /projects/{slug}/members` | `{slug}/members.json` |
| `GET /projects/{slug}/requests` | `{slug}/requests.json` |
| `POST /projects/{slug}/requests/{id}/answer` | updates `{slug}/requests.json` |
| `GET /projects/{slug}/tasks` | `{slug}/tasks.json` |
| `GET /projects/{slug}/members/{id}/credentials` | `{slug}/credentials.json`, keyed by member |
| `POST /projects/{slug}/credentials/{id}/revoke` | updates `{slug}/credentials.json` |
| `GET /projects/{slug}/conversations/{agent-id}/messages` | `{slug}/conversations.json`, keyed by agent |
| `POST /projects/{slug}/conversations/{agent-id}/messages` | updates `{slug}/conversations.json` |

Every request carries who asked inline (`asked_by`, and `on_behalf_of`
where it was raised for someone else: `{profile_id, display_name, role,
session_id}`), so the cross-project inbox renders from the requests alone.

These are a proposal until `docs/api.md` exists; the two get reconciled
then. Because a page loaded from `file://` cannot `fetch()` a local
file, the page reads `fixtures/fixtures.js`, a generated bundle of the
JSON files. After editing a fixture, run `make fixtures`; `make check`
fails while the bundle is stale.

## Checks

```sh
make check
```

Python 3 standard library only (`tools/check.py`): fixture JSON and
bundle freshness; `index.html` structure (balanced tags, doctype, lang,
charset, viewport, title, unique ids, labels, local references, every
script loaded, no inline script, style or handler); JavaScript bracket
balance and a lint that refuses `innerHTML` and the other HTML-parsing or
code-evaluating calls (`context/rendering.md`), the native
`append`/`prepend` outside `js/dom.js` (it would insert the text "null"
for a missing child), `var`, `console` and `debugger`; CSS brace balance and defined custom properties; whitespace.
When a `node` binary happens to be on the PATH, each script also goes
through `node --check`; it is not required, and the check says when it
was skipped.

This is a structural checker, not a full HTML conformance validator, and
none of it runs the page. What a change looked like in a browser is
stated in its pull request.

## Layout

```text
web/
├── index.html        the page; loads the scripts in order
├── css/app.css       one stylesheet, light and dark tokens
├── js/dom.js         element builder, text only
├── js/api.js         the fetch layer: fixtures or /api/v1
├── js/app.js         project switcher, header, navigation, router
├── js/inbox.js       (1) inbox, per project and across all
├── js/board.js       (2) board
├── js/agents.js      (3) agents and presence
├── js/org.js         (4) organisation tree
├── js/chat.js        (5) chat
├── fixtures/         me.json, <slug>/ JSON per endpoint, generated fixtures.js
├── tools/check.py    make check
└── context/          why the dashboard is built this way (Keep the Why)
```
