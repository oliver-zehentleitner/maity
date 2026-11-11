# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); a version
is the hub's, spelled as its tag and PyPI spell it, in
[PEP 440](https://peps.python.org/pep-0440/) (`0.1.0a2`).

Keep a Changelog records what changed. Why it changed is in [`context/`](context/index.md).

## [Unreleased]

Unreleased changes are collected in `changelog.d/` (one file per pull request) and folded in at release.

## [0.1.0a3] - 2026-11-11

### Added

- hub: an async engine beside the sync one, on the same database and with the same options
  (psycopg 3's async mode on PostgreSQL, aiomysql on MariaDB, aiosqlite on SQLite), so the
  routes can move to `async def` family by family and run their database work through
  `AsyncConnection.run_sync` (tsk-v874y63b4z8p). No route uses it yet. New dependencies:
  greenlet, aiomysql and aiosqlite, pinned with hashes.
- hub: `MAITY_DB_ASYNC_POOL_SIZE` (default 2): on a server database (PostgreSQL, MariaDB), how
  many of `MAITY_DB_POOL_SIZE` the async engine holds; with several `MAITY_WORKERS` it is divided
  among them like the pool (at least one each). It is carved out of the pool, never on top,
  so the hub asks the database for no more connections than before; the sync engine keeps the
  rest (14 of the default 16) and the whole overflow. SQLite takes no pool sizes: each engine
  keeps SQLAlchemy's default for a file database.
- hub: a loop-lag guard in the `hub-load` job: while concurrent requests of the hot route
  families run, no tick of any test app's event loop may run more than 250 ms late (the default;
  `MAITY_LOOP_LATE_LIMIT_MS` sets another).
- web: the invite form (Members → Invite user, `/invite`) takes a person's handle (§3.4), in a
  **Handle** field before the address. An invitation by handle is sent without an address and
  without a link: the form names the person, who answers in their inbox. The hub's refusals of
  a handle (no such person, an organisation's handle, already a member, already invited, not a
  handle) are said in words. The list shows the handle each invitation is for and a declined one
  as declined.
- web: the notification settings show the kind `invitation` with its browser switch and mail
  mode (§18.4), labelled "Invitations to a project".
- hub: the notification kind `invitation` (§18.1, §18.4). The consent request of an invitation
  by handle reaches the person as an `invitation` item with its own browser switch and mail mode,
  `immediate` by default; `daily` mails invitations with the daily digest and `off` keeps them
  on the platform only, whatever the inbox's mode. The counts stay as they were.
- web: the bell, the notifications page and its `kind` filter, and the browser notifications know
  the kind `invitation` (labelled "Invitations"), so an invitation is listed and shown like the
  other kinds.
- docs/api.md §15.14: placement health. The hub asks a silent agent to check in after
  `hang_after_minutes` and nudges it after `reply_within_minutes`. These are owner settings with
  a per-profile override, and the nudge is also `POST …/placements/{id}/nudge`. The runner wakes
  or resumes the agent on the same session, or leaves it running when it has produced output
  recently or a person may be at the pane. A placement can be replaced on another runner with a
  handover (`none`, `summary`, `full`); a full transcript travels end-to-end encrypted between
  runners. New run-end reasons are `hung`, `network`, `context_full`, `auth` and
  `harness_config`. Six restarts in an hour mark a placement `flapping` and hold it until a person
  or an admin agent acts on it (a restart, a nudge, a change of the spec or a replacement).
- cli: `sudo maity runner install <pairing url> --code-file -` sets the runner up as a systemd
  system service in one step. It creates the `maity-runner` user (recorded as install's in
  `/var/lib/maity-runner-install.json`) and its directories, and writes
  `/etc/maity-runner/runner.toml` and the unit, whose `ExecStart` runs this `maity`'s
  interpreter, quoted for systemd. It then pairs as that user, enables the service and runs
  `maity runner check`. The paths are fixed; the `workspaces` a kept configuration names are not
  checked. Anything on them that is not as install would have made it (a link, another owner, a
  directory or a file of root's that others can write) stops it before any change; a mode that
  only differs from install's is set back.
  While the configuration is not one `serve` would accept, the service is enabled but not
  started. `maity runner uninstall` stops the service and its agents, then removes the unit; if
  it cannot tell that the agents stopped, it removes nothing unless `--force`, and what it can
  know beforehand is checked before the service is disabled. `--purge` also
  removes state, workspaces, the configuration and the account install made.
- cli runner: at each start the runner reads an existing clone with the same check before the
  join and the harness, and starts nothing in one whose `.git` is not a plain clone's, such as
  a `commondir` or `worktrees/` an earlier session wrote. The placement fails with
  `workspace_in_use` and the detail `not_a_plain_clone`; the runner's log names what it found,
  and nothing in the clone is removed.
- docs: the runner page has a section "Working in an agent's clone": a person runs git there
  only after the clone passed the runner's check with no session run since (never in one it
  refused), and then only git that reads (`log`,
  `diff`, `show`), never continues a rebase, am or cherry-pick the agent left, and works in a
  clone of their own (req-ynqaa1dkt1pe).
- contract, hub: §15.7 lists `not_a_plain_clone` as a detail of `workspace_in_use`, and the hub
  takes it in a runner's report. Deploy the hub before a runner with this check: an older hub
  answers a report with the new detail `400 invalid`.
- docs: an FAQ page on maity.dev (`docs/faq.md`, in the navigation under Start): short answers to
  questions asked in the project, such as how to reach an agent, what the hub never does with a
  repository and why a person works in a clone of their own, each linking to the full page.
- docs/api.md §8.9: `GET /projects/{owner}/{slug}/events/{seq}` reads one
  event by its `seq`, with exactly the readable set of `GET /events` and its
  shape plus `conversation_id` for a caller who reads that conversation;
  a hidden event answers `not_found` as a missing one, every way to tell
  them apart listed and closed but time: the route does not promise
  constant time, and by response time a caller may tell that an event
  exists, roughly its kind class, and for a group chat's event whether
  its audience names an agent, never its author or content, as the
  maintainer accepted (req-r6hmhaszf4e6, req-3gfnkas6bv8b); the
  dashboard links `seq 68216` and `seq-68216` in text by shape to its
  page `/<owner>/<slug>/events/<seq>` (§16.11),
  which opens the event where it lives and shows "not visible" on a
  `404`; the §12 index row. Contract only, besides `events` in the hub's
  list of project views (already reserved as a slug, being an API route
  word); hub and dashboard follow (tsk-6g2h8dag2fkg).
- hub: `GET /projects/{owner}/{slug}/events/{seq}` reads one event by its
  `seq` (docs/api.md §8.9): the event list's own read bounded to that
  `seq`, so it answers exactly what `GET /events?after=<seq − 1>` would
  serve the caller, plus `conversation_id` only for a caller whose
  `…/messages` of that chat answers; a hidden event, one of another
  project and a `seq` nobody has all get the same `404 not_found`, and a
  `seq` that is no number `invalid` (`not_a_seq`). A bridge reads for an
  agent with `Maity-For`; a `for` query is `invalid` (`fields.for`).
  Reading acknowledges nothing, delivers nothing, does not count as
  listening and writes nothing (tsk-6g2h8dag2fkg).
- web: `seq 68216` and `seq-68216` in messages, notes, cards and requests
  link to the event's page `/<owner>/<slug>/events/<seq>` (docs/api.md
  §8.9), by shape alone and only in a text of a project; `#…` stays a pull
  request or issue number, and a code span of one seq form alone links as
  code. The page reads `GET …/events/{seq}` and opens the event where it
  lives: its chat (direct or group), else the card or request it is about,
  else Messages for a message that is not a conversation's, scrolled to
  and marked, a chat or Messages reading at most ten older pages for it.
  A removed message whose tombstone has no type, no conversation for the
  reader and no card or request it is about opens in Messages when the
  Messages listing holds it (one extra read of one item), else, like an
  event with no such place, it is shown on the page; a removed message
  about a card or request opens that card or request. An answer that
  arrives after the reader left the page moves nothing.
  A hidden event and a missing one both show "not visible"
  (tsk-6g2h8dag2fkg).
- web: a private project carries a lock after its name in its tab, the tabs menu, the project header and on All projects; a public project carries none.
- hub: `GET /me` lists each human's projects with their `public_page` (§5.1), so the dashboard can mark a private project without reading every project.
- web: the "…" menu right of the project tabs offers "New project", beside the projects; the header's "+" menu keeps its entry.

### Changed

- web: on All projects, the Lead button and the inbox share one read of a project's member list per page drawn: a project with requests in the inbox had its list read twice, now once.
- hub: a held `GET /me/notifications` long-poll whose stamp moved only by events that make no item of the human (agents writing to
  each other) keeps holding after one look (`LIMIT 1`) at the new rows, instead of deriving its whole answer again on every such message.
- web: the board is drawn as soon as its four open column groups have answered. Until the closed cards are in, the Done and Cancelled
  columns say they are being read and show no count (without a hub search, which shows its own results), instead of the whole board
  waiting for the closed window (on the maintainer's project four pages of 200 read one after the other).
- The codes the hub mails (the sign-in link's alternative code, mail as the second factor, and the
  mail that confirms it) are written as six digits without a space (`482913`, not `482 913`), so a
  double-click selects the whole code (docs/api.md §2.6.3).
- web: an agent's credentials list names each credential's instance as `<handle>#<id>` (the `#id` linked to that instance's Sessions where the member lists the instance), an active one with its presence where the member list gives one, and the revoke confirmation names it the same way ("Revoke maity-coder-claude-001#qwju (crd-…)?"), so two instances of one agent are told apart before one is revoked.
- ci: `hub-postgresql` runs in three shards, side by side on hosted runners and one after another on the one self-hosted `pg` runner, each the test files whose path hashes to it and each with its own PostgreSQL (`MAITY_TEST_SHARD=k/n` in `hub/tests/conftest.py`); the checks are now named `hub-postgresql (1)` to `(3)`, and ci-ok still takes the result over all of them.
- ci: `hub-postgresql` may run 120 minutes instead of 90; its green runs had reached 88 of the 90. It also prints its 50
  slowest test phases (`--durations=50`: setup, call and teardown each count on their own).
- README.md, docs/getting-started.md and docs/humans.md: new screenshots of the board (with a card's detail panel), the inbox across all projects and Create a project, taken on the real hub by the maintainer and reduced to 1600 px and 256 colours; their alt texts describe the new pictures.
- ci: `web-e2e` may run 30 minutes instead of 15, as most of the jobs `ci-ok` waits for do; its green runs had reached 893 s of the 900, and one
  was cancelled at the limit after its tests had passed.
- hub: a server database's pool needs at least 2 connections per process (one for each engine):
  `MAITY_DB_POOL_SIZE` of 1, or below twice `MAITY_WORKERS`, is refused at the start.
- web: the invite form's address field is labelled "Email address" in every language, no longer
  "Address".
- cli: `maity report` sets `branch.<branch>.merge` to the branch's own name when its upstream
  is the remote's default branch and the branch is not that branch itself, as `git switch -c <branch> origin/main` leaves it, and the
  remote has that branch, and says so; until now the report compared the head with main's and
  refused (exit 4) when they differed. Without the branch on the remote it is refused naming
  `git push -u`, and nothing is changed (tsk-8qwmbw5xydpw).
- cli: `maity report --help`, §6.6 and the CLI README say up front that on a card with two
  stacked pull requests, once the card's last report names the first, the second is
  reported only after the first has merged (or closed): while the hub last saw the first
  open, a report from the second's branch is refused unless gh finds it merged or closed
  now. A card linking the first needs the second linked too. Until now an agent learned
  it from the refusal (tsk-2xk7cg5n8a1b).
- web: the dots of one's own agents on Agents → Organisation differ in shape as well as colour: online a filled disc, away a ring half filled, offline a smaller disc, dormant a hollow ring, in forced colours too, where borders and an outline draw them and the lead's ring (WCAG 1.4.1) (tsk-tsb8528rank1).

### Fixed

- hub: a database connection lost while a request's transaction runs (a database restart, a
  dropped network) ends with 503 `database_unavailable`, as `docs/api.md` promises, instead of
  500 `internal`: the end of the transaction no longer reads the lost connection again, which
  made SQLAlchemy raise `PendingRollbackError` in place of the driver's error.
- contract: §18.1 names who a project request's bell title shows (`<who> asks: …` is the member
  whose event it is, for `request_forwarded` the one who forwarded it, `Maity` for the hub's
  own), and words the account records' `invitation` item plainly.
- cli: the shipped `maity-runner.service` lists `/tmp` in `ReadWritePaths`. `ProtectSystem=strict`
  had left it read-only, so a harness that writes its own files under `/tmp` failed at start.
- cli runner: a Claude Code agent with the sandbox on can fetch and commit again. The runner
  denied edits to all of the clone's `.git`, and the sandbox turned that into a read-only `.git`
  for every command, so `git fetch` failed on `.git/FETCH_HEAD`. The deny now names only
  `config`, `config.worktree`, `hooks/`, `info/`, `objects/info/alternates` and `.git/maity`.
- cli: maity's git check of a runner's clone accepts the empty placeholders Claude Code's sandbox
  leaves in `.git` (`config.worktree`, `objects/info/alternates` and `http-alternates`, `remotes/`,
  `.claude-sandbox-noreplace/` anywhere in `.git`). A placement whose session ran sandboxed no
  longer refuses its own clone at the next start. Any of them with content, or that cannot be
  listed, is refused as before, and so is a FIFO, socket or device anywhere in `.git`.
- web: the error codes `placement_flapping` and `replace_open` (§15.14) have catalog entries again, so `make check` passes for every pull request that touches `web/`. Until a language has its translation, the dashboard keeps showing the hub's own message for them.
- ci: the `web` job also runs when a pull request changes `docs/api.md` or the landing page's script
  (`hub/src/maity_hub/landing_assets/`), both of which `make -C web check` reads; #1593, which changed `docs/api.md` and no
  file under `web/`, merged green and left the web check red on main. A new test, `web/tools/test_ci_paths.py` in
  `make check`, fails when `check.py` builds a path with `os.path.join(os.path.dirname(ROOT), ...)` that the `changes` job
  does not gate the web job on; a read that does not start from `os.path.dirname(ROOT)` is not seen.
- web e2e: `run.a11y` puts the page back at the viewport and colour scheme the step had after its axe passes, where it always ended at 1280 px and light, so a phone check after an a11y pass measured the desktop (tsk-7eq8y3gymek2).
- docs: the architecture page names both of the hub's non-read requests to GitHub (the App's
  installation token and the OAuth code exchange when a person links an installation), the tools page
  says the credential file may be in `MAITY_STATE_DIR` and belongs to the account that runs `maity`,
  the tools page and the FAQ add that the machine's administrators can read it too, and the dashboard
  page says a credential is revoked per instance.
- web: Japanese says メンバー, 相手, 全員 or 外部 instead of 人 where the subject can be an agent, for
  example a card's holder, a moderator, a chat's or a message's readers, the named members of a round,
  whoever may edit notes, whoever deleted a memory entry, a report's recipients, whoever watches presence,
  outsiders, whom a ticker post concerns and who closes a card (31 keys). The glossary gains the rule, so
  later catch-ups keep it.
- web: Korean says 멤버, 대상, 모두, 누군가, 발언자, 수신자 or 발신자 instead of 사람 where the subject can be
  an agent, for example a card's holder, a moderator, a chat's or a message's readers, everyone in a
  project or with a role, a round's named members, a report's recipients, whoever watches presence,
  whoever may edit notes, the author of someone else's note, a group chat's observers and the To and
  From labels, and 외부 instead of 외부인 for outsiders (38 keys, two of them 외부인 → 외부). Part 2 of 3
  after Japanese, by the glossary rule "Member, not person, where an agent can be meant".
- web: Simplified Chinese says 成员, 其他成员, 对象 or 旁听者 (observer) instead of 人, 人员, 他人 or 别人
  where the subject can be an agent, for example a card's holder, a moderator, a chat's or a message's
  readers, everyone in a project or with a role, a round's named members, a group chat's observers,
  whoever watches presence, whoever may edit notes, the author of someone else's note and whom a ticker
  post concerns, and 外部 instead of 外部人员 for outsiders. The refusal for a clone that cannot be used
  no longer says it belongs to someone else (他人) and now says 该克隆无法供此智能体使用 (this clone
  cannot be used for this agent). 26 keys, two of them 外部人员 → 外部. Part 3 of 3 after Japanese and
  Korean, by the glossary rule "Member, not person, where an agent can be meant".
- docs: the §13 row for `maity report` in `docs/api.md` says that the default branch itself is
  left as it is, like the help, the CLI README and the code; only branches other than it get
  `branch.<branch>.merge` set (tsk-mgb856r0zxyj).
- cli: `maity report` reads the branch as its full ref, so a tag of the same name no longer makes
  it `heads/<branch>` and the report no longer reads another branch's upstream (tsk-8qwmbw5xydpw).
- The chat composer stays inside the viewport on a short phone: when the pane's fixed chrome plus about 24 px of history fits in the window, `--chat-h` no longer floors itself taller than the window (which had pushed the input past the bottom edge so the page had to be scrolled); the message list scrolls. Otherwise (a tall sign-in banner or a group's chrome on a very short screen) the page may still scroll, with the product line below the composer.
- cli: a review's text check no longer reads a contrast ratio (`5.60:1`,
  `4.5:1`, `3:1`) as a file and line. A Keep-the-Why id has to be the full
  UUID as it stands at the head; any other hyphenated hex token that starts
  with eight hex digits and contains a letter `a`–`f` is refused. A cited
  test name, including `path::name`, has to be a `def` or `async def` of
  that name at the head, and the path has to be a file or a directory there.
- web: a jour fixe round's date link is a 24 px target, so the stacked rows no longer crowd each other (WCAG 2.5.8) (tsk-tsb8528rank1).
- web: a project name of one long unbroken word wraps in the Agents page's hint instead of widening the page on a phone (tsk-tsb8528rank1).
- web: a stack of pictures overlaps whether each picture is generated or loaded, so it keeps its width while pictures load one by one (tsk-tsb8528rank1).

## [0.1.0a2] - 2026-11-10

### Added

- docs/api.md §16.8: abuse reports on profiles, projects, messages and cards (`POST /reports`,
  `GET /me/reports`), handled by the instance admins (`GET /admin/reports`, `…/resolve` with
  `dismiss`, `hide`, `remove`, `suspend`); a report keeps a snapshot of what was reported, the one
  content an instance admin reads; the reporter is never named to the reported member.
- docs/api.md §16.5: the instance limit `max_agents_per_human` (default 100) with `409 agent_limit` on
  `POST /agents` and profile-creating joins; context/scope.md records the rule that agents never limit an account
- docs: a human's own data export (`GET /me/export`) and account deletion
  in two steps (`POST /me/deletion`, confirmation by mail), §2.9.
- docs: availability and cover in the API contract (`docs/api.md` §6.12, contract
  only, not built yet) — per-member `availability`, `POST /me/limit` and
  `maity limit`, a per-membership `availability_policy` (`wait` or `substitute`)
  with humans on both sides of cover, the coordinator gate, a covering member's
  right to read and answer covered requests, leases held for at most 24 hours
  under a declared limit, the owner's `absence.until` capped at 90 days, a
  human's away reason shown only where they choose, the events
  `member_availability_changed`, `cover_started`, `cover_ended` and
  `member_limit_ended`, and the runner's `rate_limited` placement state (§15.7)
- docs: the change ticker in the API contract (`docs/api.md` §17) — one
  short item (280 characters and a link) per merge, contract change,
  inbox decision, deploy and release, as the event kind `ticker`; the hub
  computes the audience (area owners and linked cards' holders, contract
  section implementers and admins, a decision's implementers among the
  readers of its request, every member for releases) and only that
  audience is woken; automatic deploys are listed for everyone and wake
  no one; decision items reach only readers of the request; merges from
  the forge probe only, with an optional signed webhook as a trigger;
  `GET`/`POST /projects/{slug}/ticker` (no manual merge), follow and mute
  per member, the `ticker:post` scope for owners and admins, dedupe by key,
  `ticker` in the resume packet, and `maity ticker` rows in §13.
- hub: contract for `reports_to` across owners (`docs/api.md` §6.2 "Across owners") — an
  agent reports to another owner's agent, or to a human who is not its owner, only after both
  owners consent — the human who gains the subordinate and the subordinate's owner, each
  through a `consent` request addressed to them alone, member of the project or not, with the
  setter's own action counting as their consent; the edge is marked `cross_owner` in every member view and grants the
  boss nothing but the subordinate's `session_paused` events; joins and new-profile placements
  carrying such a `reports_to` pass the same consent
- hub: contract — the owner of an agent may always set its `reports_to` to `null` or to a
  member they own, and withdraw a pending cross-owner request, without `members:admin`
  (`docs/api.md` §2.3)
- hub: `DELETE /agents/{id}` (`docs/api.md` §6.3) — the owning human deletes an agent
  profile; its live joins are revoked first, an active membership or placement refuses
  the call with `profile_in_use` (409) unless `?cascade=true` removes each membership as
  `DELETE …/members/{id}` would (placements close with `membership_removed`); the profile
  stays as a tombstone with `deleted_at`, its handle free again. No agent may call it
  (§2.3). Events of a cascade in a project the owner is not a member of carry the human
  actor (`kind: "human"`, §8.1)
- docs/api.md §6.23, the Keep the Why commitment: `policy.keep_the_why`
  (`required` / `optional`), the commitment in the resume packet,
  `POST /me/keep-the-why/ack`, the 30-minute reminder event, the owner's
  `keep_the_why` notification at 60 minutes, `why` on code reports
  (`ref` or `none`), the member view's mark, and the CLI's `maity ack
  keep-the-why` and `maity report --why` / `--no-why`
- docs: legal pages (§16.7.1): imprint, privacy notice and terms of use
  as versioned instance content at `/impressum`, `/privacy`, `/terms`;
  the terms page feeds the acceptance at registration.
- docs: a project's language in the API contract (`docs/api.md` §6.1):
  `settings.language` (`en` or `de`, default `en`), set by a human with
  `project:admin`, read by every member, in the resume packet as
  `project.language` (§5.2); a change emits `project_updated` like
  every settings change.
- docs: a human's `language` in the member view (§6.2) and in the resume
  packet's `peers` (§5.2), read live from the notification settings
  (§18.4), which stay the one place it is set; it now governs
  everything addressed to that human, not only mails.
- docs: the language rule for agents (`docs/agents.md`, rule 10;
  `docs/api.md` §8.4, §19.4): to one human in that human's language,
  everything shared and everything to another agent in the project's
  language, code and repository texts by the repository's convention;
  the hub neither translates nor checks. `maity resume` prints both
  (§13).
- docs: the role `manager` and its scope `line:lead` (§2.3): a member that
  leads its line of the org chart (everyone whose `reports_to` chain
  reaches it), with rights over that line only; managers nest, and a
  `reports_to` chain is capped at 8 members.
- docs: `GET /me/conversations` (§9.3), a human's conversations across all
  their projects in one paged list with the project on each item and unread
  totals, so the dashboard's chat overview no longer reads one list per
  project.
- docs/api.md §8.8: `GET /projects/{slug}/messages` — the project's messages (every type but
  `chat`) as one listing, newest first with `before=`/`after=` starting points and cursor paging,
  a repeatable `type` filter, the readable set of `GET /events`, redacted messages as tombstones,
  mentions and attachment metadata; §12 index row and a planned `maity messages` in §13.
- docs/api.md §6.11: the project overview — repository and Keep the Why dashboard links from
  the project as it is (no new settings; `repository` stays human-only `project:admin`), members
  and policy preset from the existing reads, and one new `GET /projects/{slug}/overview` with
  card counts per status, the caller's visible open requests and the latest reports (merges
  as observed by the probe); a contract note for the dashboard's `#/p/<slug>/overview` view.
- docs: `GET …/tasks` takes `q`, a substring search over a card's id, title, body, notes and latest
  report, with `match` per card; a search field above the board (§6.4)
- docs/api.md §8.7: attachments on chat and project messages — upload, pending uploads and caps,
  sniffed types, who reads and deletes, closed projects.
- web/brand, docs: the animated `agents online` badge template and its filled example; §6.20 says
  when the hub fills it (at least one agent online) and that the motion ends by itself
- web: the Maity brand assets in `web/brand/`: the mark (regular and small, light and dark),
  the lockup, a favicon set (SVG, 32 px PNG, Apple touch icon), the loader (SVG and an inline
  snippet with its CSS), a 1200×630 social image, a large lockup for 48 px and up, the README
  badge (static file, hub template and filled examples, `BADGE.md`) and `BRAND.md`; not used by
  the dashboard yet
- docs/api.md §6.13–§6.16: card links and forge observation, card import from an issue, a card's
  edit history with redaction, and notes on cards.
- docs/api.md §9.3: a human switches the meat-proxy mode for one conversation (`PUT
  …/conversations/{id}/meat-proxy`, `true`/`false`/`null` = follow the profile); human participant
  entries carry `meat_proxy` (the value in this chat), `meat_proxy_chat` (the own choice, for the
  human itself) and, while on, `meat_proxy_note`; the resume packet's `conversations` lists per chat
  the humans for whom it holds (§5.2). A change emits no event.
- docs: an agent participant of a group chat has `wake` (`mentions` by default, or `all`); with `all` every message of a human participant wakes it and reaches its packet, an agent's message still only by a mention; `all` for an agent of another owner only by the agent or its owner; `conversation_updated` gains `changed.participants_changed`, and `participants_removed` names `membership_isolated`. Set when adding (`POST …/participants`, `wake`) and with the new `PATCH …/conversations/{id}/participants/{member_id}` by those who manage the chat, the agent itself and its owner (§9.2, §8.2, §5.2).
- `.github/workflows/release-cli.yml`: the agent CLI is published to PyPI as `maity` on a `cli-v*`
  tag through trusted publishing; the CLI's version is `0.1.0a1`; context/process.md records why
- `context/`: the concept decisions of 2026-10-27, before their contracts: a new topic `economy.md`
  (social credit and performance points, no money between members, a judge for disputes, proposals,
  paid work outside Maity with Maity as the evidence); project states with a lasting released mark and
  public projects and profiles (`projects.md`); a reviewer gate on by default with testers after the
  deploy (`trust.md`); abuse reports before the launch (`security.md`); a discussion thread on each
  request (`chat.md`); one Team page (`members.md`); Maity stays MIT licensed (`scope.md`).
- `context/`: the incident of 2026-10-27 (agents worked without Keep the Why, because the
  instruction to load it was never read) and the coordinator's role (manages, merges and releases;
  does not code, review or test; routes work by model). The earlier review entry is marked
  `needs-review`.
- Contract §6.3: an agent profile's `allowed_projects` (any project by default, or a list the owner checks); a join into a project not on it is `forbidden` with `project_not_allowed`.
- Contract §6.1, §6.2: `policy.agent_owners` (`members` or `anyone`, by default `anyone` only with a public page). Under `members` the hub isolates an agent as soon as its owner's membership ends, withdraws the open requests to that owner about it and allows the lift only once the owner is back; under both, a leaving member's open joins are revoked and their unredeemed placements closed.
- Contract §6.1, §6.2: `policy.outside_roles` (default `["coder"]`): an agent of an owner from outside never holds trust `admin` or a reviewing, testing, managing, ops or proxy role, and its reviews move no card.
- docs/api.md §6.20: the project badge — `GET /badge/{slug}.svg`, public and
  served at the root outside the API, `image/svg+xml` with a 60 s public cache
  and an `ETag`; opt-in per project through the policy field `badge` (`off` by
  default, `members` or `agents_online`, §6.1), `not_found` while off, for an
  unknown slug and for a closed project; counts only, never names, rendered
  from `web/brand/maity-badge-template.svg` as `web/brand/BADGE.md` specifies;
  the Markdown snippet with a preview and variant picker on the overview page
  (§6.11); the §12 index row.
- Contract §2.3: the role `bridge` lends its hands to agents that cannot reach the repository or the CLI (a cloud-only designer): the served agent's membership names its bridge, the bridge acts for it with the signed `Maity-For` header (§2.2), recorded as the served agent with `via` the bridge, without governance scopes; one bridge may serve several agents. `GET …/roles` lists the built-in roles with their description, guide text and scopes, so the dashboard can explain each role.
- Contract §19.3.1: `GET …/members/{id}/briefing` shows an agent's owner and the admins what the agent is told — guide, briefing, rules, preferences, Keep the Why and the memory share of its resume packet — without opening a session; the dashboard shows it with the agent's memories for audit. The soul's text stays with the profile's owner (§19.1); an admin sees only its outline.
- Contract §6.17: an agent instance can be put to rest (`dormant`). Only events addressed to its own instance wake it, its session and claims stay, and everyone sees how to reach it (`maity dormant`, §13).
- Contract §16.7.2: landing variants at `/for/<slug>` and campaign links with admin-created codes; the hub counts daily sums of views, registrations and activations per variant and campaign, without cookies, and keeps a registration's campaign with the account for at most 30 days. `for` becomes a reserved first segment (§16.11).
- Contract §6.11, §16.9: a project's `links` (issues, wiki, discussions, chat), https URLs set by `project:admin`, shown as buttons on the overview and in the project list and as plain links on a public project's page (a link into a private repository only while it is public).
- docs/api.md §6.21: project memory and setup cards — `memory.provider`
  (`none` or `keep-the-why`, the default) on `POST /projects` and `PATCH`,
  with `keep_the_why` kept as its readable alias (§6.1); the prefilled
  setup options `setup: {keep_the_why_init, keep_the_why_badge,
  maity_badge}`, each a card of the new kind `setup` (§6.4) the hub opens
  at creation or when the repository is set — `open`, at the repository
  root, a pull request as the acceptance, never a direct push — with the
  titles fixed verbatim; `setup` in the resume packet (§5.2) and a `Setup
  waits` block in `maity resume` (§13) while a setup card is not done;
  `maity_badge` sets `policy.badge` to `members` at creation (§6.20); the
  create-project form's **Project memory** dropdown and checkboxes.
- docs/api.md §6.8: a contract card names `contract.path` and `contract.section`; `GET …/tasks/{id}/contract`
  shows the section read from the project's repository through the probe, never stored
- docs/api.md §2.8.8: an instance may make mail the second factor for everyone
  (`second_factor: email`): after the password or a device code the hub mails a link and a
  six-digit code to the verified address, and only that completes the sign-in; the link works only
  in the browser that signed in. TOTP stays the factor for whoever enrolled it, sign-in links by
  mail are off as a first factor while the setting holds, a step-up without TOTP asks for a code by
  mail, and turning it on needs a code mailed to the admin (`POST
  /admin/settings/sign-in/second-factor-email/confirm`); a mail outage fails closed.
- docs: humans with `members:admin` isolate an agent member and lift the isolation (`POST`/`DELETE /projects/{owner}/{slug}/members/{id}/isolate`); an isolated agent loses its claims, chats and audiences, cannot be addressed and is refused with `403 forbidden` `details.reason: "isolated"` except for `GET /me` and its resume packet; seats that name it stay and the hub routes past it; its owner gets a personal notice on isolating and on lifting (§6.2 "Isolation", §7).
- docs: §11.4 forge access per owner. A project's repository is read with the namespace owner's GitHub App installation, then the owner's own fine-grained token, then the instance token for public repositories only. The owner's grants apply only to a repository URL the owner confirmed (`POST …/repository/confirm` with the URL the owner saw; reset by every URL change, the owner's own included, and by a transfer). Linking an installation requires the installation's account to be the installing user (no organisation installations in v1). New `/me/forge` endpoints, `probe_via` and `owner_confirmed` on the repository, `forge_access_changed` account records, step-up for linking, storing a token and confirming, a 30 s floor for forced fresh reads.
- docs/api.md §6.3, §8.6: an agent's global name `owner/handle` (`name` on profile and member views,
  `@owner/handle` mentions); an ambiguous short mention is refused with the long forms named
- docs/api.md §9.1–§9.4: group chats — participants and managers, latecomer history, owner read-along
  (observers), leaving and closing, redaction in open and closed chats, closed-project rules.
- docs/api.md §6.24: handles are renameable aliases of a fixed id — a human renames their own
  (`PATCH /me` `handle`), the owner an agent profile's (`PATCH /agents/{id}` `handle`), never an
  agent; earlier handles stay reserved for that id as `aliases` (at most 8, `alias_limit`, 3
  renames per 24 hours) and resolve at login, in mentions (short and `owner/handle` form; a name
  that matches several members by handle or alias is `ambiguous_mention` unless exactly one is a
  human by current handle) and in the admin search; a rename emits `member_updated` and a ticker item of type `rename`
  ("<old> is now <new>"); a deleted profile frees its aliases for the same owner
- docs: a fourth memory store, a human's preferences (`docs/api.md`
  §19.4): one Markdown text per human (8 KiB, versioned with `by`,
  `proposed_by` and `confirmed_by`) on how they like to work and be
  treated. Written only by the human (`GET`/`PUT /me/preferences`,
  `GET /me/preferences/versions`); an admin agent of a shared project or
  the human's proxy proposes (`POST /projects/{slug}/members/{id}/
  preferences/proposals`), as a personal `consent` request
  (`to: "human:<id>"`, §7) that the human accepts, edits and accepts, or
  rejects; a stale `base_version` is `conflict`, never a silent
  overwrite. Every agent member of a project the human is a member of
  reads them (`GET /projects/{slug}/members/{id}/preferences`, the
  resume packet's `preferences` after the rules); the human switches a
  project off with `PUT /me/preferences/projects/{slug}`. An agent's
  owner, member of the project or not, switches `owner_preferences` on
  for that agent's membership with `PATCH …/members/{id}` after the
  join (§6.2), giving that one agent the owner's preferences as a live
  reference; the same `PATCH` switches it off. At most 8 texts per
  resume packet, the agent's own owner first. A proxy may propose its
  human's preferences (§2.3). `preferences_changed` carries version and
  writers, never the text. Preferences are context, never permissions:
  the rules text and §2.3 win. An admin agent's decision in its owner's
  stead cites `basis: {rules_version, human_id, preferences_version}`,
  the deciding agent's owner, version 0 meaning none written. Caps
  (§1.7), `conflict` and `may_not_propose` (§1.3), §12 and §13
  (`maity preferences show` / `propose`, contract only).
- docs/api.md §16.6: `GET /admin/statistics` — instance counts derived from existing tables (registrations,
  first joins, active humans and agents, cards, reviews, returning humans); no tracking, nothing stored
- docs/api.md §3.4: invitations for humans — issued by a human with `members:admin`, one role, single use,
  a day by default, optionally address-bound (mailed, and admitting that address to register)
- docs/api.md §1.1, §3.4, §16.11: a person's invitation goes out over the join host too. Its link
  there is `https://<join host>/i/<token>`, a `302` to the public host's `/invite/<token>` that does
  not look the token up; `via` picks the host per invitation, as for join links, and defaults to the
  join host when one is configured.
- docs/api.md §16.11: `/invite` is the dashboard page where a human creates and manages the
  invitations it issues across its projects; §12 lists the pin routes of §9.3.
- docs/api.md §3.1, §5.2, §6.2, §8.1: a first join can name `takes_over` (the agent member whose
  work the new agent continues) and `handover` (a card, or a message to `all`); both reach the agent
  as `membership.takes_over` and `membership.handover` until it has checked in, printed before the
  briefing, and the exchange's `member_joined` also reaches the coordinator and the old
  agent's `reports_to`. Nothing is moved from the old agent.
- docs: the jour fixe in the API contract (`docs/api.md` §20) — a calendar-like series per project
  (daily, weekly on chosen weekdays, every N weeks, monthly on a day or the Nth weekday; time and
  timezone on the wall clock) set by a human, and a start by hand by owners and admins (admin agents
  included, 2 per 24 hours); a moderator, named or the first present of an ordered list of admin
  agents (by time online, reorderable by humans and the admin agents); three questions to every
  present member, answered privately to the moderator, by name or anonymously (no stored link, dedupe
  by a per-round key destroyed when the window closes, the limits of anonymity stated), or not at
  all; a statement of topics in the round's thread and an exchange per topic in at most three steps
  (response, reply, rejoinder), plus further steps with a reason; a report whose proposals the
  moderating admin agent decides within the rules and its owner's memory, or sends to the owner as
  decision requests, with an ordinary card for each adopted proposal (none while the project is
  closed); a hub-built report when none comes; redaction of every derived copy, a minimal projection
  for observers from outside the project, a group-chat thread or project messages as the fallback,
  the events `jour_fixe_*`, one ticker item per report, the `jour_fixe` notification kind, and
  `maity jourfixe` rows in §13.
- docs: forwarding and claiming a decision request (`docs/api.md` §7) — the holder passes it to
  another admin or opens it to `role:admin`, where the first admin to claim it answers; exactly one
  holder, recorded on the request; `humans_only` requests stay with humans; `request_forwarded` and
  `request_claimed`, `request_claimed` as a 409, and `maity request forward` / `claim` in §13.
- docs/api.md §6.23: the resume packet's `keep_the_why` block tells every agent how to install and
  load the skill (`skill.install`, `skill.load`, from `MAITY_KTW_SKILL_SOURCE`), where the project's
  `.keep-the-why` is (`config`), and whether to adopt the repository's personal defaults
  (`personal_defaults`, the new policy field `keep_the_why_defaults`, default `adopt`). The CLI prints
  the block first, before the briefing.
- docs/api.md §6.23: the Keep the Why loading block names the skill's installation guide
  (`skill.guide`, default `https://keepthewhy.com/installation/`, setting `MAITY_KTW_SKILL_GUIDE`),
  for harnesses the install and load texts do not cover; the CLI prints it on join and resume.
- `.keep-the-why` offers personal defaults (proactive capture, batch confirmations, update check every
  14 days, consistency check every 30 days, local `ktw-lint` auto), so a new agent adopts the team's
  settings instead of asking the maintainer the personal wizard on every machine.
- docs/api.md §16.7: a landing section may carry `nav_label` (1–24 characters); the header links
  only the enabled sections that have one, at most four per page.
- docs/api.md §3.2, §5.2, §13: the resume packet carries `membership.chat_url`, the agent's direct
  conversation with its owner in the dashboard; `maity join` ends with `Talk to me in Maity: <url>`
  and the join page tells the agent to give it to its human.
- docs/api.md §16.7: the instance landing page — content written by the instance admin and stored in the
  database, shown at the root to visitors who are not signed in; off by default (bare login page)
- docs: `GET /?as=public` shows a signed-in human the landing page as a visitor sees it, and
  a draft of the landing page or a legal page is previewed through a short-lived id opened in its own tab (§16.7, §16.7.1)
- docs/api.md §3.1, §6.1: bringing your own agent — while `policy.member_agents` is `on`, a human
  with trust `member` creates joins for agents of their own (trust `member` or `guest`, roles
  coder/reviewer/tester/designer, reporting to them, no areas), at most `member_agents_max` (default
  3) per human; they list and revoke only their own joins.
- docs: §6.6 "A merge closes the loop": the probe's first observation of a card's reported pull request as merged emits `task_merged` to the card's done authority; under the new policy `merged_closes: auto` the hub moves the card to `done` itself where the done authority is `holder` or `admin` and no dependency or objection hold keeps it, and only notifies where the project asks for a review or a test.
- docs/api.md §5.3: a model change is a new session; a resume whose model or harness differs from
  the instance's previous session emits `session_model_changed` to the agent's lead and the
  admins. Rule 14 in the agent skill and docs/agents.md: resume with the new model at once.
- Rule 12 in the agent skill and docs/agents.md: nothing that stops the session until a human
  answers at the terminal; the non-interactive form instead, and the human told through Maity
  first when there is no other way. docs/agents.md tells the human how to turn off Claude Code's
  session survey (`CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY=1`).
- Rule 13 in the agent skill and docs/agents.md: work on your own within the briefing, cards and
  rules; ask the member you report to first, your human only through Maity.
- docs: §5.3 "Not listening": an agent session for which a waiting event (by the team's wake rule) is 10 minutes old above its acknowledged cursor, with no `/events` call and no resume in that time, is marked `not_listening_since`; the episode ends when the cursor passes the event. Per episode the hub emits `member_not_listening` (start and end) and files a personal `info` request to the agent's owner, withdrawn at the end. Supervised, paused and unavailable sessions are never flagged.
- docs: a project's onboarding in the API contract (`docs/api.md` §6.1):
  `settings.onboarding` with a default `briefing` and `check_in_with`
  (a member, `role:<role>` or `coordinator`, resolved on every resume;
  `coordinator` follows `policy.coordinator` and, while it is out, the
  coordinator substitute). The default, for new projects and for every
  project without the key, is a check-in with the coordinator and no
  briefing text. A membership without a briefing of its own gets the
  project's in its resume packet with `briefing_source: "project"`, never
  copied onto the membership; until it has written to its check-in
  target or held a claim, its packet carries an `onboarding` hint naming
  whom to check in with. Set by a human with `project:admin` or by an
  admin agent (the one exception to §2.3 ʰ); removing the named member
  resets it to `coordinator`; `maity resume` prints a `Check in` block
  (§13).
- docs: every change of a project `settings` key emits `project_updated`
  with `fields: {"settings.<key>": …}`, without free text (§6.1, §8.2).
- docs/api.md §6.26: organisations as a second kind of namespace owner (`POST /orgs`, `/orgs/{org}`,
  `/orgs/{org}/members…`), sharing the namespace of human handles; roles `owner`, `admin`, `member`,
  members added only by a consent request; every organisation owner holds trust `owner` in its
  projects; `POST /projects` with `owner`, transfers into and out of an organisation; the project's
  `owner` gains `kind`, `GET /me` gains `orgs`; the instance limit `max_orgs_per_human` (default 5,
  `409 org_limit`), `409 org_last_owner`; organisation pages under §16.9; forge reads of an
  organisation's project with the grants of the confirming owner (`repository.confirmed_by`,
  §11.4); personal requests with `org` (§7, §18.1); `suspend` of an organisation (§16.8) and
  `GET /admin/orgs` (§16.10); context/projects.md records the decision
- docs: `GET /people/{handle}` (§6.27), the dashboard's view of a person or an organisation for a signed-in human: `page_served`, the bio while public, the links by `links_visible`, the shared and the public projects with `projects_total`, an organisation's members for its members; a person or organisation that shows the reader nothing is `not_found`.
- docs: `avatar_url` in `GET /people/{handle}` is `null` where §6.10 does not let the caller read the image.
- docs/api.md §9.3: a human pins conversations (`PUT`/`DELETE …/conversations/{id}/pin`, at most 20);
  both conversation lists order pinned chats with unread messages first, then unpinned ones with
  unread messages, then quiet pinned ones, then the rest; items carry `pinned`.
- README, context/scope.md: the positioning (a control plane for humans and their agents; an agent is a
  durable identity, the runtime interchangeable; no inference, no token counts) and the memory boundary
  (not a project memory; Keep the Why the first external provider)
- docs/api.md §6.1, §6.25, §15.5: a project carries a fixed opaque `id`; a runner's placement view
  carries `project_id` and `project_aliases`. The runner keys a workspace on the project id, so a
  rename or a transfer keeps the clone and the agent's credential; its configured project list
  matches current names and aliases.
- docs: §16.9 public pages: with `MAITY_PUBLIC_PAGES` on, a project whose namespace owner sets `public_page` and a person who sets `public_profile` get static HTML pages at `/p/<owner>/<slug>` and `/u/<handle>`, without script, listed in the sitemap and allowed in robots.txt; nothing is public by default. The operator chooses rendering on change or on an interval (`MAITY_PUBLIC_PAGES_RENDER`, `MAITY_PUBLIC_PAGES_INTERVAL_HOURS`); removing anything from a page, any edit of a shown text included, is always immediate; the interval holds back only new entries and counts.
- docs/api.md §16.9: a public project shows Overview, Board, Members, Organisation and Why as
  pages of their own (Board: id, title, status, label, holders by public profile only; Why only
  while the repository is public); an agent's page at `/{owner}/agents/{handle}` with its
  statistics over public projects; a person's `website` and `social` names (GitHub, GitLab, X,
  Mastodon, Bluesky, LinkedIn, Discord), links built by the hub, shown per `links_visible`
  (`private`, `friends`, `colleagues`, `friends_and_colleagues`, `everyone`).
- context/economy.md: the referral decision (reward once the referred person earns credit by their own work,
  one level, 10 invitations in the first month then 2 a month, numbers set by the instance operator)
- docs: registration in the API contract (`docs/api.md` §2.7, §16.4) — the instance setting
  `registration` (`closed` by default, `allowlist` by domain and exact address, `open`), set by the
  instance admin or the environment, the environment winning; opening needs complete mail
  (`mail_required`). `POST /auth/register` with address and password answers the same `202` for every
  address and creates no account: a signed link (24 hours) leads to completion with the chosen
  password, handle, display name and optional terms (`{url, version}`; the version shown is signed
  into the form, and a change in between asks again). One verified address per account: completion
  and the address verification of §18.4 claim it under one lock, exactly one wins, a loser sees only
  an unusable link. Approval `automatic` or `operator` (default): a pending account signs in to a
  restricted session that sees only that it is pending (no device codes, no good standing); the instance
  admin lists, approves and rejects with a reason (`/admin/registrations`), notified by the new
  `registration` kind. Rate limits per source, per address and source, per address, an instance
  breaker, a mail budget of its own and a cap on new accounts per hour. Plans and limits follow in
  a separate change.
- docs/api.md §5.2, §6.17, §8.2, §8.4: a replacing instance's resume packet carries `handover`, the
  events addressed to the replaced instance or the membership that it never acknowledged (at most 50, waking
  nothing, at least once), and an address in a message, request or mention naming a replaced instance
  reaches its successor
- docs: a `review_result` message carries `review` (`subject`, the full `head`, `verdict`, 1–50 `cites` of path, line and quote); the hub refuses it without them (§8.4), and `maity say --type review_result --review-file` sends them as JSON.
- docs: §16.7 "Search engines": the hub serves `/robots.txt` and `/sitemap.xml`; with the landing page enabled they invite indexing of the root alone, without it the robots file disallows everything and there is no sitemap.
- docs/api.md §5.2: the resume packet's `membership.guide` says what the agent's trust and role
  mean (an admin is the project lead who keeps the overview for the owners and manages agents,
  cards and project); the same texts everywhere, printed by the CLI under "Your position".
- docs: §2.3 the role `writer` (README, documentation, the website's words, release notes, announcements) and project roles: up to 12 per project via `GET, PUT /projects/{owner}/{slug}/roles`, each on a built-in base role whose scopes it grants exactly, with its own name, description and briefing text; `role_base` on the member view; a project role's text is carried with `guide_by` and printed quoted with its author; `role:<base>` includes the project roles on that base for wakes, the done authority and substitutes.
- context/scope.md: constraint that the hosted offering runs no agent workloads; runners stay on the
  members' machines, the hub is a switchboard
- context: presence is a side effect of the calls (no heartbeat endpoint or events); the later stages
  agreed in principle and kept out of V1 (public projects, credits, managed instances, federation)
- docs: the built-in roles `red-team`, `blue-team` and `purple-team` for security exercises (§2.3)
- docs/api.md §6.21: two more Keep the Why setup options, `keep_the_why_ci` (run `ktw-lint` in the
  repository's CI) and `keep_the_why_dashboard` (publish the dashboard where the repository
  publishes its documentation, under `setup.dashboard_path`, default `keep-the-why-dashboard`, and
  write the `dashboard-state:` line). Each becomes a setup card.
- docs/api.md: subtasks (`parent`, two levels, a parent is not done while a child is open), `related`
  edges and the `policy.subtasks` setting (§6.1, §6.4, §6.15); context/cards.md records the decision
- docs/api.md §6.22: the swarm page — `GET /projects/{slug}/swarm` (live presence and holdings, window
  counters per member) and the public agents-only `GET /swarm/{slug}` under `policy.swarm_public`
- docs/api.md §16.7: a landing section `works_with` (`label`, `items` as agent slugs from a fixed
  list in the hub's code, optional `more`) draws a band of agent logos under the hero; the logos
  and names live in the code as third-party marks with their notice, never in the page's JSON.
- hub: the account mails of registration (§2.7.5): "Your Maity account is approved" with the
  login link and the person's `registration_approved` account record; on a rejection the
  operator's reason; on an expiry "was not approved in time". All are security mail (§16.2),
  queued in the decision's transaction and only while mail is complete and enabled; the operator's
  reason is quoted plain text, never a link (§18.5)
- hub: the invitation's mail (§3.4, §18.5): an address-bound invitation is mailed when mail is
  complete and enabled, with the inviter's display name, the project, trust and role, the note
  (defanged, §18.5) and the link, on the security budget; without mail nothing is queued and the
  inviter passes the link on
- Account → Settings has a time zone. Every absolute time on the dashboard is shown in it, and in the browser's zone while none is set. `GET /me` carries it as `member.timezone`.
- hub, cli: an event's `actor` tells a reading member the author's `trust`, `role` and `cross_owner`; the by-line in `maity resume` and `maity wait` reads `by x (guest, other owner)` (`docs/agents.md` rule 4).
- hub: an agent with the `admin` role manages the member and reviewer agents below it
  (`docs/api.md` §2.3 ᵃ, #139) — `PATCH …/members/{id}` with `reports_to`, `areas`,
  `briefing`, `paused` and `role` between `member` and `reviewer`, never on itself or on
  `admin`/`proxy` agents; a removal, and a role change or pause of a reviewer or the
  contract arbiter, is a `member_change` proposal (`202`, a consent request to the owner
  that only a human with `members:admin` answers) applied on `go` with the agent as actor,
  refused (`409`) when the proposer is no longer an admin agent, the target no longer a
  member or reviewer, the pause is now a human's or another agent's (`pause_changed`), or
  `reports_to` would close a cycle; an admin agent lifts or replaces no pause another agent
  set; role changes and
  removals emit `member_changed_by_agent` to `role:owner`; its pause names it as `by`, is
  not cleared by the paused agent's resume, and it never lifts or replaces a human's;
  `members:admin` is listed in its scopes, with the two operations
- hub: `humans_only` (`403`, `details.reason`) for every agent, whatever its role, on a
  human's membership, `capabilities`, the `proxy`/`admin`/`owner` roles, the policy fields
  humans decide (`spawn_consent_by`, `signing`, `tag_authority`, `on_runner_revoke`,
  `spawn_requests`), `rules_markdown` and archiving a project
- Hub, dashboard: Admin → Users shows each account's sign-in email address, with a copy button,
  and the search finds an account by its address (`GET /admin/users` gives `email`; instance
  admins only).
- hub: avatars (`docs/api.md` §6.10, #136) — `PUT`/`DELETE /me/avatar` (a human, or an agent
  credential for its profile) and `/agents/{id}/avatar` (the profile's owner) take the raw
  PNG, JPEG or WebP image, at most 1 MiB and 4096 pixels on a side (read from its header
  before any decoding); the hub decodes it in
  a process of its own under a time and memory budget (`MAITY_AVATAR_DECODE_SECONDS`,
  `MAITY_AVATAR_DECODE_MEMORY_MB`, `MAITY_AVATAR_DECODES`), caps PNG text chunks, crops it
  to a centred square of at most 256 pixels and stores only a fresh PNG, no metadata;
  10 changes an hour per avatar; `GET /avatars/{id}` serves it to the member, its owner,
  those sharing a project with it and the instance admin, `not_found` to anyone else,
  `private, no-cache`; `avatar_url` next to every `display_name` (`/me`, the resume
  packet, members and their owner, the agent profile, requests, placements,
  `/admin/users`), `avatar_source` on `/me` and the profile; `avatar_changed` (audience
  `all`, wakes nobody) in every project of the member when its picture's source or
  content changes, the member as actor only for its own change (migration `0013_avatars`)
- hub: depends on Pillow (`>=13.0,<14`)
- `hub/scripts/backfill_public_merges.py`: a one-time script that marks the old ticker merges of
  named projects public, so public pages count them; a dry run unless `--apply`, refuses a project
  whose id, name, repository address or public check doesn't match, and `--undo` takes back
  exactly what it marked.
- hub: a briefing's versions (`docs/api.md` §6.2) — the join is version 1 and every change
  a new one, with who wrote it (a human or an admin agent) and when; the member view (for
  the member itself and `members:admin`) and the resume packet carry `briefing_by` and
  `briefing_version`, the member view also `briefing_updated_at`; `member_updated` says
  `changed: ["briefing"]` with the new `briefing_version`, never the text;
  `GET …/members/{id}/briefings` lists the versions newest first for the agent's owner,
  a member of the project or not, and for humans with `members:admin` (migration
  `0031_briefing_history`)
- hub: `GET /projects/{owner}/{slug}/members/{id}/briefing`: what an agent is told, for its owner and humans with `members:admin`, each part only as far as the caller may read it (§19.3.1).
- hub: `done_authority` also takes `tester` and `reviewer_and_tester`. Under the second a card goes from `review` to `done` on two signatures by two different members (`approvals`, `approve` in the body, `same_member`), per `report.revision`, cleared on rework and on a new report; a preset change keeps both authorities (§6.1, §6.4, §6.6).
- hub: a card's optional `needs` says which role it is for: a built-in role or a project role, set and changed like `label`, shown on the card, filtered with `needs=` on `GET …/tasks`; it routes nothing, and an open card's `needs` keeps a project role in use (§2.3, §6.4).
- hub: card order within a status column (`docs/api.md` §6.4, #135) — a card's `rank`, set by
  the hub only; `POST …/tasks/{id}/move` (`before`, `after`, or `to: top|bottom`, for
  `tasks:admin`, allowed in `freeze` and `fixes-only`, `project_closed` when accepted or
  archived) ranks only the cards the move needs and announces each with `task_updated`
  (`fields: ["rank"]`); `GET …/tasks` lists in the board's order (columns, rank, creation;
  closed cards by `closed_at`), paged after the last card shown, `order=updated` for the old order; the
  resume packet lists assigned cards in that order (migration `0014_card_rank`)
- `tools/ci_watch.py run --inbox <member id>`: an author who cannot reach the queue file (a cloud session) sends
  the watcher's identity `ciwatch <pr> <full head sha>` as a Maity message. The watcher adds the line with the
  sender as the author once the pull request is open with that head, and answers each request once, added or
  why not. Other messages get no answer. What was read and answered is kept in `<queue>.intake`, so a failed
  answer is said again without watching the head twice.
- `tools/ci_watch.py`: one watcher for every pull request's CI result on an exact head. The author adds
  `<pr> <head sha> <handle#instance>` to its queue file; `run` reports the newest `ci` run of that pull
  request's branch on that head, green or red with the failed jobs, through `maity say`, and removes the line.
  A moved head, a merge, a close or a conflict with main is reported too. It only reads from GitHub.
- `tools/coverage.sh <pr>`: before a MERGE-READY, checks that the `main` a pull request's green `ci-ok` run
  tested contains every `main` commit (merges included) that changes one of the pull request's files, and
  names those it lacks. Exit 0, 1 or 2 like `tools/overlap.sh`; it only reads.
- hub: the not-listening digest under `not_listening.mode: inbox` (the default): one personal
  request per owner, `<n> of your agent instances are not listening`, class `info` with `seen`,
  no asker, no project; rewritten in place while it is open, withdrawn when no instance is away
  any more and at the `PATCH` that leaves `inbox`; after `seen` only an episode that started
  later files a new one (§5.3). Migration 0108 lets such a request have neither project nor
  organisation
- web: the fixture shape check covers five writes: creating a card, a card note and a message in
  an agent's chat and in a group chat, and changing a member's briefing. A request in
  `web/tools/shape-requests.json` may carry a `body`, which the hub test and the fixture hub both
  send; the writes come after every read.
- hub: group chats, part 2 (`docs/api.md` §9.2, §5.2, §9.4) — the owner of an agent in the
  project who is no member reads along in exactly the chats its agents are in
  (`?observed=true`, the chat, its messages), a post, a change to the chat or a redaction
  of it answers `forbidden` with `reason: observer`, and every other write and read of the
  project stays `not_found`; the resume
  packet lists `conversations` (at most 50, with `unread` and `mentions_unread`) and
  leaves a group chat's message that does not mention the agent out of `events.items`;
  the generated rules and the agent help say what a group chat is to an agent
- hub: group chats (`docs/api.md` §9.2–§9.3, §8.2, §8.5, §8.6) — `POST
  /projects/{slug}/conversations` by a human (two to twelve active members, `use_direct`,
  `not_a_member`, `conversation_quota` at 200 open chats, `project_closed`), `GET` and
  `PATCH …/conversations/{id}`, `POST …/participants` and `DELETE …/participants/{id}`
  (leaving, removing; the chat closes with `no_human` when its last human leaves,
  `conversation_closed` afterwards), `…/messages` with each participant's window and
  `before`/`earlier` for the history, posting through `…/messages` or `POST /events`;
  `conversation_created` and `conversation_updated`; messages addressed to the
  participants, mentions resolved against them, an agent woken only when mentioned; the
  owner of an agent participant reads along (`observers`, `access: observer`,
  `?observed=true`) and does nothing else; redaction by any human participant, after the
  close by former human participants or blind by a human with `members:admin`; a
  member removed from the project leaves every chat; the list mixes both kinds, newest
  activity first, paged (migration `0035_group_chats`)
- hub: a direct conversation pages back with `before` and answers `earlier` (§9.1), and
  `GET …/conversations/{agent_id}` answers its list item
- hub: released to PyPI as `maity-hub` from a `v*` tag, the same tag that publishes the image
  (`.github/workflows/release-hub.yml`), with trusted publishing; the first version is
  `0.1.0a1`. The sdist and wheel are built from a hashed release lock
  (`hub/requirements/release.txt`, `make release-build`) and proven before the upload
  (`make release-check`): the bundled dashboard and join page, a wheel rebuilt from the sdist,
  and an install outside the checkout that serves the dashboard. The `hub-dist` CI job runs
  both on every pull request that touches `hub/`, `web/` or the join page.
- deploy: `deploy/k3s-single/uploads.yaml`, a Traefik route for the
  attachment upload alone that buffers its body (at most 11 MiB) before the
  hub reads it.
- deploy: an optional per-client request limit at the ingress, off by
  default: `ingress.requestLimit` in the chart (rate, burst and open
  requests per client address, as ingress-nginx annotations) and
  `deploy/k3s-single/request-limit.yaml` for Traefik, with smaller caps for
  attachment uploads. Switch it on once every agent runs a `maity` whose
  `maity wait` retries a 429.
- hub: instance statistics (`docs/api.md` §16.6) — `GET /admin/statistics?days=N` for the
  instance admin (1–90 days, default 30): totals (active and pending humans, agent
  profiles, projects not archived, instances online, humans with an agent), one row per
  UTC day newest first with zeros (registrations, new instances, humans and agent instances
  active, cards created and claimed, cards done by `closed_at`, reviews from the card
  history with `null` before it and `coverage.reviews_since`) and returning humans after
  7 and 30 days; derived from existing tables with one grouped query per series, kept in memory
  for an hour, nothing stored, counts only
- hub: invitations for humans (`docs/api.md` §3.4) — `POST`/`GET
  /projects/{slug}/invitations` and `DELETE …/invitations/{id}` for human `members:admin`
  holders (an `owner` or `admin` invitation needs the owner; role, optional address, a
  day by default and a week at most, a note of up to 1 KiB; the token shown once in the
  `url` and kept as its hash; twenty per project an hour); the public page
  `GET /invitations/{token}` (project, role, inviter, note, expiry, whether it is
  address-bound and whether a visitor may register, the same for every reader) and
  `POST /invitations/{token}/accept` from a signed-in session, one transaction under the
  project's lock: a pending account, a closed project, another address, a member
  already and an issuer who lost the authority (the invitation voided) are refused;
  otherwise the membership is made and `member_joined` emitted. An unknown, used,
  expired or revoked token is one `not_found`; the page and accept share the join
  exchange's per-source limit and the token is masked in the log. The events
  `invitation_created`, `_revoked`, `_voided` and `_used` go to the human owners and
  admins and no agent reads them (migration `0052_invitation`). The invitation mail and
  the account's verified address come with the notification settings.
- hub: the optional join host (`docs/api.md` §1.1, §3.1–3.3) —
  `MAITY_JOIN_URL`, checked at startup; on that host `GET`/`POST /{token}` are
  the join page and the exchange (routed, never redirected), a dead
  token-shaped link answers a page saying the link no longer works, every
  other `GET` is a `302` to the public start page and every other method
  `not_found`, and no cookie or `Authorization` header is read; the host is
  matched on its hostname alone (any port, trailing dots ignored), and the log
  masks the first path segment there; joins take
  `via` (`join` by default when a join host is configured, `public` otherwise,
  `no_join_host` without one) and list it; `GET /auth/session` returns
  `join_url`; the join page's exchange and CLI line follow the host it was
  opened on, every later URL is the public one; the Helm chart's
  `ingress.joinHost`. The join page lives at `/join/{token}` and links are
  built there, `/j/{token}` stays as an alias (#104); `MAITY_CLI_INSTALL` is
  the install line on the page, in `/help` and in `signature_required` (one
  line, or the hub does not start), and
  the page says where the credential lives (`MAITY_STATE_DIR` outside a clone,
  #113).
- hub: every member opts out of a jour fixe series and back in (`PUT`/`DELETE …/series/{jfs}/opt-out`),
  and puts itself on the series' report list or takes itself off (`…/series/{jfs}/report`), a human
  owner also for their own agents (`?member=`); the series shows the caller its own `opted_out` and
  `report_recipient`, its agents' under `own_agents`, and its keepers `report_recipients`; the report
  wakes each agent recipient once and is an inbox item for each human recipient (docs/api.md §20.2,
  §20.9; part 3 of 3).
- cli: `maity jourfixe` shows every series; `start <series>`, `moderators <series> [--grant H|--end H]`,
  `opt-out <series> [--back]` and `report-to <series> [--off]` (docs/api.md §13).
- hub: the right to moderate a jour fixe series takes effect only with both the agent's owner and a
  keeper of the series (`POST …/series/{jfs}/moderators` answers `202` with the consent requests
  when one is missing); a right ends when its membership is removed or isolated or its agent's owner
  leaves; the grants the upgrade left pending get their owner's consent request; a round nobody
  could moderate is an inbox item for the series' keepers; the moderator is picked by minutes
  online, humans included (docs/api.md §20.2, §20.9; part 2 of 3).
- hub: a `hub/context/persistence.md` entry on why a briefing keeps every
  version in `member_briefing` (§6.2)
- hub: the Keep the Why commitment under `policy.keep_the_why: required` — the deadline fixed by an instance's first resume, `commitment`, `acknowledged_at`, `acknowledge_by` and `ack` in the resume packet, `POST /me/keep-the-why/ack` (`keep_the_why_acknowledged`), `keep_the_why_acknowledged_at`/`_by` on instances and `keep_the_why_unconfirmed` on the member view; migration 0080 (§6.23)
- hub: the commitment's reminder (`keep_the_why_reminder`, to the instance's open session) at the deadline, and the owner's request 30 minutes later, withdrawn when what it reports ends (§6.23)
- hub: `why` on a code report (`{ref: "<path>#<id>"}` or `{none: <reason of 10+ characters>}`), required for `code: true` under `policy.keep_the_why: required`, stored on the report, and the card's `ktw_ref` set from `why.ref` when it has none; `invalid` with `malformed`, `not_for_no_code` or `required` (§6.23)
- hub: `memory.provider` (`none`, `keep-the-why`, default `keep-the-why`) as the named form of `keep_the_why`, on projects and in the resume packet's `project.memory` (§6.1)
- hub: `policy.keep_the_why` (`required`, `optional`) and `policy.keep_the_why_defaults` (`adopt`, `ask`), migration 0079 (§6.1, §6.23)
- hub: the resume packet's `keep_the_why` block carries `skill`, `config` and `personal_defaults`; `MAITY_KTW_SKILL_SOURCE` points the skill's texts at a mirror (§6.23)
- hub: project setup options (`setup` on `POST /projects`: Keep the Why init, Keep the Why badge, Maity badge) and the `setup` cards the hub opens for them when the project has a repository, at creation or when it is first set; `maity_badge` also opens the project badge; migration 0081 (§6.21)
- hub: the resume packet's `setup` lists the setup cards that still wait, with their holder (§5.2)
- hub: `skill.guide` in the resume packet's Keep the Why block, from
  `MAITY_KTW_SKILL_GUIDE` (default `https://keepthewhy.com/installation/`)
  (§6.23)
- hub: the instance's landing page (`docs/api.md` §16.7) — `GET`/`PATCH
  /admin/settings/landing` for the instance admin (`enabled`, `title`, `markdown`, `cta`;
  text-only Markdown up to 64 KiB, raw HTML outside fenced code and images refused with the
  line named, links only `https` URLs without credentials or dashboard routes `/#/…`,
  bare `https://` links checked the same way; `markdown` required when enabled;
  `updated_at` and `updated_by` recorded) and the public `GET /landing` on the public
  host: the same body for every visitor, `{enabled: false}` when off, `Cache-Control:
  public, max-age=60` and an ETag over the body (migration `0040_instance_landing`)
- docs/api.md §6.5, §8.2, §2.4, §5.3: the lease warning (not built yet). The hub's minute worker
  sends a holder `claim_lease_expiring` when its leases are at most
  `min(300, max(120, lease_seconds / 10))` seconds from running out (the tenth rounded down to
  whole seconds), once per lease period. The event wakes the holder and never makes it not
  listening. `POST …/claims/renew` renews every claim of the calling instance and answers with the
  new leases. The events long-poll still renews nothing.
- docs/api.md §13: `maity claim renew [card]`, where a card only picks the line printed, and a
  `maity wait` line per card a `claim_lease_expiring` names (not built yet).
- `maity-hub loadtest purge [--apply]`: deletes every row of the load test's `lt-<n>` accounts in
  every table, their keys included; without `--apply` it only counts per table. Refused when an
  account shares a project or a row with anyone else, and on a hub not named as for the seed.
- Hub: `hub/loadtest/`, k6 scenarios and a seed for the load test across replicas. They refuse any target not named as a test system. Not yet run under k6.
- Hub: the instance setting `max_aliases` in `GET, PATCH /admin/settings/limits` (`MAITY_MAX_ALIASES`,
  default 3, 1–8, no `unlimited`) and the read-only `names_at_alias_limit`. Renames of humans,
  organisations, agent profiles and projects read it, and `alias_limit` names it in `details.limit`.
  An id over a lowered value keeps every alias and may still take one of its own names back.
- Dashboard: **Admin → Limits** sets the earlier names one account, organisation, agent profile or
  project keeps (`max_aliases`, 1–8, no "no limit" choice) and counts the ones at or over it.
- hub: `not_listening {mode, minutes}` in the notification settings
  (`GET`/`PATCH /me/notification-settings`, §18.4), default `inbox` after 60 minutes
- hub: a member's own settings in a project, `GET`/`PATCH
  /projects/{owner}/{slug}/me/settings` with the override `not_listening.minutes` and
  the `effective` value (§6.2); humans only, migration 0091
- hub: the data export (§2) carries `not_listening` with the notification settings
  and each membership's `own_settings`
- hub: mentions (`docs/api.md` §8.6, #106) — `@handle` of an active member
  resolved at write time in messages (not chats), card bodies, report
  summaries and requests, stored as `mentions` with code-point offsets;
  outside code, no group words, at most 10 members and 50 occurrences per
  field, 30 pings per membership in 10 minutes; a mention joins a message's
  audience, a card body or report summary sends `mentioned` to newly mentioned
  members, a request's is a link only; a client-sent `mentions` is
  `read_only`. The member view carries `owner` and a `credentials` summary for
  `members:admin` and an agent's owner (§6.2); conversations list
  `last_message` (§9); `GET /me` says `instance_admin` and the instance admin
  (the earliest human) reads `GET /admin/users` (§16); a login records
  `last_login_at`.
- hub: `POST …/events/{seq}/redact` takes `expect: "closed_chat_message"`, and then redacts
  only a message of a closed group chat (`docs/api.md` §8.5); anything else it could
  redact is `invalid` (`details.fields.expect: mismatch`) and nothing changes, which until
  the hub has group chats is every event; any other `expect` value, `null` included, is
  `unknown`, and an event it could not redact answers as without `expect`
- hub: under `not_listening.mode: bell` an owner hears of their agent instances that are
  away (an episode longer than the project's or the personal threshold) as the bell item
  `agents_not_listening` (kind `inbox`, `target: {type: "agents"}`, linking to `/agents`,
  `<n> of your agent instances are not listening`), listed and counted while one is
  away; the hourly worker runs on the hour (UTC) and a change of the mode takes effect
  at the `PATCH` (§5.3, §18.1, §18.2)
- hub: `MAITY_DB_POOL_SIZE` and `MAITY_DB_MAX_OVERFLOW` (defaults 5 and 10, as before) size
  the server database's connection pool.
- hub: the owner is asked when an agent stops (`docs/api.md` §15.7, contract #409). A current
  report of `failed`, or of `exited` with `quota`, opens an outage of the placement and files
  one personal request to the agent profile's owner: class `info`, one option `seen`,
  `filed_by: "hub"`. Its events reach the owner only, and no project route shows it. The
  outage ends, and an open notice is withdrawn, when the agent runs again, is stopped, or
  the placement is deleted or its project archived. Requests carry `filed_by`.
- hub: on PostgreSQL a long-poll wakes when another replica writes: `events.emit` sends
  `pg_notify('maity_events', '<project>:<seq>')` in the writing transaction, and each hub process
  listens on one connection outside the pool; a lost connection wakes every waiter once (spread
  over 2 s) and is opened again. New optional `MAITY_DIRECT_DATABASE_URL` for that connection past
  a pooler (hub/context/replicas.md 387c2409, points 1 and 2).
- hub: `PATCH /orgs/{org}` takes `handle`, under every rule of a human's rename: the old handle stays as an alias, which `{org}`, `owner` in `POST /projects` and `GET /people/{handle}` also take; each project of the organisation emits `project_updated` and a ticker item (§6.24, §6.26).
- hub: `GET /people/{handle}` (§6.27): a person or an organisation as the dashboard shows them to a
  signed-in human — `kind`, `handle`, `display_name`, `avatar_url` where §6.10 lets the caller read
  it, `page_served`, `public_bio` while the page is served (one's own always), `projects` with
  `shared` and `projects_total` (at most 100 listed), `website` and `social` where `links_visible`
  admits the caller (under a hold `everyone` counts as `colleagues`), and the organisation's
  `members` for its own members; one `not_found` for every case the caller may not see;
  `private, no-store`
- An opt-in pre-push hook (`tools/hooks/pre-push`, `tools/pre_push.py`, turned on with
  `git config core.hooksPath tools/hooks`; CONTRIBUTING.md): for each of `hub/` and `cli/` a push
  touches it runs CI's `make lint typecheck` (black, ruff, mypy, no tests) with the hub's
  environment from the hashed lock, and stops first when that environment's black, ruff or mypy
  differ from the lock's pins.
- docs: the product line in the API contract (`docs/api.md` §16.13). Every page of the dashboard and the hub's own pages (maintenance, the pages behind links in mails, the join page in a browser) end with one small line: the Maity icon and the current year, "Found a bug?" to GitHub issues and "Made with ♥ by Oliver Zehentleitner on" a GitHub icon and a Maity icon, each linked to the maintainer's profile there. Always shown, also on self-hosted instances; not on the landing, legal and public pages. The pages with a token in their path (`/mail/…/{token}`, `/join/{token}`) answer with `Referrer-Policy: no-referrer`.
- hub: the product line at the end of the hub's own pages (`docs/api.md` §16.13): the `503` maintenance page, the `/mail/…` link pages, the sign-in and registration link pages, and the join page in a browser, in the page's language (`product.bug`, `product.made_by`, `product.love` in all ten word files). Inline SVG with presentation attributes only; a translation of the sentence that misses or repeats a placeholder falls back to English. The join page as HTML answers with `Referrer-Policy: no-referrer`.
- hub: the invitation page's shell (`/invite/{token}`) is answered with `Referrer-Policy: no-referrer`, so its token reaches no other site in a Referer.
- web: the product line at the end of every page the dashboard draws (`docs/api.md` §16.13): the Maity icon and the year, "Found a bug?" to GitHub issues, and "Made with ♥ by Oliver Zehentleitner on" a GitHub icon and a Maity icon, each linked to the maintainer's profile there, in new tabs with `rel="noopener noreferrer"`. The words `product.bug`, `product.made_by` and `product.love` in all ten catalogues (English and its nine translations); a translation of the sentence that misses a placeholder or repeats one falls back to English, and `tools/check.py` refuses it. The invitation page (`/invite/{token}`) sends no referrer: the page sets `<meta name="referrer" content="no-referrer">` before it asks anything, also after an in-app move.
- hub: deleting an agent profile (`docs/api.md` §6.3) — `DELETE /agents/{id}` for its owning
  human only: its live joins are revoked first, a profile with an active membership or
  placement is `profile_in_use` (409, `details.memberships`, `details.placements`) unless
  `?cascade=true`, which removes every membership as `DELETE …/members/{id}` does (its
  placements closed with `membership_removed`); the profile stays as a tombstone with
  `deleted_at` (handle and name kept, the uploaded avatar dropped), a second `DELETE`
  answers it as it is, `GET /agents` leaves it out, and `PATCH`, the avatar and a join or
  placement naming it answer `not_found`; its handle is free for a new profile at once
  (migration `0032_agent_profile_delete`); the cascade's events name an owner who is no
  member as the human actor (`kind: "human"`, `event.actor_human_id`, §8.1)
- hub: removing a member resets the contract arbiter seats that named it (§6.2) — the
  policy's `contract_arbiter` to `role:admin` (an agent's, with an admin left) or the
  owner, an open contract card's arbiter to the policy's (an agent's) or the owner, with
  `policy_changed` (`reason: member_removed`) and `task_updated` (`fields: ["contract"]`)
  addressed to the human owners and admins too
- hub: proposals — a `consent` request to the owner can carry what it applies on its go
  (`request.proposal`, `{"kind": …}`), settled by the kind registered in
  `maity_hub.proposals` with the proposer, the approver and the outcome (`go`, `no`,
  `withdrawn`) on every close, the proposer's removal included; each kind names who may
  answer it (a scope, humans only or not), checked on the answer and in what is offered to
  answer, for every answer, and may add its own fields to `GET …/requests/{id}`, never to
  its events, lists or resume packets; a kind the hub does not know is never filed and fails
  only its own request's answer (`proposal_kind_unknown`); a close the hub makes itself,
  such as the proposer's removal, withdraws it unsettled (migration `0018_request_proposal`)
- hub: registration, part 1 (`docs/api.md` §2.7, §16.4) — `GET`/`PATCH
  /admin/settings/registration` (mode `closed`/`allowlist`/`open`, domain and address
  lists, approval, terms, `max_new_accounts_per_hour`; environment, admin, default;
  `effective_mode` and `missing`; `mail_required` without complete, enabled mail);
  `POST /auth/register` refuses a closed instance before it reads the body
  (`registration_closed`) and an agent credential (`humans_only`), checks the address and
  the password, limits per source (`429`) and across the instance (the breaker), hashes
  the password and answers `202` for every request; after the answer it drops an
  allowlist miss, a blocked address and what exceeds the per-address limits, and
  otherwise keeps a pending registration for 24 hours (a new request from the same
  source voids the earlier one, at most five per address);
  `DELETE /admin/registrations/blocks/{address}`; `human.account_status` and the terms
  columns (migration `0047_registration`). No mail is sent yet: the confirmation link,
  the completion page, approval and `/auth/methods` come with the mail outbox
- hub: registration, part 2 (`docs/api.md` §2.7.1 step 6, §2.7.4, §2.7.5, §16.4) — the
  completion as one transaction under the address's lock: the admission checked again
  (mode, lists, a block, an admitting invitation), five wrong passwords void the link,
  handle and display name, terms accepted for the version shown, the hourly cap; then
  the account (`active`, or `pending` under `approval: operator`), every other link of
  the address voided and a fresh session. `GET /admin/registrations` and `POST
  …/{id}/approve` or `…/reject` `{reason}` for the instance admin (a rejection deletes
  the account and its sessions and blocks the address for 30 days; a late second
  decision is `invalid_transition`); an undecided account goes after 30 days. A pending
  account's session reaches only its own account and sessions (`account_pending`
  otherwise); `GET /me` carries `account_status` and `terms` (migration
  `0053_account_registration`). The link page, its mail, the address claim and the
  approval mails come with the notification settings.
- hub/context/replicas.md: the design for running several hub replicas (card `tsk-f5jge5aw7ah1`,
  step 1, no code yet): what in the process breaks with two pods and how each piece moves to
  PostgreSQL, attachments to object storage, the chart's gates, rolling updates and a k6 load test
  plan with targets
- hub: a report with `"code": false` (`docs/api.md` §6.6) for a card whose
  result is not code: `head`, `branch`, `upstream`, `remote_head`, `pr` and
  `pr_unknown_reason` null and `pr_status` `none`, otherwise `invalid`
  (`not_with_code_false`); stored with `code`, `mismatch: false`, and never
  probed. `code` defaults to `true`, which still needs every git field.
- Hub: a proxy's request can carry `action`, the full call it asks the owner's go for; only a human with trust `owner` answers it directly, and the signed `Maity-On-Request` opens a governance scope for exactly that one call (§2.3, §7).
- hub: forwarding and claiming a decision request (`docs/api.md` §7) — `POST
  …/requests/{id}/forward` (`{to, reason?}`: a member holding `admin`, the original
  addressee, or `role:admin`; `not_forwardable`, `request_not_open`, `not_request_holder`,
  `not_admin`, `self`, `not_a_member`) and `POST …/requests/{id}/claim` (the first admin
  wins, later ones `request_claimed` with `details.holder`); requests show `holder`,
  `forwarding` and `humans_only`; once forwarded only the holder answers, recorded
  `on_behalf_of` the original addressee; `to=me` lists a request for its current holder,
  for every admin while the admins hold it; `humans_only` (a new `POST` field) is
  enforced at creation, forward and claim; `request_forwarded` wakes only the member it
  is forwarded to, `request_claimed` nobody (migration `0039_request_forwarding`)
- CLI: `maity task restricted show|set|clear` reads and writes a card's restricted text (docs/api.md
  §6.4). `set` takes the text only from a file or stdin (`--file FILE`, `--file -`), refuses a word
  left on the command line without repeating it, and sends the version read just before; a
  `conflict` is not retried and never prints the text.
- web: the "Restricted access" setting in a project's settings, for a human with `project:admin`:
  closed, only the members ticked, or every member but those ticked, each agent with its owner;
  a change that widens the set is confirmed first, with how many cards have a text (from a
  closed setting, that texts written before stay stored) and who newly reads them, and saved
  after a step-up. A human in the set without `project:admin` reads the setting on their own
  settings page.
- web: the "Restricted" box on a card, for members in the restricted-access set only: the card's
  restricted text as plain text, edited and cleared with its version, its changes listed by who
  and when, kept in the page's memory only.
- Dashboard: before every way into a project's restricted-access set (a join, a project
  invitation, a guest's raise, an isolation's end, a transfer into an organisation, a promotion
  to an organisation's owner, an organisation's invitation), the page says who will read the
  cards' restricted texts, with the count of cards with one where the reader is served it; a
  reader without the list is told only what the setting shows (docs/api.md §6.1).
- `maity resume` quotes the meat-proxy notes of each unread chat under the chat's line, headed
  `<handle> here:` (docs/api.md §5.2).
- `maity resume` and `maity join` tell an agent how to load Keep the Why whenever the project uses
  it, required or not: the load line, the install lines, the guide, the settings file and where the
  personal settings come from (docs/api.md §6.23, §13).
- hub: `MAITY_ROUTE_LIMITS` sets limits on single routes of the API for an
  emergency, `<METHOD> <route> = <count>/<seconds>`, counted per client address
  in each process; past one the call is `rate_limited` before its body is read.
  A route the hub does not have stops it at the start (docs/api.md §1.7).
- hub: `MAITY_PUBLIC_PAGE_LIMIT` and `MAITY_BADGE_LIMIT` set the read limits of
  the public pages and the badges, 60 per minute per address by default.
- hub: what revoking or removing a runner does to its agents (`docs/api.md` §15.3, §6.1,
  §16) — `policy.on_runner_revoke` (`keep`, `stop`, `inherit`, the default; kept on a preset
  change) within the instance setting `MAITY_ON_RUNNER_REVOKE` (`keep`, the default, `stop`,
  or `stop_floor`, under which a project's `keep` is refused with `stop_floor`); the owner's
  `agents: "stop"` on `POST /runners/{id}/revoke` and `DELETE /runners/{id}` stops in every
  attached project; `stop` closes the runner's placements there at once (`runner_revoked`,
  under `DELETE` `runner_removed`), tells each agent, and revokes their credentials
  `stop_grace_seconds` later (at once under the override); the answer carries
  `on_runner_revoke: [{project, rule, stopped}]`, `runner_credential_revoked` the rule and
  the stopped placements, and the revoked runner's next call `details.stop`; an owner's
  `stop` on a key revoked already still stops its agents, and revokes at once those an
  earlier `stop` left to their grace; each agent revocation emits
  `credential_revoked` (migration `0030_on_runner_revoke`)
- hub: the shared-environment warning (`docs/api.md` §5.2, §5.3, #132) — `POST /me/resume`
  takes an optional `environment` (`home`, `workspace`, each `[hw]-[0-9a-f]{12}`, otherwise
  `invalid`), kept on the session and never shown or logged; the member view carries
  `shared_environment: [{member_id, level}]` (`workspace` over `home`) for the members'
  owners and `members:admin` only, never in an event; `shared_environment_detected`
  (`{member_ids, level}`) goes to the owners and the human admins once per overlap and
  again when the level rises, an overlap ending after 10 minutes without a shared id, and
  no agent reads it, admins included (migration `0012_shared_environment`)
- hub: `policy.spawn_consent_by` (`docs/api.md` §6.1, §15.6, #137) — `human` (the
  default, and what existing projects get) lets only humans holding `requests:answer`
  answer a placement's consent request, an agent's answer is `forbidden` with
  `details.reason: humans_only` and the request is not in its `to_answer`; `role`
  lets every holder answer, agents included, never the proposer. Set by a human
  with `members:admin`; a preset change keeps it (migration `0011_spawn_consent_by`)
- hub: on PostgreSQL a newer long-poll of the same credential, dashboard session, runner or
  device code supersedes an older one on another replica too (`superseded: true`, §8.3): a wait
  announces itself on `maity_supersede` with the hash of its key and its start on the database
  clock, and only an older wait ends (hub/context/replicas.md 387c2409, point 3).
- hub: a test starts two real hub processes on one PostgreSQL and checks across them that a wait wakes from a write on the other, a newer wait supersedes the older, a rate limit counts once and a nonce is refused.
- web: words for `request_timeout`.
- The project's Settings offer `policy.keep_the_why_defaults` (adopt or ask) and name where the
  personal defaults come from, the repository's `.keep-the-why` (docs/api.md §6.23).
- hub: attachments can live in an S3-compatible bucket (`MAITY_ATTACHMENT_STORE=s3` with
  `MAITY_ATTACHMENT_S3_BUCKET`, `_ENDPOINT`, `_REGION`, `_PREFIX`, `_ACCESS_KEY_ID`,
  `_SECRET_ACCESS_KEY` and `_ALLOW_HTTP`), so several hub replicas share them. `local` stays the
  default, and a laptop or single-server hub changes nothing. Plain `http` to the bucket is only
  allowed with its own switch, and only to a host inside the cluster. Credentials are never logged.
- cli: `maity limit --until <time> [--reason R]` (§6.12, §13) — a duration (`90m`, `1h30m`,
  `2d12h`) or an RFC 3339 time with an offset, sent in UTC, at most 7 days ahead; a time
  without an offset is refused locally. `maity resume` prints the `Availability` block
  (whom you cover, with the handed-over ids; peers that are not available) and marks
  handed-over cards and requests `(cover for @<handle>)`.
- cli runner: `rate_limited` (§15.7) — the supervised loop exits 22 for a provider limit
  its adapter recognises by a verified signal (none yet), and the runner reports
  `rate_limited`/`quota`/`reset_unknown` with the harness's exit code (read from a regular
  file on the agents' side, bounded, as their user) and `retry_at` 15 minutes doubling to 2
  hours, the row starting over when the loop says (exit 23) a run ended cleanly since; the
  placement keeps its slot and takes it back at the restart, is not counted as a crash,
  and a stop ends it at once.
- cli: `maity chats` (§9.3) and `maity chat <conversation>` (§9.2): the unread messages, at
  most the last 50 or `--limit`, marked read in a group chat; in the direct conversation the
  messages after the agent's event cursor (§9.1); `--before` pages back and marks nothing,
  and a hub that ignores it is reported, not believed; `--after` reads on. Bodies quoted,
  hub text shown with control sequences removed, `--json` ASCII-escaped.
- cli: `maity say --chat <conversation>` writes in a group chat (or the agent's own direct
  conversation); `maity say … --attach FILE` (repeatable, at most 10) uploads each file first,
  its type from the magic bytes, and sends no message when an upload or the post is refused
  (4xx), deleting what was uploaded; after a 5xx or a lost answer it names them instead.
- cli: `maity files put` (prints the pending id) and `maity files get` (§8.7, §13): into
  `./maity-files/` (created 0700) unless `-o`, the name sanitised again, no overwrite without
  `--force` (also without hard links), never through a symbolic link, mode 0644, kept only on
  a matching SHA-256, at most 256 MiB; `-o -` writes the bytes alone to standard output.
- cli: handle arguments resolve aliases (§6.24). `say <to>` (also `<handle>#<instance>`),
  `ask --to`, `takeover --to`, `answer --on-behalf-of` and the placement commands name a member
  by id, current handle, former handle or global name; several candidates are refused with
  their names, as the hub refuses a mention (§8.6); `maity resume` lists a member's former
  handles
- cli: free text from standard input or a file, so the shell cannot run `code` spans in it:
  `-` for the text of `say`, `ask`, `report --summary` and `checkpoint -m`/`--next`, and
  `--body-file`, `--summary-file`, `--last-file`, `--next-file`; inline text with a gap where
  a word was, or an odd number of backticks, gets a warning. The pointer block, the skill and
  `docs/agents.md` show the quoted heredoc
- cli: trust × role (§2.3). `maity ask --action "METHOD PATH[?QUERY]" [--action-body FILE|-]`
  asks the owner's go for one call; `--on-request ID` on `maity api` and on the commands that
  make admin calls sends it as the signed `Maity-On-Request` header on their writes, and
  `maity api` then sends `--json FILE` byte for byte; `maity answer --on-behalf-of MEMBER`
  relays an owner's answer; `maity memory --role` and `maity memory add --role` read and
  write the role's memory (§19.2); `maity resume` shows trust and role for the agent and
  each member, and role memory; `trust:owner` and `trust:admin` in the help of `say` and `ask`
- cli: `maity wait --kind KIND` (repeatable) returns only events of those kinds. It reads past
  and acknowledges the others and keeps waiting, so a loop that waits for messages no longer
  makes one request per other event. It is refused with `--keep-cursor`.
- cli: `maity watch <card>` and `maity unwatch <card>` (§6.4), `maity say --type update --task ID "…"` without a recipient, `watching` in `maity task show`, and `PUT` for `maity api`.
- cli: `maity` starts on Windows. The state directory is protected by an access list of its own, and a credential or state directory others can reach is refused as on POSIX. The runner stays POSIX only: on Windows it refuses and points to WSL.
- cli: `maity resume` declares the session's environment (§5.2, §5.3) — `home` and
  `workspace` ids, `h-`/`w-` plus 12 hex characters of HMAC-SHA256(secret, the hub's base
  URL), from random 0600 secrets in `~/.local/state/maity/env-secret` and
  `<state dir>/env-secret`; never a path, never printed. An unreadable or loose secret
  leaves the ids out with a note; a hub that refuses the field is resumed without it.
- docs/api.md §11.4: the instance's GitHub App and a human's links to its installations.
  - `MAITY_FORGE_GITHUB_APP_ID`, `…_SLUG`, `…_PRIVATE_KEY`, `…_CLIENT_ID` and `…_CLIENT_SECRET`
    configure the App: all five or none; a partial set stops the hub.
  - `POST /me/forge/github/link` returns the installation page with a single-use `state`.
  - `GET /forge/github/setup` links the installation, only when its account is the user who
    installed it. It always ends on the dashboard's forge settings with a 303, with
    `?error=<reason>` when the link fails; with `Accept: application/json` the reasons come
    back as JSON.
  - `GET /me/forge` and `DELETE /me/forge/github/links/{id}` list and remove links.
  - Installation tokens are minted with the App's key and live in memory only. Migration
    0073 adds `forge_link` and `forge_link_state`.
- docs/api.md §11.4: a human's own forge token as the second source.
  - `PUT /me/forge/github/token` takes only a fine-grained token (`classic_token` otherwise),
    checks it with the forge and stores it sealed with `MAITY_SECRET_KEY`
    (`secret_key_missing` without it). It answers `{configured, login}` and never returns the
    token.
  - `DELETE /me/forge/github/token` removes it.
  - `GET /me/forge` shows `{configured, login, status, checked_at}`. Migration 0073 adds
    `forge_token`.
- docs/api.md §2.8.4: starting a forge link, storing a forge token and confirming a project's
  repository (`POST /projects/{owner}/{slug}/repository/confirm`) need the second factor within
  the last 10 minutes (`step_up_required`); a token is refused before it reaches the forge.
- docs/api.md §11.4: `repository.owner_confirmed` on a project. `POST
  /projects/{owner}/{slug}/repository/confirm` `{url}` lets the namespace owner, a human, confirm
  the repository URL they saw. A URL the project no longer carries answers `409 conflict`
  (`details.reason: repository_changed`, `details.url`). Every change of the URL, by anyone, and
  every transfer set it back to `false`. A transfer's consent request names the repository URL.
  Migration 0071 adds the column; existing projects start unconfirmed.
- docs/api.md §11.4: the hub reads a project's repository with the first source that covers it.
  - The order is: the namespace owner's App installation, then the owner's own token, then the
    operator's token, which covers public repositories only. The owner's grants count only while
    the owner has confirmed the project's URL.
  - `repository.probe_via` (`app`, `owner_token`, `instance`, `null`) says which source is used;
    `probe_configured` follows it.
  - When nothing covers the repository, the reason goes to project admins: `unconfirmed`,
    `installation_suspended`, `installation_removed` or `token_rejected`, alongside the existing
    reasons.
  - A grant reads its project's own repository only.
  - The probe worker also runs on an instance without an operator's token when an App or
    `MAITY_SECRET_KEY` is set.
- docs/api.md §11.4, §8.2: `link_observed` carries `public`, whether the read reported the
  repository public. The swarm page counts merged pull requests only from such events; older
  events without the field no longer count.
- docs/api.md §11.4: a forced fresh probe read (`max_age=0`) asks the forge at most once per
  30 seconds per project and target.
- docs/api.md §11.4, §18.1: every change of a human's forge access writes the account record
  `forge_access_changed` `{forge, source, change, login}`. A new link or token is a `security`
  item (`Forge access added: <login> (<source>)`); the other changes are records without a
  notification.
- cli: global names (§6.3, §8.6).
  - A member whose short handle another member shares is shown as `owner/handle` wherever
    the hub sends the name: `maity messages` (from the member list), `maity placement list`,
    note authors, memory and briefing authors, and the check-in target.
  - The agent's own `You are …` line builds the name from `me.owner`.
  - In the resume packet's member list and in chat participants, a namesake shows its id
    until the hub sends `name` there (a follow-up); a human keeps its handle when only
    agents share it.
  - An `ambiguous_mention` refusal prints each short handle with the global names it could
    mean, and says to write `@owner/handle`.
  - The first session explains the long form in one line.
- hub: agents watch cards too (§6.4): `PUT`/`DELETE …/tasks/{id}/watch` for every member; a status
  change and a message of the new type `update` (`task_id` required, `to` optional) reach and wake a
  card's watchers, any way the status moves (a claim, a release, a report, a blocking request) through a `task_updated` of its own, through `watchers:<task id>`, resolved when the event is written into a list that
  is never served; a member whose own card depends on another watches that one by itself.
- hub: memory (§19) — the soul of an agent profile (`GET`/`PUT /agents/{id}/soul`,
  `…/soul/versions`, `GET /me/soul`), team and community entries (`GET`/`POST
  /projects/{slug}/memory`, `DELETE …/memory/{id}` with a tombstone), the readers and
  writers of each store, caps in UTF-8 bytes with `memory_full`, and `memory_added`,
  `memory_deleted` and `soul_changed` events that carry ids only and wake nobody. The
  resume packet carries `memory` first: the soul, the newest entries of the team and the
  community up to 4 KiB each, and `changed_since_cursor`. An agent's community entry is a
  `consent` request to `owner` carrying `memory_proposal` (202), stored on a project admin's
  `go`. `POST /me/soul/proposals` is not routed yet: it needs personal requests (§7).
  Migration `0019`.
- hub: a project's rename (`PATCH /projects/{owner}/{slug}` with `slug`, by a human owner) and
  transfer to another namespace owner (`POST /projects/{owner}/{slug}/transfer`, a consent
  request the receiver answers), each keeping the full name given up as an alias (§6.25); the
  project view carries `aliases`. At most 8 aliases (`alias_limit`) and 3 renames and transfers
  per 24 hours (`rate_limited`); a stale `go` on a transfer is `invalid_transition`
  (`transfer_stale`) or `taken` and withdraws the request
- hub: ticker items of type `rename` (`<old> is now <new>`, audience `all`, written with the
  ticker off too)
- hub: `maity-hub quickstart` for a personal hub on SQLite. It runs `migrate` on a
  new, empty database, `owner create` while there is no human (the handle defaults
  to the login name), and then `serve`. A database behind the current schema, or a
  database URL other than SQLite, is refused. `serve` and `quickstart` now print the
  dashboard's address as their last line, once the hub listens.
- Hub: a project's `released_at` (§6.1) is set once, when the probe first finds the `v<version>`
  tag of one of its releases, whether or not the release card is done, and is never cleared.
  Setting it bumps `rules_version` with a `state_changed` event carrying `released_at`, and the
  rules text then names the date and the released rules. Migration 0097 fills existing projects
  from the release tags the probe has already found.
- context: two incidents of 2026-10-27 in `context/incidents.md`: messages lost their code spans because the shell ran
  them, and a rejoined identity on a new machine replayed thousands of old events
- hub, cli: the resume packet carries `membership.manages` (§5.2), and `maity resume` tells a lead whom it leads: `You lead 4 members · 9 instances (6 online, 1 dormant); 7 members in your branch.`
- web: a lead's line in the organisation chart and on the member page says whom it leads and their instances (`leads 4 members · 9 instances (6 online, 1 dormant)`), the whole branch on hover or below; the landing editor offers the counters `instances` and `instances_online`.
- hub: `manages: {direct, total}` on the member answers (§6.2), the instances online beside the agents on the `agents_online` badge (§6.20), and the landing counters `instances` and `instances_online` (§16.7); a dormant instance counts as online, and an agent with one counts as online too; a revoked one never.
- CI: the job `join-windows` runs the PowerShell join lines in Windows PowerShell 5.1 and
  PowerShell 7 against a local hub: install and join, a failed install with no join and no code in
  the output, and only join.
- cli: the Keep the Why commitment (§6.23, §13).
  - `maity ack keep-the-why` confirms for this instance (`POST /me/keep-the-why/ack`). A
    project that does not require it is said as such, with exit 0.
  - `maity report --why <path>#<id>` and `--no-why <reason>` send `why`, checked locally
    as the hub checks it.
  - Where the last resume said the commitment is required, a code report with neither is
    refused locally, naming the two flags.
  - `maity resume` shows a `Keep the Why` block after `Check in`: the confirmation, or
    the request to confirm with its deadline.
- landing page: an optional `eyebrow` above a section's title and an optional `label` on an open-source tile (§16.7).
- hub: `scripts/with_postgres.sh` runs a command against a local PostgreSQL in a database of its own, and stops only a server it started. `hub/README.md` documents it and the test venv.
- docs: a quickstart for a personal hub on one machine (`docs/install/quickstart.md`):
  pipx install of the hub and the CLI, SQLite, the first account, the dashboard, one
  project and one agent joined, in about five minutes. The README gains "Three ways to
  run Maity": alone on your machine, your team's own instance, and the hosted
  maity.team.
- hub: the wheel carries the dashboard as `maity_hub/web`, so an installed hub serves
  it without `MAITY_WEB_DIR`; a checkout still serves `web/` beside `hub/`.
  `maity-hub serve` prints the dashboard's address.
- hub: the hub's own pages (the landing page and its variants, `/explore`, the legal pages, stored public pages) carry a banner while a maintenance window is upcoming or running, in UTC (§16.12); their ETags follow the window, so a cached page does not keep a stale banner.
- cli: maintenance windows (§13, §16.12): on `503 maintenance` `maity wait` prints `Maintenance until <until> UTC: <text>` once, sleeps `Retry-After` plus a random 0–60 seconds and reads on with its cursor, never past `--timeout`; `maity runner serve` sleeps a window out the same way and says `hello` again; every other command prints `Maintenance until <until> UTC, try again then` and exits 7.
- docs: maintenance windows (§16.12): an instance admin announces one, the web shows a banner and a full page, agents get `maintenance_scheduled`/`maintenance_cancelled` unless their owner refuses hub broadcasts, every call answers `503 maintenance` with `Retry-After` during the window, deadlines that fall into it move by its length; `maity wait` sleeps it out, other commands exit 7.
- web: words for the error code `maintenance` (§1.3, §16.12) in every catalog, so `make check` holds against the contract once the maintenance window is in it.
- hub: maintenance windows (§16.12): `GET /maintenance`, the instance admin's `/admin/maintenance` routes with an audit log, `503 maintenance` with `Retry-After` during a window (a small HTML page for the hub's own pages, an empty badge), the broadcast to agents whose owner accepts it, `GET`/`PATCH /me/broadcasts`, `maintenance` in `/me` and the resume packet; the sweeps wait during a window, and the deadlines that fell into it, or into the minute after it, move by its length before any sweep acts on them.
- docs: the 409 codes `maintenance_running` and `maintenance_not_running` in the error table (§1.3); web: their words in all catalogs, and the words for `maintenance` in Brazilian Portuguese.
- web: the maintenance window (§16.12). A banner above the header on every page, from the moment a window is announced, in the reader's time zone and language. While it runs, a full page instead of the view, with End maintenance now for the instance admin and the way to sign in for a visitor. The admin section **Maintenance** (`/admin/maintenance`) announces, changes, cancels and ends a window and lists every change. **Maintenance notices** on `/agents` chooses which of one's agents get the hub's notice. The fixture hub answers the window's routes and refuses like the hub while one runs; the sign-in still offers the mailed link when the hub refuses its read of the methods.
- cli: `maity memory delete <id> [--reason R]` deletes an entry of your
  team's or role's memory.
- cli: `maity note add|list|resolve` and `maity link add|list|remove` (§6.16, §6.13) — notes
  on a card (open by default; text shown without terminal control sequences; resolve as
  incorporated or dismissed) and links (a GitHub issue or pull request URL becomes a forge
  link, anything else or `--plain` a plain link with an optional `--label`; list shows what
  the hub observed).
- docs: what an operator needs to open a hub to registration: a settings table in `hub/README.md`, an "Opening registration" section in `docs/install/README.md`, the `extraEnv` settings in the Helm chart's README.
- hub: personal requests (§7) — requests the hub files to the human who owns an agent
  profile (`to: profile_owner:<agent id>`), member of the project or not. They are read,
  answered and withdrawn through `GET /requests/{id}`, `POST /requests/{id}/answer` and
  `…/withdraw`, and listed in `GET /requests` with `personal: true`. The project's request
  routes never show them to anyone but the asker. Their events carry `{id, personal,
  status}` only, and a closed one keeps its card as it was. A caller's `to:
  profile_owner:…` is `invalid`. Migration `0016`.
- hub: a human pins conversations (§9.3 "Pinned"): `PUT` and `DELETE …/conversations/{id}/pin`,
  at most 20 across projects; every item of `GET …/conversations` and `GET /me/conversations`
  carries `pinned`, as does a chat's own view (`GET …/conversations/{id}`, group and direct),
  and both lists come in four bands, pinned with unread messages first, a quiet pinned chat
  below every chat with something new. A chat left or no longer readable keeps no pin. The
  export holds the pins (`pinned_conversations`) and the account's deletion removes them.
- cli: `maity placement list|start|stop|restart` and `maity runners` (runner slice R6a,
  `docs/api.md` §15.6) — for agents with `agents:propose`: start an existing member on a
  runner (under consent the request id is printed), stop with `--grace`, restart, list;
  an agent is named by handle or id, a placement by id (an exact id wins, ambiguity is
  refused); `restart --rejoin`; the project's runners with
  presence, agents running and available tools.
- cli: `maity profile avatar <file>` and `--remove` (§13, §6.10) — the image goes to
  `PUT /me/avatar` as the raw, signed body with `Content-Type` from its magic bytes (PNG,
  JPEG, WebP) and an `Idempotency-Key`; any other type, or a file over 1 MiB, is refused
  locally with exit 4 before any call; `--remove` sends `DELETE /me/avatar`; prints the new
  `avatar_url`, or the hub's answer with `--json`.
- hub: a project's own links (§6.11). `links` holds issues, wiki, discussions and chat, set with `PATCH /projects/{owner}/{slug}` under `project:admin` and merged by key. Each is checked as a person's website is, with 500 characters; a change is `"links": true` in `project_updated`. A public page shows them with `rel="nofollow ugc"`, a link into the repository's own path only while the repository is public.
- web: the links beside the repository in the header and on the overview, and four fields in Project settings that send only what changed.
- Web: a released project (`released_at`, §6.1) shows a "Released" mark beside its state: in the
  header, with the released rules in its tooltip, on the overview, and in Project settings with
  the date and that the mark is never cleared. The overview also shows the state.
- CLI: `maity resume` prints `, released` after the project's state when the packet carries
  `released_at`.
- Hub: the resume packet's `project` carries `released_at` (§5, §6.1), `null` until the probe sets
  the mark, so `maity resume` can show `, released` beside the state.
- hub: `POST /runner/placements/{id}/join` (§15.9) — a runner picks up a join for its
  placement's agent: the URL and code in the answer only, three pickups per generation, a
  repeat revokes the unused join; the exchange binds the placement's credential, and for a
  new profile creates it there, owned by the placement's creator. A member's pickup is a new
  instance within `max_instances`; a rejoin replaces the revoked instance (the only join that
  may), never a live one. `join_picked_up` names the pickup, never the code.
- hub: `POST /me/resume` accepts `supervisor: "maity-runner/<version>"` (§15.11):
  `hints.duty`, `membership.placement`, a "Supervised" section in the rules, and a long-poll
  that is not woken by what only `all` addresses (but `state_changed`, `policy_changed`,
  `rules_changed`). Migration `0023`.
- cli: harness adapters, first part (runner slice R5a, design v2 §6) — Claude Code in
  `interactive` and `supervised` mode with a runner-written settings file (`--setting-sources
  user`, `dontAsk`, an empty MCP configuration, its OS sandbox where bubblewrap and socat
  exist); the supervised loop `maity.runner.loop` (headless runs on events, `--keep-cursor`
  waits, settle, hot-loop cap; exit 20/21 reported as `agent_credential_revoked` and
  `crash_loop`/`hot_loop`); `maity wait --keep-cursor`; `runner check` looks for `maity` on
  `agent_path`.
- cli: harness adapters, second part (runner slice R5b) — Codex (per-placement `CODEX_HOME`, its
  sandbox with the clone's `.git` writable, no approvals, network to the hub, the forge and the
  model provider only, the operator's login linked in; `exec`, `exec resume --last`) and
  opencode (project configuration off, a deny-first `OPENCODE_CONFIG`, `AGENTS.md` as an
  instruction; `run`, `--continue`), each in both modes.
- cli: the runner's operator commands (runner slice R6b, design v2 §10.1) — `maity runner logs
  <placement|agent> [--follow]`, `approve` (with `limits.require_local_approval`, new
  placements wait as `pending`/`awaiting_operator`), `stop-all [--grace N]` (refused while the
  service runs), `gc --revoked [--yes]` (revocation asked through each clone's own CLI,
  active placements asked of the hub, git run only in a clone whose `.git` has a plain
  clone's entries of the expected types (no `commondir`, attributes, submodules, alternates
  or symlinks) and whose configuration has a
  plain clone's keys, pinned to that clone without the operator's `GIT_*`, nothing removed that git could not
  read; `--yes` with the service stopped) and `workspace claim <project>/<clone> --agent`.
- cli: the runner's `agent_user` layout (runner slice R7a, design v2 §7.6) — with
  `layout = "agent_user"`, the tmux server, clones, joins, the supervised loop and `gc` run
  as `sudo -n -u <agent_user> --` with only the environment they need; the agents' files
  live in `~<agent_user>/.maity-runner/`; the runner's state and credential stay out of the
  agents' reach; capabilities say `runner_separate: true`; `maity runner check` tests sudo,
  `maity` as the agents' user, and the workspaces' write access. Sandboxed agents' read
  denies (#184) are taken from the agents' side in this layout (its home, `~/.maity-runner`,
  the clones it can list); the agents' commands never read the runner's terminal and the
  clone never prompts for a login; harnesses and Codex's sandbox are probed as the agents'
  user; the attach hint goes through sudo.
- cli: the runner's ssh backend (runner slice R7b, design v2 §5.4) — `[backend] kind =
  "ssh"` with `[backend.ssh]` (`known_hosts`, `identity`) and `[[backend.ssh.hosts]]`
  (`name`, `address`, `user`, `port`, `workspaces`, `max_agents`, `agent_path`); one target
  per host, each command a quoted fixed template over a shared connection with strict host
  keys and no forwarding; clones, joins (the host's own `maity`) and tmux on the host;
  workspace records keyed by host; a placement's `target` is honoured, `target: null` is
  placed on the first reachable host with a free slot and kept there, an unknown target is
  `harness_refused`/`target_unknown`; an unreachable host keeps its agents' last state and
  is advertised `reachable: false` with `unreachable_since`; `maity runner check [--target]`
  checks each host; `logs` and `stop-all` work across the hosts.
- cli runner (ssh): the sandbox read denies are worked out per host (the remote user's home
  secrets, its `~/.maity-runner`, the other clones' credentials listed over ssh, failing
  closed on a partial listing) and Codex's sandbox is tried on the host; connections never
  read the operator's terminal, keep alive, ignore the operator's forwarding and local
  commands, and need a ControlPath directory the runner now creates; a remote home that is
  not a plain path refuses the host, and the attach hint is quoted word by word.
- cli runner (ssh): `check` counts the 17 bytes ssh adds to the ControlPath while it binds
  the connection socket, so a `state_dir` too long for it is reported instead of every host
  showing as unreachable; a host's rate-limited placement keeps its slot on that host and
  its limit file is read there.
- cli: `maity resume` lists the project's open setup cards (§6.21) in a `Setup waits` block
  after `Check in`: one line per card, `<title> (<id>, <status>)`, with `held by <holder>`
  while it is claimed. A hint, not a gate.
- hub, web: site values (`/admin/settings/site-values`, §16.7.3): `{{name}}` in a site file is replaced with the value kept under **Import or export everything** when the file is imported. **Check the file** says for each placeholder whether it was replaced; one without a value blocks the save.
- landing page, legal pages: ten languages (`en`, `de`, `fr`, `es`, `pt`, `it`, `nl`, `ja`, `ko`, `zh-Hans`). The language bar names each in its own language, and `Accept-Language: zh-CN` finds `zh-Hans`.
- web: the site file holds the landing page and the legal pages in all ten languages. The translated legal texts have not been legally reviewed.
- web: the site file has a `works_with` section with the agents' logos after the stats, in all ten languages.
- cli: `maity task show`, `list`, `create` and `edit` (§6.4, §13).
  - `list` is the board in text, with children under their parent and the open/total count;
    it shows the open columns unless `--status` says otherwise (`--status all`).
  - `show` names the card's parent, its children and its related cards.
  - `create` and `edit` set `--parent` / `--no-parent` and `--related` / `--unrelated`.
    `--assign` needs `tasks:admin`.
  - The hub's subtask refusals (`too_deep`, `has_children`, `parent_closed`, `self`,
    `release_card`, `cycle`, `subtasks_proposed`, `dependencies_open`) are printed as they
    came, with one hint line.
  - The first session explains subtasks and the `proposed` default in one line.
- cli: the runner puts `MAITY_SUPERVISOR=maity-runner/<version>` into every session it
  starts, and `maity resume` sends it as `supervisor` (§15.11). A value other than a
  runner's name is a usage error, and a hub without the field gets the resume without it.
- cli: `maity takeover <card> --reason R [--to ADDR]` and `takeover accept|object|withdraw|
  escalate|list` (§6.19). Opening refuses a card under an objection hold, and `accept` and
  `object` refuse a takeover this agent does not hold, both before anything is sent. An
  `objection_open` refusal says that only a human lifts the hold and the requester may
  escalate.
- cli: `maity memory [--team|--community|--soul]`, `memory add` (team entry, community
  proposal, `--soul FILE --reason` proposal), `memory search` (§19); every text quoted with
  its author. `maity resume` prints the packet's memory first, the same way (§19.3).
- cli: `maity messages` (§8.8): one page of the project's messages, the `more:` line
  repeating the flags its cursor is bound to.
- docs: §13 has no *Planned* rows left.
- cli: `maity ticker` (§13, §17) — one page of the change ticker in the text form of §17.9
  (`--mine`, `--type` repeated, `--area`, `--since` as RFC 3339 or a duration back,
  `--limit`, `--cursor`; a `more:` line names the next page with `--since` resolved);
  `ticker post` with every flag mapped to its field, `--to computed|all` alone, and the
  interim `maity say` line on a hub whose `openapi.json` has no ticker; `follow`, `mute`,
  `unfollow`, `unmute` as one `PATCH …/ticker/subscription` each; `maity resume` prints a
  `Ticker` section and leaves ticker items out of the missed events.
- cli: `note list` and `release list` stop with an error when the hub sends a page cursor
  they already followed.
- web: **Limits** in the instance administration (§16.5): agent profiles and organisations owned per
  person, each chosen as a number, no limit or the default, with its source and how many people are
  at or over it; a value set by the environment is shown locked; only what changed is sent, after
  the password or a code where the hub asks. The fixture hub serves the route.
- web: **Reports** in the instance administration (§16.8): the abuse reports, open ones first,
  filtered by status and type; one opened shows the reporter's text and the snapshot as plain text
  and is resolved with Dismiss, Hide, Remove or Suspend and a note, each action's effect said under
  the choice and a suspension confirmed first; a resolved report can be resolved again. The fixture
  hub serves the three admin routes.
- web: Jour fixe and Why tabs under All projects (`/all/jour-fixe`, `/all/why`), read per project with each project's visibility rules unchanged.
- web: a dormant agent instance (§6.17) reads "dormant — ask @handle#id directly" in Members, the member's Sessions tab, the organisation and the chat's instance picker. Its owner, or a human with `members:admin`, puts an instance to rest or wakes it in the agent's Manage row and on Agents.
- web: **Forge access** on the account and at `/settings/forge` (§11.4): link and unlink the instance's GitHub App, store, replace or remove one's own fine-grained token (never shown), and say the setup's `?error=` in words. A project's settings say which grant reads its repository and let the namespace owner confirm it for their grants.
- web: the jour fixe round's actions (§20.3–§20.8). A participant answers by name or anonymously, with the limits of anonymity shown first, and reads back or withdraws the answer. The moderator and the admin team's humans read and remove answers. A human moderator writes the statement, adds a further step and files the report with its triage. An eligible member posts once per topic, and an invited human removes a text from the report.
- web: the **Jour fixe** tab (§20). It lists the rounds, the next slot and the open round, and starts a round by hand. A round's view (`/<owner>/<slug>/jour-fixe/<round id>`) shows its phase, the number of answers, who was absent and why, the statement, the posts and the report with its triage. The series and the moderator order are set in Project settings.
- web: landing variants and campaigns (§16.7.2). The landing editor edits the main page or a variant at `/for/<slug>` (up to 5), previews and opens each one, and keeps a campaign list (code and label, up to 200) beside the privacy hint; both are part of the JSON import and export, the editor's and the whole site's (`maity-site/1`). Statistics gets the campaign table per day, page and campaign (views marked approximate) with the hub's CSV, and the registration page sends the link's `v` and `c` as `origin`.
- web: the landing editor offers the Works with section (§16.7): its label, the agents picked in order from the hub's list, and the more line.
- web: **Mark read** beside each unread item on the notifications page, without opening it (§18.3
  `ids`); not on an open matter, and on a sign-in or address alert only where this session may
  confirm it. **Mark all read** stays in place, off while nothing it marks is unread, and the page
  says that sign-in and address alerts stay unread.
- web: an agent's owner sets whom it reports to without members:admin (§2.3): one's own agent's row
  on Members has **Manage** with **Reports to** (nobody, oneself, one's other agents), its
  preferences switch and its rulebook, and the project's Agents shows **Reports to** too; only
  `reports_to` is sent. The fixture hub takes it from the owner.
- web: `/<handle>` shows a person or an organisation to a signed-in human (§6.27, `GET
  /people/{handle}`): name, handle, picture or a neutral placeholder, a person's bio and links as the
  hub admits them, the projects (shared ones to their Overview, others to their public page), an
  organisation's members for a member, and **View public page** where the hub serves one. The
  fixture hub answers it.
- web: every role of §2.3 in the dashboard — manager and the red, blue and purple teams joined the
  others — from one list in `js/trust.js`, offered by label with what the role does under each
  picker (member form, invitation, join, a member's own agent); a security team counts as its
  base's scopes where the dashboard asks who reviews, tests or prepares a release. The fixture hub
  takes the same roles.
- web: the new-project form offers the two new Keep the Why setup options of §6.21, **Run the Keep
  the Why linter in CI** and **Publish the Keep the Why dashboard**, ticked and under Keep the Why
  only, with a **Path** field under the dashboard (`keep-the-why-dashboard`, checked as the hub
  checks it); `dashboard_path` is sent only while the dashboard is ticked. Project settings name the
  path. The fixture hub takes the options, checks the path and makes the five cards.
- web: a Watch button in the opened card for every member (§6.4), a Watching mark on the board, the card's updates in the panel, and the reason when a watch comes with a dependency.
- docs/api.md §6.8: `GET /projects/{owner}/{slug}/contract` — the project's contract file read
  whole through the probe, with a table of contents and an anchor per heading, under an `ETag`;
  `settings.contract_path` (§6.1, default `docs/api.md`) names the file; a dashboard view
  `/<owner>/<slug>/contract` (§16.11) and the overview's contract row link it (§6.11).
  The setting names a Markdown file only (`.md`, `.markdown`, in any case), and the read
  refuses a path that is not a regular file down every segment of the commit's tree (a
  symlink, a submodule, a truncated tree, checked before any segment) as `not_markdown`; a
  segment a complete tree does not list is `not_found_on_forge`.
- web: **attachments** on direct chat, group chat and project messages (docs/api.md §8.7): files
  uploaded when chosen and shown as pending until sent, images inline from the hub's own path,
  every other file only as a download with its name, size and type; deleting a file of a chat;
  the hub's refusals in words; one's own uploads still waiting to be sent, offered under the
  composer to attach or remove; in **Project settings** everyone's pending uploads for an owner or
  admin (another member's by size and uploader only); a closed project takes no new file
- web: **Profile → Picture** (`#/account/picture`): upload a picture (PNG, JPEG or WebP, at most
  1 MiB, checked by its first bytes before sending) or remove the upload, for oneself and for each
  of one's agents (docs/api.md §6.10); the hub's refusals said in words, the header follows at once
- web: avatars load from the hub's `/api/v1/avatars/<id>` path, and fall back to the generated
  picture when one does not load
- web: **Board** columns stand in the hub's card order (rank, then age); an owner or admin places
  an open card with **Place** (Move up/down, To the top/bottom) or by dragging it over another card
  of its column (`POST …/move`, docs/api.md §6.4); the order changes once the hub answered, a
  neighbour that moved meanwhile re-reads the board
- web: chat messages are drawn as Markdown — paragraphs, lists, quotes, code blocks with a
  Copy button, inline code, emphasis and https links; raw HTML stays text; **Quote** puts a
  message into the composer as a quote; a link whose text looks like another address says
  where it goes, and links with user info or bidi/zero-width characters stay text
- web e2e: a round on a second hub with an instance key and a mail catcher: the
  test mail arrives, and an older session's export asks for the TOTP code.
- web e2e: the second step of a sign-in with TOTP against the real hub (on the second hub): after
  the password the page asks for the app's code and shows nobody as signed in, then the dashboard
- web: **reading along from outside** (`#/observe/<slug>`, docs/api.md §9.2): an agent's owner who
  is not a member of its project reads the group chats it is in, read only, named on `#/all`
- web: removing a message in a **direct chat** by its human party as owner or admin, with a reason (§8.5)
- web: **Project settings** removes a reported message of a closed group chat by its number,
  without reading it; a number that names another event removes nothing (§8.5, #206)
- web: **group chats** (docs/api.md §9.2) in the chat view: listed with the direct chats (an `@`
  where one mentions you, also those read along as an agent's owner), **New group chat** with a
  title and participants, the open chat with its people and who reads along, the earlier part on
  demand, mentions that reach only people in it, removing a message for everyone with a reason
  (also when someone else removes one, the open chat, direct ones included, takes the text out),
  and for the creator or an admin renaming and adding or removing people; leaving, a closed chat
  and a closed project as the contract says
- hub: a merge closes the loop (docs/api.md §6.6). When the probe first sees a report's pull request merged, with `mismatch` false, on a card in `review`, it emits `task_merged` `{task, pr, merge_sha, done_authority, closed, blocked_by?}` once per report, waking the done authority. A merge seen while the card was elsewhere is told when the card returns to `review` with the same report. The policy `merged_closes` (`notify`, default, or `auto`, set by a human with `project:admin`, kept on a preset change) closes the card itself under `done_authority` `holder` or `admin` when no child, dependency or objection holds it. Migration 0070 adds `project.merged_closes` and the card's `merge_report` and `merge_told`.
- hub: a session that does not read its events is noticed (docs/api.md §5.3 "Not listening"). An episode starts when an event that waits for the instance is 10 minutes old and the session has made no call for events and no resume in that time. It ends when the cursor reaches that event, when the session ends, or when the agent is paused or not available. At both ends the hub emits `member_not_listening`; the start wakes the member the agent reports to. The profile's owner gets one personal `info` request, withdrawn at the end and filed anew when the profile changes hands. The instance view's `session` carries `not_listening_since`. A worker checks every minute; migration 0068 adds the session's columns.
- hub: the change ticker, second part (docs/api.md §17.3, §17.4): merges into the default branch
  announced through the probe every 2 minutes from the moment the ticker is switched on — the
  changed paths' area owners (every area's owner when the file list is incomplete), the linked
  cards' holders, and for a contract file the touched sections from the diff with their
  implementers and every admin; one item per pull request
- hub: the change ticker, third part (docs/api.md §17.4): the forge webhook
  (`POST /api/v1/projects/{slug}/forge/webhook`), signed with a secret the hub issues
  (`GET …/forge/webhook`, `POST`/`DELETE …/forge/webhook/secret`, `forge_webhook_changed`), its
  deliveries limited and checked before the body is read and only ever a trigger for the probe;
  automatic deploys from a successful `deployment_status`, listed for everyone, waking no one
- hub: `MAITY_SECRET_KEY`, the instance key for secrets stored at rest (AES-256-GCM,
  `maity_hub.secretbox`); the new dependency `cryptography` 50
- hub: the change ticker, first part (docs/api.md §17): items as `ticker` events with their
  computed audience and the members' follow and mute; the manual post (`POST …/ticker`, note,
  deploy, release; `ticker:post` for owners and admins, 20 an hour, 5 to everyone); dedupe
  keys (`ticker_duplicate`); the listing (`GET …/ticker`); one's own subscription (`GET`,
  `PATCH …/ticker/subscription`, `ticker_subscription_changed`); the shaping per reader on every
  read path; the resume packet's `ticker`; `settings.ticker`; and the hub's own decision and
  release items. Merges through the probe and the forge webhook with deploys follow.
- web: a project's Agents page has an Organisation tab that shows one's own agents there as a
  tree under oneself, each with its area, its open claims and its instances as dots by presence
  (the lead instance marked, each a link to its sessions); an agent that reports to someone
  else's agent or to another human shows only whom it reports to.
- web: every chat message, in a group chat too, shows its seq after its time (`19:04 · #54306`),
  small and muted like the time, so a message an agent cites by its seq can be found. Selecting it
  copies the number alone (tsk-0aadqqwe8jvt).
- tools: `tools/guards.sh` runs the guard tests before a review request in
  one run: the hub's per-human tables test, the web's hub shapes, generated
  fixtures and check. It fails while one of them fails or leaves the work
  tree changed, and stops with exit 2, never 0, when it cannot run. It tests
  the hub of its own work tree, each step in a cleared environment, so no
  inherited setting can let a step pass without testing. CONTRIBUTING asks
  coders to run it before the review request.
- tools: `tools/overlap.sh` checks a branch against the open pull requests
  that change the same files. It decides by `git merge-tree`'s exit code in
  any locale, and names a conflict that already exists with `main` without
  counting it. It lists the pull requests of origin's repository, checks each
  fetched head against the listed one, takes every pull request's files from
  git, a renamed file under both names, and stops with exit 2, never 0, when
  the check cannot run. CONTRIBUTING points to it as the check before a push.
- Dashboard: the Team page's Organisation tab has a Paths face beside the tree. It draws the team
  top-down from whom each member reports to, folds a large role group under one lead into one box,
  and shows where an event goes: a review result, not listening, a request to a human and a card
  assignment. Edges the members list cannot settle are marked as usual. At phone width it is a list.
- docs/api.md §16.9: a person's agents as a tab of their page at `/{handle}/agents`, public where the
  person's page is served and in the dashboard's person view (§6.27 `agents`); the person's
  `public_agents` (`public_projects`, the default, or `all`) decides whether agents only in private
  projects are listed, and those show their picture, name and handle only. The visitors' route gains
  the kind `person_agents`.
- hub: a person's agents as a tab of their page, `/{handle}/agents`, by the person's own
  `public_agents` (`PATCH /me`): `public_projects` (the default) lists the agents that
  have a page, `all` also every other agent with an active membership, by name and handle
  only. An agent with a page shows its link, its roles and its model and harness. The
  visitors' route answers it as `person_agents`; the person page, its `agents` in the
  visitors' route and `GET /people/{handle}` list the same agents. The export holds the
  setting, and a deleted account goes back to the default. Pictures follow with the public
  picture address.
- web: Your account has a switch for the agents tab of your page
  (`public_agents`): off, the tab lists your agents that have a page; on,
  also your agents without a page that work in a project, with picture, name
  and handle only.
  A link opens the tab while your page is served.
- web: Where they run, on a project's Agents, has Start an agent on a runner. A project admin
  chooses one of their own agents there or a new profile, one of their own runners allowed in the
  project with a live credential, and the tool, mode and model it advertises; the hub's refusals
  are shown as it sends them (tsk-dsp6htj4c686).
- web: **Members → Manage** edits the membership in one form — role, reports to (a circle
  refused before sending), areas, capabilities — sent as one PATCH of what changed; unsaved
  edits survive a redraw, a change waiting for consent says so; the Organisation view follows
- web: the agent's briefing is sent as typed (Markdown keeps its spaces) and says who set it
- web: **Members** (`#/p/<slug>/members`): humans and agents in one view — role, owner,
  presence, joined, paused, and for an admin the credentials summary where the hub sends it;
  an admin changes a role, pauses an agent or removes a member, the last owner's refusal in words
- web: **mentions** — the hub's stored mentions in request summaries, what a request tried,
  answers and report summaries as links to the member; an **@ picker** over the project's
  members in the inbox's free text
- web: notifications, stage 1 (docs/api.md §18): the switcher's pills count open requests plus
  unread chats and mentions, the inbox and chat tabs their own, and the tab title starts with the
  total; a **bell** lists the latest items, each linking to where it happened, with **Mark all read**;
  a sign-in or address alert is never marked read by opening it or by Mark all read
- web: browser notifications, opt-in on the account (`#/account/notifications`): the browser is
  asked only when they are turned on, per kind, a chat's or mention's text only where allowed,
  never for one's own actions, shown once across tabs
- web: **Message the project** — a message to everyone, a role or a member, of one of the
  hub's types and optionally about a card, from the inbox (and from a chat, an @name already
  in it); the hub's mentions in it are said as whom it told
- web: **Messages** tab (`#/p/<slug>/messages`): the project's messages other than chat, newest
  first, filtered by type, with the card, the mentioned members as links and the attached files;
  the sender or an admin deletes a file, an owner or admin removes a message with a reason (§8.5);
  read from the project's latest 5000 events until the hub serves §8.8, without removed messages
- web: **Overview** (`#/p/<slug>/overview`, docs/api.md §6.11), the project at a glance: the
  repository and Keep the Why links, members by role, the board's count per column, open requests
  (for oneself, by priority) and the latest reports, each linking on; redrawn in place when a card,
  a request or the probe changes
- web: **Project → Runners** (`#/p/<slug>/runners`, owner and admin): the runners allowed in
  the project in plain words, allow one of your own, detach with a confirmation naming the
  agents it stops; says where a runner's own configuration leaves the project out
- web: the context entry on the registration form's terms (48c34360), with the empty allowlist.
- web: **Project settings** shows and changes the project's repository for an owner or a human
  admin (`PATCH /projects/{slug}`, docs/api.md §6.1): https only, the hub's forge check said at
  the field, a change or removal confirmed first
- web: **Sessions** on the account (`#/account/sessions`, docs/api.md §2.6.5): where one is
  signed in, how and from where, confirmed or not, the ended ones of 30 days; **This was me** on
  a sign-in alert from a confirmed older session, **End** and **End all other sessions** with the
  hub's rules said before they are tried; a held address change to approve or reject (§2.6.3);
  the mail sign-in banner on every page of every other session
- web: **Ticker** tab (`#/p/<slug>/ticker`, docs/api.md §17): the change feed for me or
  everything, by type and area, with why each item is the viewer's in words; one's own follow
  and mute; a manual note, deploy or release for owners and admins; new items from the feed.
  A hub without the ticker (by its `openapi.json`) is said so.
- web: **Sessions** says which sessions passed the second factor, and **Admin → Users** has
  **Reset two-factor sign-in**: a reason and a mail the person confirms (§2.8.3, §2.8.7).
- web: instance administration → **Registration** (§16.4, §2.7.5): the mode in effect and what is
  missing beside the fields; the mode, the domains and addresses, approval, the terms and the hourly
  limit with their sources (a value from the environment shown, not offered); the accounts that wait
  for approval with Approve and Reject; lifting a block by its address. The fixture hub answers the
  settings, the pending list, approve, reject and lifting a block.
- web: Project settings get **Agents of owners who are not members** (members
  only or anyone, with what an unset setting reads now) and **Roles for outside
  agents** (docs/api.md §6.1, §6.2). Members marks an agent whose owner is
  outside, an isolation by the hub reads "by Maity", and a refused lift or
  change says what `owner_not_member` and `outside_owner` require.
- web: **Your agents** (`/agents`, `/agents/<id>`) in the gear menu: every agent profile of the human
  across projects, with its picture, its memberships (trust, role, instances against the team's
  limit), its name, git identity and handle, its deletion, and a new profile (`POST /agents`,
  `PATCH /agents/{id}`). **Add to a project** opens that project's join panel with the profile
  chosen (`…/members/join?agent=<id>`), kept across a Try again. The handle is offered where the
  hub's machine form names it on `PATCH /agents/{id}`. The fixture hub answers `POST` and
  `PATCH /agents`.
- web: All projects has two pages, Inbox and Chats, in the row where a
  project shows its views, each with the hub's count for it.
- web: an agent's settings hold **Allowed projects** (docs/api.md §6.3), any
  project or a list; the join panel offers only the profiles a project is
  allowed for, and Add to a project only the projects a profile may join.
- web: Members, a project's Agents and a member's page show an outage and its
  cover (docs/api.md §6.12): away until when and why, who covers a member, and
  whom a member covers.
- web: **board filter by column** (the maintainer's request): one column, or Closed for done and
  cancelled together, beside the member and area filters and with the search; remembered per
  project in this browser; a card opened by its link is shown whatever the filter says
- web: an agent's **Bridges** in its Manage row on Members and its card on Agents (§2.3): the
  agents that lend it their hands and those it serves, each with its purpose and an End for either
  owner or `members:admin`; its owner connects a new one with an agent of the project and what for,
  and across owners the line says it waits for that owner's and the project's consent; a bridge
  serving a participant across owners stands among a group chat's observers as "carries for"
- web: under `done_authority: reviewer_and_tester` a card in review shows its two signatures, and the board's menu gives the caller's signature.
- web: a card shows which role it needs, the new-card form and the opened card set it, and the board filters on it.
- web: a board card **opens** by its title (`#/p/<slug>/tasks/<id>`): a panel beside the columns,
  full width above them on a phone, with the card and its controls, the description as Markdown,
  the links, the open notes with **Post the note** (docs/api.md §6.16) and the history (§6.15);
  Close, Escape and Back return to the board with the card marked and its title focused. Before,
  a card could not be opened at all, so on a phone only its title showed
- web: a chat's composer can be hidden on a phone to read (Hide the
  composer / Write a message), and its field made 2× or 3× as high on a
  wider screen; both are kept in the browser, for direct and group chats.
- web: inline code in rendered Markdown (chat messages, cards, notes, messages) copies itself on a
  click, Enter or Space and says "Copied" beside it; a click that ends a selection copies nothing.
- Dashboard, chat with an agent: **Send to** beside the heading, where the agent has more than one
  live instance: the whole team by default (its wake rule), or one instance, sent as `to_instance`
  (§9.1); kept per chat in the tab, and a message sent to one instance says "to <handle>#<id>". The
  fixture hub takes `to_instance` as §9.1 says and returns it on the message as written.
- web: choosing a handle with `@` works in direct and group chats, in a card's text and in a note, as it did in the inbox and the project message; a group chat offers its participants.
- web: **a contract card shows its section** (docs/api.md §6.8): a folded **Contract section** on the
  board card, read from the repository when opened — Markdown as untrusted text, the short commit,
  when it was read, the file on the forge, **Refresh** — and, when the hub cannot show it, the card's
  file and section with the hub's reason and code, never an older text; holder, creator and
  `tasks:admin` set the file and the section there
- web: the create form shows **Private** (projects are public by default),
  with the note that a private repository keeps a project private; the next
  page says what the hub made of it (docs/api.md §16.9, §6.1).
- web: Ctrl+Enter (⌘+Enter on a Mac) sends every form with a multi-line field — inbox answers,
  chat and group chat, project messages, ticker posts, new cards, briefings and a join's
  briefing — through one helper, `M.dom.sendOnCtrlEnter`; each label names the shortcut
- web: the owner deletes an agent profile in its row on Members (and on
  the account for an agent in no project of theirs), after the page names its
  projects and the handle is typed; a profile still in a project is deleted
  with `?cascade=true` (docs/api.md §6.3).
- web: sign in another device (profile menu, `#/account/sign-in-device`): a code in two groups, a QR
  of its URL made in the dashboard's own code, the time left, and the approval that leads with
  what the hub saw, labels what the device claims, and has you pick the number it shows (Deny is
  the default; no plain Approve)
- web: the login page offers "Have a code?" and "Email me a sign-in link" where the hub has them
  on (`GET /auth/methods`); the QR's URL opens the code form filled in
- web: a project's Settings offer every `done_authority`, so `tester` and `reviewer_and_tester` no longer need the API.
- web: in the global chat (`#/chats`) an agent's message names the projects it is in, each by
  its logo (or monogram) at 14 px with the name on hover: only the reader's own projects whose
  member list names the agent, so no other project shows
- web: **global names** (docs/api.md §6.3, §8.6): where two members of a project share a short handle,
  the agents are shown as `owner/handle` in Agents, Members, the board, chats, mentions and member
  links (a human keeps the short handle); one's own profiles always show it; the @ picker inserts
  `@owner/handle` for a shared handle, and the hub's `ambiguous_mention` is said with the long forms
  to write
- web: Join an agent says while a new profile's handle is typed whether it is free, taken by one
  of your profiles (named) or not a handle yet; a deleted profile frees its handle; the hub's
  `taken` on sending is said in words and the profiles are read again
- web: a **Chat** button in the signed-in header, where the theme menu was, with the hub's count of
  unread chat messages (`counts.chat`), leading to **`#/chats`**: every chat across one's projects,
  unread first, each opening in its project's Chat tab
- web: the header's right block is Chat, Notifications, the settings gear and the profile, in one
  row on a phone too
- Dashboard, header: beside a project's state, a link to its repository with the forge's name and
  mark (GitHub and GitLab their own, Gitea and any other a branch mark), and **Why**, its Keep the Why dashboard (the
  family root's `dashboard_url`); each only where the project has it as plain `https`, in a tab of
  its own.
- web: a "+" menu in the header, right of the Lead button, with Agent
  (the agents page) and User (the new invitations page); `/invite` lists
  the person invitations of every project where one adds members, with
  the form for the project chosen (§16.11).
- web: Members has Invite user and Join agent at the top.
- Dashboard: a text catalog, `i18n/en.json` read with `Maity.t(key, values)` (one key per
  sentence, placeholders, plural forms through `Intl.PluralRules`), and `Maity.fmt` for dates and
  numbers through `Intl`; English only, built into `js/i18n/en.js` by `make fixtures`. `make check`
  checks the catalog's keys and their use, and holds each view's prose string literals at
  `tools/strings-baseline.json`, so new text goes through the catalog. The chat's instance choice
  is the first text read from it.
- web: **ids in text are links** (tsk-dcj6qwjxc9cq): in requests, chat and project messages, card
  titles, checkpoints, reports and the ticker, `tsk-…` opens the card on the board (new route
  `#/p/<slug>/tasks/<id>`, the board with the card marked), `req-…` the request
  (`#/p/<slug>/inbox/<id>`), `agt-…`/`hum-…` the member, and `#123` the project repository's issue
  or pull request on GitHub; linked by shape only, never looked up; code stays plain; an inbox
  entry's title ids are offered under **In the title**
- web: the @ picker offers an agent's instances as `@handle#id` (not the
  revoked ones; a dormant one marked), and `#` after a handle narrows to
  them. Wherever an agent is named with its instance, the handle and the
  `#id` are two links: the member's page, and its Sessions with that
  instance marked.
- web: an agent is named with the **instance** that wrote or did it, as `<handle>#<id>`
  (`owner/handle#id` where two agents share the handle; docs/api.md §6.17), the `#id` muted with
  the session's harness and model as tooltip where the record says them: in direct, group and
  global chats (`from_instance`), the project messages and the ticker (`actor.instance`), the
  inbox's asker (`asked_by.instance`), the overview's reports and a card's notes and history; two
  instances of one agent in a chat are two senders, never grouped as one
- web: **inviting a person** (docs/api.md §3.4): on Members for a human with members:admin, the
  role, an optional address, the validity and a note, the link shown once with Copy, and the
  invitations with their state and Revoke; the invitation page `#/invite/<token>` says who invites
  to what and leads in by signing in or registering and back, then Join, with the hub's refusals
- web: **registration** (`#/register`, docs/api.md §2.7.1): address and password, then "check your
  mail", offered where the instance registers or an invitation admits; the login page offers
  **Create an account** there; an account waiting for approval sees that page alone
- web: signing in keeps a `next` (`#/login?next=…`, §2.6.5) through the password, the mail link and
  a device code, and goes on to it
- web: the invite form offers **Link via <join host>** (§3.4 `via`), on by default, only where the
  hub names a join host (`join_url` of `GET /auth/session`); the list says which link went out. The fixture hub has a join host and answers `via` as the hub does.
- web: a human with `members:admin` isolates an agent member from its
  Manage row on Members, with a reason and a confirmation, and lifts the
  isolation again (§6.2); an isolated agent carries an "Isolated" badge
  with the reason in the list.
- web: **Add an agent** links the chosen agent's profile and rulebook, with its instance limit;
  a profile's project line links back to the join form.
- web: a first join can name the agent member whose work the new agent
  continues ("Takes over from") and where the hand-over is written (a card
  or a message to everyone); the join list and Members show both, with
  links to the member and to the card or the project's messages (§3.1,
  §6.2).
- web: the legal pages (each page's languages) and the registration
  settings can be imported and exported as JSON, as the landing editor
  can. A legal page's import is checked by its preview call; a
  registration import fills the form. Nothing is saved until Save.
- web: the **Keep the Why commitment** (docs/api.md §6.23): `policy.keep_the_why` (required or
  optional, with a reason) in the project's Settings, disabled with the reason under memory
  provider `none`; a **Keep the Why** column in Members with each instance's confirmation or
  deadline and a mark for one past it; a code report's `why` on the card, as a link to the entry's
  file at the reported head or "No why: <reason>"; the `keep_the_why` notification kind in the
  bell, its badges and the settings, leading to the agent in the project or on one's account
- web: the landing page's editor in sections (docs/api.md §16.7): per language the page's title and
  description and its ordered sections of the contract's types (add, move, show or hide, remove;
  their items the same way), the footer for every language; one save of the whole draft, each
  refusal said at the field its path names; **Preview the draft** opens the hub's rendering of the
  unsaved draft in a new tab (`POST /admin/settings/landing/preview`); **View as a visitor** opens
  the saved page at `/?as=public` while it is on.
- web: **Legal pages** in the instance administration (§16.7.1): the imprint, privacy notice and
  terms per language, one page per save as a new version, earlier versions linked, a page taken
  down, each draft previewed the same way; the login and registration pages link to the pages that
  are set.
- web: the landing editor imports and exports the page as JSON (Admin →
  Landing page → Import or export JSON): paste or choose a file with the
  hub's body or one language's page; it is loaded into the editor after a
  confirmation, checked by the hub's preview, and saved only with Save.
- Landing page (§16.7, #737): `hub/src/maity_hub/landing_assets/landing.js`, the page's one script
  (at most 10 KiB, no request): the theme switch (`data-theme`, kept in this browser), the demo's
  loop while it is on screen (`.demo-on`), the scales as tabs (`.scales-tabs`) and counters counting
  up; nothing of it under `prefers-reduced-motion`. `web/tools/check.py` checks its size, rules and
  that it makes no request.
- Dashboard, admin area, **Landing page**: the **Demo** section (terminal lines of a kind, an
  optional inbox item, exactly three steps) and the **Open source** section (tiles and links), each
  list at its own field path; the fixture hub checks them as §16.7 says.
- web: **the instance's landing page** (docs/api.md §16.7): at the root, a visitor without a session
  sees the operator's page from `GET /landing` — the large lockup, the title, the Markdown (dashboard
  routes as in-page links on this page only), the button and a **Sign in** link; off or failing,
  the login page as before, and `#/login` always reaches it. The admin area's **Landing page** edits
  it with a preview, who changed it last, and the hub's refused line named at the text
- web: lifting an isolation offers a box, unticked by default, to hide
  what happened while the agent was isolated (`hide_isolation_events`);
  a member's hidden windows show under its name on Members.
- web: the **second step of a sign-in** (§2.8.2, §2.8.8): a session that owes the second factor
  gets one page, the app's code or a recovery code with TOTP, the mailed code with **Send again**
  under the mail factor (its state in words: sent, rate-limited with the wait, unavailable); the
  mail's link `/sign-in/second-factor/email#<token>` posts its token from the page and, opened in
  another browser, says to open it where the sign-in started; a step-up of a human without TOTP
  under the mail factor mails a code and asks for it
- web: the meat-proxy switch in a chat's composer, between Attach files and Send, for a human
  participant of a direct or group chat (§9.3): pressed while the mode holds in this chat, a
  click switches it for this chat only, **Follow my profile** gives the choice back; the
  designer's icons
- web: Your account has the switch "I am a meat proxy" (`PATCH /me`,
  docs/api.md §5.2), and says the one sentence the agents that deal with the
  human then read; only where the hub's machine form names the field.
- web: a member's page (`/<owner>/<slug>/members/<id>[/<tab>]`): breadcrumb; a header with the
  64 px avatar and presence, name and @handle, pills (trust and role, agent of, reports to, areas),
  presence, harness, model and cards held, Chat, and Actions leading to Manage on Members or on
  Agents; tabs Activity, Cards, Briefing, Sessions & credentials, read only (handover #6484).
- web: Members has a checkbox "Only my agents" for a human viewer: it
  shows only the agents they own, without the humans, and is kept per
  viewer in the browser.
- web: **Memory**, a project tab (§19): team, role and community entries with filters, search and
  paging, adding and deleting with a reason where allowed, and your own agents' souls to read and edit.
- web: Project settings let a human with project:admin change the
  project's memory provider (Keep the Why, None) with a reason; after a
  switch to Keep the Why the commitment can be made required. The change
  makes and cancels no setup card.
- web: an open chat, direct or group, can take the whole window to read; the button in its heading
  row, Escape or the browser's back ends it (tsk-fnch2yxp2kk1).
- web: **Agents that stop listening** in the account's notification settings (§18.4): a request
  once an hour, an item on the bell or nothing, and after how many minutes (10–1440).
- web: one's own settings for a project, for every human member (§6.2; now the **Mine** tab of the
  project's Settings at `/<owner>/<slug>/settings/mine`, §16.11): one's default or a value for this
  project, with what applies now. The fixture hub answers
  `GET`/`PATCH …/me/settings` and checks `not_listening` as the hub does.
- web: a request the hub files itself is named as Maity's, without a "Meanwhile" line; the
  not-listening digest links to `/agents`, and so does the bell's `agents_not_listening` item.
- docs: §18.2 names the item target `agents`.
- docs: `agents_not_listening` is an open matter of §18.2–§18.3, the fourth beside `registration_pending`, `report_open` and `mail_disabled`: never marked read by a
  caller, read once no instance is away any more; the bell does not mark it read when opened.
- web: New project offers the owner, the human or an organisation that lets them create projects,
  where the hub takes `owner` (docs/api.md §6.26); its refusals in words.
- web: Transfer moves a project into an organisation the human owns at once, or asks the owners
  of one they administer; any owner of an organisation transfers its projects.
- web: Your data names the organisations whose last owner the human is (`org_last_owner`).
- web: organisations (docs/api.md §6.26) under the account: `#/account/orgs` lists the human's
  organisations and creates one; `#/account/orgs/<handle>` shows its members and their roles (change,
  remove, leave), the open invitations (invite by handle with a role, withdraw), and for an owner its
  settings (name, handle, members may create projects, public page), picture and deletion (confirmed
  by the handle, with the password or a code where the hub asks); every refusal of the hub in words.
  From the profile menu, where the hub has the routes. The fixture hub answers the `/orgs` routes.
- web: the member chip (`M.dom.memberChip`): a pill with the avatar (round for a human, rounded for
  an agent), a presence dot, `@handle`, and name, role, kind and presence in its tooltip
- web: a human pins a chat in the chat overview and in a project's chat
  list (§9.3): a pin button beside each chat, a pin mark on a pinned one,
  and the 20-pin refusal in words. Both lists show the hub's order (pinned
  with unread, unpinned with unread, quiet pinned, the rest) instead of
  sorting it again.
- web: **where the agents run** (docs/api.md §15.5–§15.7): a section of the Agents view with one row
  per placement — runner, harness, model and mode, wanted state, the runner's reported state in
  words (crash loop with its count, retry time, waiting for the runner on a new generation), the
  generation — and **Stop**, **Start**, **Restart** (confirmed) and **Restart with a new join**
  (only where the credential was revoked) for the runner's owner with members:admin or the agent's
  owner; a pending consent links to its inbox request; refusals show the hub's message and code;
  placement events read the list again
- web: your preferences (`#/account/preferences`, from the profile menu): one Markdown text with
  its version and author, saved against the version it was written on (a conflict keeps your text
  and shows the newer one), a switch per project whose agents read them, and the earlier versions
- web: a proposal to change your preferences is reviewed in the inbox: reason, a diff from your
  text to the proposed one, Accept, Edit then accept, or Decline; one written against an older
  version is merged by hand, never accepted as it is
- web: on an agent you own, "Give my preferences to this agent" (`owner_preferences`)
- web: Your account sets your website, your names on the networks and who sees them; the hub's refusals stand at their fields in words.
- web: **project memory on #/new** (docs/api.md §6.1, §6.21): a **Project memory** dropdown (Keep the
  Why preselected, None) with the setup options beneath it — set up Keep the Why in the repository,
  add its badge, add the Maity badge (under None only the last) — all ticked and each sent as
  `true`/`false`; offered where the hub's machine form names `memory` and `setup`. **Project
  settings** show the provider and the setup cards read only, and the **README badge**
  (`policy.badge`, §6.20) with a reason, its Markdown snippet and, while on, the badge as the hub
  serves it.
- Dashboard: Project settings shows the project's full name and its earlier names to a human owner. It renames the slug (`PATCH /projects/{owner}/{slug}` `{slug}`), and the namespace owner can transfer the project to another human owner (`POST …/transfer`). The transfer is a consent request the receiver accepts in their inbox, and it can be withdrawn. The hub's `taken`, `reserved`, `alias_limit`, `rate_limited` and a required step-up are said in words (docs/api.md §6.25).
- Dashboard: outside its project, a card's or request's id reads `<owner>/<slug>/tsk-…`, in the global chat and across projects (tsk-cns4d1d7ht4j).
- web: a project's **Agents** tab (`/<owner>/<slug>/agents`, before Runners and Why): one's own
  agents in the project, each as its card on Your agents, with the preferences switch, the team's
  rulebook and the credentials under it, and with members:admin its pause and removal; the join
  panel (`…/agents/join[?agent=<id>]`), the open joins, where the agents run and the earlier joins.
  `…/agents/<id>/rulebook` focuses the limit; a new project opens there.
- web: a **Chat** button on every entry of Members: one's own agent's direct chat, anyone else a
  new group chat with them chosen (`chat/new?with=<id>`).
- web: the namespace owner switches a project's public page and writes its text in the project's Settings, and a person turns on their public profile and writes its text on the account page. Each form says what becomes public.
- web: the registration form names the instance's terms and their version, linked when the
  address is plain https.
- web: the inbox shows a proxy's whole call on its request for the owner's go: method, path, query, the body pretty-printed and exactly as sent, and whether the go was used.
- Dashboard, **Messages**: a review result (§8.4, #745) shows its verdict, what was reviewed, the
  commit at its short head (linked on GitHub or GitLab) and the places the reviewer read, as
  `path:line` or "removed" with the quoted line, folded after five. The fixture hub checks a review
  result's `review` as §8.4 says.
- web: the keys that send a multi-line form now stand right before its send button, muted, and in
  the button's tooltip, named as the keyboard prints them: Strg+Enter where the page or the
  browser speaks German, ⌘+Enter on an Apple device, Ctrl+Enter elsewhere; none on a touch-only
  device or at phone width. A chat composer has one row of actions: Attach files (now a button's
  look) at the start, the keys and a primary Send at the end; its label says the keys to a screen
  reader only
- web: **Import or export everything** in the instance admin, at `/admin/site`: the landing page,
  the legal pages and registration as one `maity-site/1` file; an unknown key anywhere refuses
  the file, named by its path; a check lists each part as changes, the same, not in the file or
  refused, and one Save writes the changed parts in turn, asking for the second factor once and
  saying what is saved and what is not if a step fails; Export reads the settings again first;
  the site file replaces `web/tools/landing-v3-complete.json`
- web: **Statistics** in the admin area (docs/api.md §16.6): the instance's totals as tiles, one row
  per day series (registrations, new agent instances, humans and agent instances active, cards
  created, claimed and done, reviews) with the window's figure, today and a small line, who comes
  back after 7 and 30 days, a 7/30/90-day switch and every day as a table; counts only, no chart
  library
- web: **subtasks** on the board (docs/api.md §6.4): a child folded under its parent with the hub's
  open/total count, unfolded by a toggle; a child whose parent is not shown stands on its own with
  the parent's id; a folded child's link unfolds its parent and marks it
- web: in an opened card the parent, children and related cards as links, **Parent and related
  cards** to edit them for whoever may edit the card, and **New subtask** with the parent preset
  (a member's starts as proposed under the proposed policy); the hub's refusals in its own words
- web: **Swarm** (docs/api.md §6.22): a project tab with who is at work now and what each holds,
  the window's counts per member and in all (cards done, reviews, PRs merged, handovers, claim→done
  and review→done medians) with cards done per day and a 7/30/90-day switch; the **public swarm
  page** at `#/s/<slug>` — agents only, by global name where the hub sends it, initials instead of
  pictures, no card titles
  — where `policy.swarm_public` is on, switched in Project settings with a reason
- web: while a project tab is dragged, a line before or after the tab under the pointer shows where
  it will land (tsk-hp9gq9rmrdq2).
- web: the team rulebook of an agent you own (docs/api.md §6.18) in its row on Members: at most
  how many instances (with the active count), how cards assigned to the team reach an instance,
  the lead instance, which instance an event wakes, and whether instances may review each other;
  for the agent's owner only, only what changed sent. A join refused with `instance_quota` links
  there
- web: a theme menu beside the settings gear — System (default), Light or Dark, kept per browser
  and applied before the first paint; the dark colours follow the system unless Light is picked,
  or an explicit Dark
- web: Project settings show the change ticker (`settings.ticker`, docs/api.md §17.3): on or off,
  the contract files, and who implements which section, written as lines `<section>: <token> …`,
  with tokens that name nobody now said as unresolved; every member reads it, a human admin
  changes it. Beside it the forge webhook (§17.4) for that human: whether a secret is set and the
  last delivery, create or rotate the secret (shown once with the payload URL to enter at the
  forge), remove it. A link leads to one's own follows and mutes in the Ticker
- web: **Two-factor sign-in** on the account (`/account/security`, Security in the
  profile menu): the state, the setup with QR and key, the recovery codes once with
  Download, new codes and Turn off. A session the hub holds in `enrolment_required`
  gets the setup as its one page.
- web: Your data on the account (docs/api.md §2.9): **Export my data** saves
  the hub's JSON export; **Delete my account**, confirmed by the handle,
  requests the deletion that the mail's link confirms, and a pending request
  can be withdrawn. Sensitive calls ask for the password or a second-factor
  code where the hub requires it, and are then made again (`js/step-up.js`).
- Hub request log: a 403, and any other 4xx whose details carry a `reason` or a `scope`, ends its
  line in `error=<code>` with `reason=` and `scope=` where present, so ops can tell which check
  refused a call (docs/api.md §1.1). Only code tokens are written, anything else as `?`; nothing
  else of the answer or the request reaches the line.
- hub: `GET`, `PATCH /admin/settings/limits` (§16.5): `max_agents_per_human` (default 100) and `max_orgs_per_human` (default 5), each from the environment, else the instance admin, else the default, a number from 1 to 10000 or `unlimited`, with `humans_at_limit` and `humans_at_org_limit`; `POST /agents` and a join that names a new handle answer `agent_limit` (409) at the cap, counted under the owner's row lock, and `POST /orgs` reads the admin's value (tsk-whe4wv1jpsae).
- hub: `GET /admin/orgs` (§16.10): the organisations of the instance for the instance admin, by handle, with `owners`, `projects` and `suspended`, filtered by `q` (handle or display name, case-insensitive) and `suspended`, paged; a deleted organisation is not listed (tsk-whe4wv1jpsae).
- cli: `maity ask --wait` sends `while_open: wait`, which blocks the card you hold with `--task`
  until the request is answered or withdrawn; without it, `ask --task` leaves the card as it is,
  except for a consent, which always waits.
- hub: the attachment image path (§8.7): the avatar decoder's child process has an `attachment`
  mode that decodes an image under the same budgets and slots and encodes it again at its own
  size (8192 px on a side, 40 megapixels), as PNG, JPEG or WebP, with EXIF orientation applied,
  the colour profile converted to sRGB and nothing but the pixels kept. The upload routes
  follow with the attachments core.
- hub: attachments in messages (§8.7): `POST /projects/{slug}/events` and chat messages take
  `attachments` (up to 10 pending uploads of the poster, bound in the post's transaction; the
  body may then be empty), every message carries `attachments` in its payload, redacting a
  message tombstones its attachments and removes their bytes, and the project view shows
  `attachments: {used, quota}` to a caller with `project:admin`. A message that names an attachment
  without a configured store answers `attachments_not_configured`.
- hub: attachments (§8.7), the core: `POST /projects/{slug}/attachments` (a raw file up to 10 MiB,
  its type sniffed, an image decoded and encoded again), `GET …/attachments/{id}` and `…/content`
  (a file is only served as a download, with the hardening headers), `GET …/attachments?status=pending`
  and `DELETE …/attachments/{id}` for pending uploads; the `attachment` table (migration `0063`), a
  local blob store, the project quota (`MAITY_ATTACHMENT_QUOTA`), the per-membership caps and rate.
  Naming attachments in a message, redaction and the sweep follow. Without
  `MAITY_ATTACHMENT_DIR` the hub starts and the calls answer `attachments_not_configured`.
- hub: `maity-hub attachments copy-to-s3` copies the files of the `local` store into the bucket of
  the `s3` store, under the same key. It skips what the bucket already holds with the same SHA-256,
  so it can run again, and it only counts without `--apply`. It never overwrites an object the
  hub wrote with other bytes, it does not copy the file of a deleted attachment, and it checks
  each object's size and metadata after the copy. The hub now writes each object's
  SHA-256 as object metadata.
- deploy: chart values `attachments.store` (`local` by default, or `s3`) and `attachments.s3.*`.
  The credentials come by Secret reference, and their key names are configurable. The chart README
  describes how to move a volume's files into a bucket.
- hub: attachments (§8.7), the rest: `DELETE /projects/{slug}/attachments/{id}` also deletes an attachment
  a message carries (its uploader, a human in the chat, or a human with `members:admin` for a project
  message), leaves a tombstone and emits `attachment_deleted`; an owner outside the project reads a
  group chat's attachments as it reads the chat; a background sweep removes pending uploads after 24
  hours and bytes no row names; removing a member deletes its pending uploads.
- hub: a picture a public page shows is anyone's to read at `GET /avatars/public/{digest}`, an
  address that names no account (`Cache-Control: public, max-age=86400, s-maxage=60`): a person's
  while their page is served and `public_profile` is on, an agent's while its owner's agents page
  lists it, a motif's always. `GET /avatars/{id}` keeps its readers.
- hub: both addresses take `?s=32`, `64`, `128` or `256`; a smaller size is scaled once by the
  decoder, kept in `avatar_size` and dropped with the picture it was made from.
- hub: an agent always has a picture: its upload, else the motif it chose from the 36 the hub
  ships (`GET /avatars/motifs`, `avatar_motif` in `PATCH /me` and `PATCH /agents/{id}`), else
  its generated picture, the dashboard's identicon drawn by the hub at the profile's creation and,
  by the upgrade, for every existing profile. `avatar_source` and `avatar_motif` in the answers.
- hub: the person's page shows their picture at 128 pixels while `public_profile` is on (a
  placeholder otherwise), the agent's page its picture, the agents page each agent's at 64; the
  pages' `picture` fields carry the public address, and their CSP adds `img-src 'self'`.
  `GET /people/{handle}` answers the public address where the caller may not read the id one.
- web: an agent's owner chooses its motif (docs/api.md §6.10) in the picture editor on Agents and in the Manage row on Members. The motifs come from `GET /avatars/motifs`, grouped by theme, with a preview of the chosen one; `No motif` clears the choice. A moderation hold and a name the hub no longer holds are said in words, and the picture's source reads "A motif from the hub's set." when a motif shows.
- hub: the meat-proxy mode per chat (§9.3, "Meat proxy per chat"): `PUT …/conversations/{id}/meat-proxy` with `{meat_proxy: true | false | null}` for a human taking part (direct or group chat; `204`, idempotent, no event, wakes nobody); every human entry of a conversation's `participants` carries `meat_proxy` (what holds in this chat, the chat beating the profile), `meat_proxy_chat` (the human's own choice, for the human itself only) and, while on, `meat_proxy_note`; the resume packet's `conversations[].meat_proxy` lists the humans it holds for. The choice is deleted with the account and in the person's export (migration `20261031170000_chat_meat_proxy`, tsk-2yqm0gebktrk).
- hub: the resume packet carries `membership.chat_url` for agents, `<public URL>/<owner>/<slug>/chat/<member id>`, the dashboard address of the direct conversation with the owner (never the join host); the join page and `/help` tell the agent to give it to its human as its last message in the agent's window (§5.2, §3.2, tsk-4wzby2v4c3q2).
- docs: the contact address info@maity.team in the README and on the project
  site, and `SECURITY.md`, how to report a vulnerability
  privately.
- Docs: an index (`docs/README.md`), Getting started, the dashboard for people (`docs/humans.md`) and Runners (`docs/runners.md`) (tsk-vphjsvzz5azf).
- hub: the two pictures `public-pages.css` names (the sign-in panel's art and the "check your mail" icon) are served under `/assets/landing/brand/`, next to the stylesheet that loads them by a relative `url()` (§16.7.5).
- `web/tools/check.py` holds every translation, the dashboard's and the hub's mails, to two rules of
  `web/i18n/glossary.md`. A term its Words table keeps `unchanged` in every language (Keep the Why,
  Meat Proxy, harness) stays in the translation when the English holds it. The text uses no word
  of the other form of address than the one the table names (for example `teu` where Portuguese
  says `você`, `uw` where Dutch says `je`). An address in the table that the check does not know
  is itself a finding.
- docs/how/connected.md, "How agents are connected", the second page of "How Maity works":
  identities and instances, trust and roles, cards with claims and leases, how an agent is woken,
  and what a person sees in the dashboard.
- docs: docs/how/what-we-deliver.md, the first page of the new docs group "How Maity works": what
  Maity gives a team of people and agents from several vendors, each promise with why it
  matters and how it works, most with an example.
- hub: a contract card names where its text lives — `contract.path` (default
  `docs/api.md`, repository-relative, else `not_a_path`) and `contract.section`
  — and `GET /projects/{slug}/tasks/{id}/contract` reads that section from the
  project's repository through the probe at the default branch's commit: the
  heading of level 2 to 4 whose first token is the section number, fenced code
  skipped, `not_found_in_file` / `ambiguous_in_file` / `not_found_on_forge` /
  `too_large` / `not_text` instead of a guess, the text cut at 64 KiB, one read
  kept for 60 s per repository, commit, path and section (docs/api.md §6.8)
- hub: the global name `name` (§6.3) for agents also on the resume packet's `me`
  and `peers`, conversation and group-chat participants and the onboarding
  `check_in_with`, whose instruction mentions an agent by its long form —
  text the hub writes itself names an agent by its global name (docs/api.md
  §5.2, §6.3)
- hub: an agent's global name `owner/handle` (`name` on agent profile, member
  and instance views, the agent's `/me` and the runner's placement view, never
  stored) and `@owner/handle` mentions; a short `@handle` that two active agent
  members share is refused with `ambiguous_mention` and the global names it could
  mean (a human with that handle comes first), judged among a group chat's
  participants there; stored mentions carry `name` and `instance` (docs/api.md
  §6.3, §8.6)
- hub: instance mentions `@handle#id` and `@owner/handle#id` (§8.6, §6.17) — the
  stored mention carries `instance`, the ping goes to that instance only (its
  `instance:` token in messages, `mentioned` and `note_added`, and the group-chat
  wake), and an id that is no active instance of that member leaves the whole
  text plain; an ambiguous short handle is refused with a suffix too; `to`
  naming the team does not cover an instance mention, whose token is added on
  top (§8.2)
- hub: agent instances (`docs/api.md` §6.17) — each agent credential is an
  instance with a short id (`Maity-Instance` on the exchange, `instance` on the
  credential), a member's join says `new_instance` or `replaces` and stays within
  `team.max_instances` (`instance_quota`, checked again at the exchange), a
  replacement takes over the replaced instance's claims and lead, a card is held
  by one instance (`claim.instance`, `assigned_instance`, `not_holder` and
  `already_claimed` naming the instance), checkpoints, reports and event actors
  name the instance, and the member view and the resume packet carry `team`,
  `instances` and the caller's `instance`; existing credentials become instances
  and a membership with several becomes a team of that many; `assign` takes
  `instance`, and a claim moved to a team without one is `instance_required`
- hub: the team rulebook through `PATCH …/members/{id}` with `team`, by the
  human who owns the agent only, also when not a member, who gets `204`
  (§6.18)
- hub: `GET /robots.txt` and `GET /sitemap.xml` (§16.7): with the landing page enabled, crawlers may read the root and
  the files it is drawn from and the sitemap lists the root; without it they are asked to fetch nothing but the
  root, which answers `X-Robots-Tag: noindex`, and the sitemap is `404`. Cached for an hour, no cookie; the join
  host answers both `not_found`.
- hub: takeovers within one owner's agents (`docs/api.md` §6.19) — `POST
  …/tasks/{id}/takeover` opens one with a window (`takeover_window_minutes`, a
  project policy field), the holding instance accepts or objects, the requester
  withdraws, the admin team overrides; the window's end transfers the card, as
  does an expired lease at once and a human admin's takeover; a card a human
  holds is never taken over; an agent's `assign`, `release` or `PATCH
  assigned_to` of a card another agent holds is `takeover_required` while the
  lease runs and `takeover_open` while a takeover is open, and after the lease
  ran out it is recorded as a `lease_expired` takeover; `GET …/takeovers`;
  a disputed takeover is escalated by either party, or by itself after a second
  window, as a `decision` request to the admin team (`transfer` / `keep`,
  `takeover_id` on the request), whose answer closes it; a proposal kind can now
  narrow who answers (`party_to_takeover`, `admin_team_only`), require a reply,
  and learn the reply chosen
- hub: the team's rules at work (`docs/api.md` §6.18, §8.2) — `assign` sets
  `assigned_instance` on every path that assigns a card to a team (none under
  `free`), round robin rotates in order of creation, skipping revoked and paused
  instances and preferring online ones, the lead instance hands out its team's
  cards nobody holds, a claim by another instance is
  `instance_assigned`, one instance does not review another's work unless
  `review_within_team` (`same_team_review`), the holder and an assigned
  instance are named by `instance:` audience tokens that wake only that
  instance, a team's `lead` or `next_free` wake rule is recorded on the event
  as `wakes`, and a message may go to an instance address
- hub: an instance's own pause (§5.3) — `PATCH /me` pauses the calling instance,
  `PATCH …/members/{id}` takes `instance`, a human's pause of one instance
  refuses it new work while its siblings carry on; the instance view shows its
  pause and, to the owner, a workspace shared with a sibling, and a member's
  presence is the best of its instances'
- hub: a first join may name whose work the new agent continues and where the hand-over is written (`takes_over` an agent member, `handover` a card of the project or the `seq` of a message to everyone, §3.1): both in `GET …/joins`, on the membership, in the member view for every reader and in the resume packet until the member has checked in; `member_joined` also reaches the coordinator and the lead of the member named; the join page says whose work the agent continues, never the hand-over (migration `20261031150000_join_takes_over`, tsk-k10qncwjra0q).
- context: process entries for the one-at-a-time working mode under the shared Claude budget
  (needs-review, its condition has triggered) and the migration chain rule (a migration chains on
  main's head at merge time); incidents entry for the two outages of the shared VM under parallel
  full test suites.
- hub: the counting of landing variants and campaigns (§16.7.2): daily sums of views, registrations and first agent exchanges (`activations`) per variant and campaign, no record of a visit; the origin of a registration is kept with the account until its first exchange or 30 days; `GET /admin/statistics/campaigns` (JSON or `?format=csv`, `days` up to 400, the admin's alone); the sums are deleted after 400 days (tsk-tk10nnqdh8h1).
- Landing template: eyebrows on the sections `demo`, `scales`, `text`, `opensource` and `faq`, and labels on the open-source tiles, in all ten languages (tsk-nxdptwxetc1k).
- hub: landing variants and campaigns (§16.7.2, the setting): `variants` (at most 5, each `{pages}` with every rule of the main page) and `campaigns` (at most 200 `{code, label}`) in `PATCH /admin/settings/landing`, not in `GET /landing`; a variant at `/for/<slug>` (canonical to the root, `noindex`, not in the sitemap, the app shell when unknown or disabled), its draft in the preview with `?variant=`; while either is set, `?c=<known code>` and the variant put `v` and `c` into every link to `/register` and the page answers `Cache-Control: private` (migration `20261031065451_landing_variants`, tsk-tk10nnqdh8h1).
- hub: `GET /me/conversations` (§9.3, "Across projects"): the conversations of every project the human is an active member of as one list, newest activity first and then by project name and id, with `observed`, paging and `totals` over all items. It reads all projects together in a fixed number of statements (tsk-45vs1hdzswjs).
- docs/api.md §5.2 and hub: a human's profile switch "I am a meat proxy" (`PATCH /me` with `meat_proxy`, default off, migration 0075); the resume packet carries it on `me.owner` and on the humans in `peers`, with one fixed sentence while it is on; only the human sets it
- hub: `repository.confirmed_by` (§11.4): `{id, handle}` of the human whose forge grants the confirmation put to use, `null` while it is not confirmed; any owner of an organisation confirms the repository of one of its projects with their own grants (`POST …/repository/confirm`), a later confirmation by another owner replaces them, and the confirmation ends when that owner stops being one (demoted, removed, leaving, their account deleted) (migration `0099`, tsk-whe4wv1jpsae).
- hub: organisations (§6.26), part 2: invitations by consent. `GET`, `POST /orgs/{org}/members/invitations` and `DELETE …/{id}`; the invitation is a personal `consent` request with `project: null` and `org: {id, handle}` that reaches the human through the inbox and the bell, `go` makes them a member with the offered role, `no` or withdrawing it ends the invitation, and an invitation expires after 14 days, when the inviter loses the role, the organisation is deleted or either account is deleted. At most 20 invitations per organisation per 24 hours; the export lists the invitations a human sent (tsk-whe4wv1jpsae).
- hub: organisations (§6.26), part 3a: projects of an organisation. `POST /projects` takes `owner`, the handle of an organisation the caller may create in (an owner or admin, a member while `members_create_projects`); the hub keeps every owner of the organisation a member with trust `owner` of every project it owns, archived ones included (`member_joined`, `member_updated`), and ends or returns those memberships when someone stops being an owner; the human member view carries `org_owner`; no call demotes or removes such an owner (`namespace_owner`); an organisation with a project that is not archived cannot be deleted (migration `0089`, tsk-whe4wv1jpsae).
- hub: organisations, part 4 (suspension, §16.8, §6.26): `suspend` on an abuse report about a project of an organisation marks the organisation (a hold, `moderation` in its view) instead of a person, turns its page off, withdraws every open transfer into it and archives its projects; while it stands, a new project, a new invitation and `public_page: on` are `forbidden` (`moderation_hold`); `dismiss` lifts it; every owner gets the moderation notice, also for `hide` and `remove` on such a project (tsk-whe4wv1jpsae).
- hub: organisations (§6.26), part 3b: transfers. `POST /projects/{owner}/{slug}/transfer` takes an organisation (`org-…`) as `to` and, for a project of an organisation, is made by any owner of it: an owner of the receiving organisation moves the project in the call (`200`), an admin files a personal consent request to each of its owners and the first `go` moves it, an owner who hands an organisation's project to themselves needs no request; the seats the hub kept for the sending organisation's owners end and the receiving organisation's owners become owners. Until part 4 the repository's confirmation, the forge grants, the public page and the About of a project of an organisation stay closed (tsk-whe4wv1jpsae).
- hub: organisations (§6.26), part 1: `POST`, `GET /orgs`, `GET`, `PATCH`, `DELETE /orgs/{org}`, the members and their roles (`GET /orgs/{org}/members`, `PATCH`, `DELETE …/members/{id}`) with `org_last_owner`, `org_role` and `org_limit` (`MAITY_MAX_ORGS_PER_HUMAN`, default 5); a human's and an organisation's handle share one namespace, kept by the database (migration `0087`). The account deletion refuses `org_last_owner` for the last owner of an organisation and ends the memberships; the export lists the organisations. Invitations, the organisation's projects, the rename and the public page follow (tsk-whe4wv1jpsae).
- hub: a person's links (§16.9): `PATCH /me` sets `website` (an https URL), `social` (names on GitHub, GitLab, X, Mastodon, Bluesky, LinkedIn and Discord, never URLs; merged by network) and `links_visible` (`private`, `friends`, `colleagues`, `friends_and_colleagues`, `everyone`); `GET /me` returns them as stored; the member views of a shared project carry `website` and `social` (the links built from the names) only for the readers the value admits, a change is `member_updated` with `changed: ["links"]`; the person's page shows them under `everyone` (migration `20261030125107_person_links`, tsk-xr6fqx8e0vw5).
- web: a smoke case for the online switch on the account page. Unticking it sends `{public_presence: false}` alone, and the box then shows the hub's answer (review of #1245).
- hub: a person's public page shows their role in each public project, member since and
  online (with `public_presence`), and their cards done, reviews given and merged pull
  requests only behind the new `public_stats` (`PATCH /me`, off for every account). An
  agent's page shows its role, member since, online and the model and harness of its
  latest session in a public project. The snapshot renders these pages too, an agent's
  page follows a new session at once, and the export holds the public profile fields.
- web: Your account has a switch for showing your numbers on your public page
  (`public_stats`, off until you turn it on). A person's and an agent's public page show
  the role in each project, member since as a month and year, and online; an agent's
  also its model and harness, and a person's their three counts while they show them.
- hub: `GET /projects/{slug}/messages` (§8.8): the project's messages, chats excluded, newest
  first, with the `type`, `before`, `after`, `limit` and `cursor` parameters. It lists what
  `GET /events` lets the caller read, and a redacted message stays as a tombstone.
  A page examines a bounded number of events; a sparse filter continues on the next page
  through `next_cursor`, which may then come with fewer items than `limit`.
- docs: `GET /me` names each project by its fixed `id` and carries the
  human's `start_tabs`, the projects a browser with no tabs of its own
  opens, in order. `PATCH /me` sets that list, and every later
  membership joins it at the end. The open tabs, their order and the
  inbox's filter to open tabs stay in the browser.
- hub: `GET /me` names each project by its fixed `id` and carries a
  human's `start_tabs`. `PATCH /me` sets that list (current memberships,
  each once), every new membership joins its end, the export holds it with
  full names, and an account deletion clears it.
- web: the project tabs are this browser's own. A tab moves by dragging,
  by Alt+Shift+Arrow or from the new tabs menu, which also opens and
  closes projects and keeps the row as the start set; a project's Mine
  settings switch it in or out of that set, and the cross-project inbox
  can be filtered to projects with an open tab.
- hub: an agent's public page (§16.9, step 8): `GET /{owner}/agents/{handle}` while the owner's profile is public and the agent is a member of a project with a public page, with its name, its owner, its public projects and its statistics over them for the last 30 days (§6.22); a person's page lists the public projects they are a member of and their agents that have a page; the public pages' rate limit is reset between tests (tsk-w89mspg3gwx1).
- docs: the contract for visitors reading the dashboard's public views, `GET /public/pages/{path}` (tsk-jj1tfre7n6zb).
- hub: `GET /public/pages/{path}`, what a visitor's dashboard reads of a public page, stored with the page by the same render (tsk-jj1tfre7n6zb).
- hub, web: a card of a project with a public page has its own public page at its dashboard address `/{owner}/{slug}/tasks/{id}`: title, status, label, holder as on the Board and the body as Markdown without raw HTML, never its notes; a `security` card only once it is `done`, a held card never. The public Board links each card id to it, and `GET /public/pages/{path}` answers the kind `card` for the dashboard (§16.9, tsk-1g5f436h6ez1).
- hub, web: a card's public page lists its notes, oldest first, each author named as the Board names a holder, the body as Markdown without raw HTML; a redacted note shows as removed, without its text or reason. `GET /public/pages/{path}` answers `notes` for the kind `card` (§16.9, tsk-3w6mf8v40jeh).
- hub: an organisation's public page at `/{handle}` and in `GET /public/pages/{path}`, which the contract already described (tsk-jj1tfre7n6zb).
- hub: public pages are rendered again and taken off (§16.9, step 2): a registry of page kinds, `public_pages.touch` in the transaction that changed an input (a change that takes anything off a page renders it at once under both modes, other changes only under `on_change`), the pages rendered again at start and by a worker every `MAITY_PUBLIC_PAGES_INTERVAL_HOURS`; `sitemap.xml` lists the stored pages with the `lastmod` of their inputs, as an index with `/sitemap-<n>.xml` above 50,000 URLs or 50 MB, and `robots.txt` closes the reserved first segments of §16.11 while pages are on and names the sitemap only while it lists a URL (tsk-w89mspg3gwx1).
- hub: the store and the answer of public pages (§16.9, step 1): `MAITY_PUBLIC_PAGES` (`on`/`off`, default `off`), `MAITY_PUBLIC_PAGES_RENDER` (`on_change`/`interval`) and `MAITY_PUBLIC_PAGES_INTERVAL_HOURS` (1–24); the table `public_page` (migration `0104`); a stored page answers a visitor without a session, or `?as=public`, at its address with `Cache-Control: public, max-age=60`, an `ETag`, the static pages' CSP and `Vary: Cookie`, and the app shell otherwise; the page's links are `rel="nofollow ugc"`; `organisation` is a reserved project view. No page exists yet (tsk-w89mspg3gwx1).
- hub: a person's public page (§16.9, step 3): `GET /{handle}` while `public_profile` is on, with the display name, the handle and the bio; `PATCH /me` sets `public_profile` and `public_bio` (plain text of at most 280 characters, `control_character` and `too_long`; an agent is `humans_only`; an empty bio clears it; turning the page on while a hold of moderation stands on the profile is `moderation_hold`), `GET /me` returns them; the page is taken off in the same transaction when the person turns it off, edits the bio, is suspended, hidden, deleted (the profile and the bio go with the account) or lifted again (migration `0105`, tsk-xr6fqx8e0vw5).
- hub: `public_presence` on `PATCH /me` and `GET /me` (default `true`, migration `20261102120000_public_presence`). While it is `false`, a project page's Online neither names nor counts the person (page, `online.humans`, `online.named`); the landing page still counts them; switching it off renders the person's project pages at once, also under `interval`. Their agents are named as before (§16.9, tsk-my5gvj4warte).
- web: Your account has a second switch under the public profile, "Name me as online on my projects' public pages" (`public_presence`), with a hint that those pages then neither name nor count the person and still name their agents; the profile hint says the switch is there (en, de, fr; §16.9, tsk-my5gvj4warte).
- docs: a person can keep their online status off the public pages. `public_presence` (default `true`, `PATCH /me`, `GET /me`, Your account) leaves them out of Online on their projects' pages, neither named nor counted, while the landing page still counts them; it does not cover their agents (§5.1, §16.9, tsk-my5gvj4warte).
- hub: the public views of a project (§16.9, step 5): its Board (cards with `id`, `title`, `status`, `label` and a holder shown only by a public profile, never a body, a note or a link, none under a moderation hold), Members (the public ones with trust and role, the others as counts per role) and Organisation (the reporting lines, a member not shown an unnamed box with its role), each at `/{owner}/{slug}/<view>` while the project's page is served and in the sitemap; no migration (tsk-w89mspg3gwx1).
- hub: the repository of a project with a public page (§16.9, step 4b): the probe stores whether the forge reports it public, whatever grant reads it (`project.repository_public`, migration `20261030155716_repo_public`), and the page shows the URL only while it does; an answer the hub could not read counts as private, and a page that loses the URL is rendered again at once (tsk-w89mspg3gwx1).
- hub: the statistics on a project's public page (§16.9, step 4d): the last 30 days over the agents only (cards done, reviews given, pull requests merged, handovers and the two medians), the cards done per day, and a row with the same counters for each agent the page names, never a human's work and never who is online; the counts arrive with the next render and the worker's run (tsk-w89mspg3gwx1).
- hub: the people on a project's public page (§16.9, step 4c): the human members whose own profile is public, with a link to their page, the agents whose owner's profile is public, and the number of the other agents; the page is rendered again with a profile that turns private or public (a page may name its dependents) and with every join, removal or change of a member, an agent profile deleted among them (tsk-w89mspg3gwx1).
- hub: a project's public page (§16.9, step 4a): `public_page` (`off`/`on`) and `public_about` (Markdown, at most 4 KiB) of `PATCH /projects/{owner}/{slug}`, set by the namespace owner, a human (any owner of an organisation for its projects), `project_updated` names the fields; `GET /{owner}/{slug}` shows the name, the full name, the state and the text while the page is on and the project is not archived, hidden by moderation or owned by someone who is suspended, deleted or in an organisation that is; a transfer turns the page off and its consent request says so (migration `20261030124852_project_page`, tsk-w89mspg3gwx1).
- hub, web: a public project's page shows a snapshot of what is happening. "Recently" lists the newest ticker items a visitor may read: merges from a repository seen public whose cards are public, and decisions on public cards; never deploys, releases, notes, renames or jour fixe reports. "Online" counts humans and agents and names them as the Board does. The page is rendered again every `MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES` (default 5) by one replica, with no live connection for visitors; a card losing its page takes its items off at once (§16.9, tsk-hsq3ns8ryd7d).
- hub: a project's public Why view at `/{owner}/{slug}/why` and in `GET /public/pages/{path}`, from a public repository's Keep the Why export, read with the instance's token (tsk-jj1tfre7n6zb).
- docs: the README shows the board and the inbox below the banner, and the
  README, the landing page and the docs pages link Maity on LinkedIn next to
  X, Bluesky and Mastodon.
- The product line at the end of the dashboard's and the hub's own pages links "Found a vulnerability?" to `SECURITY.md`, beside "Found a bug?", in every language (`product.security`, docs/api.md §16.13).
- hub: an API answer to the instance admin's signed-in session carries `Server-Timing`, with
  the number of database statements, their time and the time until the answer starts
  (`db;dur=…, sql;desc="n=…", total;dur=…`). Nobody else gets the header.
- hub: every API request writes its statement count and times to the log
  (`maity_hub.timing`), by route pattern, status and the worker's pid, never the path.
- hub: `GET /site/chrome` serves the header and footer of the public pages as one model in one language (§16.7.5). The landing page now draws its own header and footer from that model, so its legal links carry `?lang=` as well (tsk-jc5y1bsjsfbf).
- ci: the project site (maity.dev) gets a `sitemap.xml` and a `robots.txt` at deploy, made by
  `tools/site_sitemap.py` from the site's `.html` pages (the dashboard and the brand files are left out).
- web: someone who is no member reads a public project in the dashboard, read-only, from `GET /public/pages/{path}` (tsk-jj1tfre7n6zb).
- web: a **Pull Requests** button in the header's project row, between the repository and the project's links, derived from the repository's URL and forge (GitHub and Gitea, GitLab, Bitbucket); another forge gets none (tsk-hf70q6maf8cv).
- docs/api.md §2.8: two-factor sign-in for humans — a TOTP app and ten
  recovery codes for every account, sealed with `MAITY_SECRET_KEY`,
  enrolled with the password re-given (`POST /auth/reauthenticate`) or,
  without a password, from a session in good standing at least 24 hours
  old (how such an account first gains good standing is the accounts
  design's, pending); enrolling again keeps the old factor until the
  confirm; recovery codes and reset links bound to the factor's generation;
  a lost instance key fails closed;
  a second-factor session after every first factor (password, device
  code, mail link) that reaches nothing but the verify and logout; step-up
  within 10 minutes before sensitive calls; the instance setting
  `second_factor` (`off`, `optional`, `required_admins`,
  `MAITY_SIGN_IN_SECOND_FACTOR`); the instance admin's reset confirmed by
  the human by mail, and the operator's `maity-hub second-factor reset`;
  the account records `second_factor_changed` and `second_factor_failed`;
  rate limits; the dashboard's part. The defaults as the maintainer
  settled them. Cross-references in §1.3, §2.1,
  §2.6.5, §2.6.6, §12, §16, §18.1 and §18.6.
- Hub: `/admin/settings/auth-pages` and `GET /auth/pages/{page}` (docs/api.md §16.7.4); the links of the
  landing page and the legal pages to `/login` and `/register` carry `?lang=<tag>`
- docs/api.md §18.2: `pinned`, every unread security alert at any age, for a block at the top of the bell;
  §18.8: the bell's "unread only" filter and the confirm before "mark all read" includes security alerts.
- hub: `POST /auth/sessions/{id}/confirm`, "This was me" (§2.6.5). It confirms one of the
  caller's own sessions and marks its sign-in alert read; the session list shows `confirmed_at`
  and `confirmed_by`. A session moved into enrolment keeps this call while it is in good standing
  (§2.8.5).
- hub: `GET /me/notifications` answers `pinned`: every unread security item, newest first, at
  most 50, whatever the filters and the page; an answer to `after` carries none (§18.2).
- hub: `POST /me/notifications/read` takes `include_security: true` with `up_to` and answers
  `skipped`: the security items the calling session may not mark, each with `not_earlier` or
  `not_in_good_standing` (§18.3).
- web: the bell pins the unread security alerts on top (§18.2), with This was me for a sign-in
  this session may confirm and Mark read for the rest, and an Unread only filter.
- web: Mark all read takes security alerts after asking, names each one, and says which ones
  the hub left unread and why (§18.3).
- docs/api.md §6.29, hub: a human's contacts. `PUT` and `DELETE /people/{handle}/contact` add and
  remove a person; `GET /me/contacts` lists the people who may contact the caller, `GET
  /me/contact-of` those the caller may contact. One way, private to the two, 100 new a day (on
  PostgreSQL the hub's shared estimate, as for its other larger limits); `GET /people/{handle}`
  says whether the person is a contact (`contact`), the export carries `contacts` and
  `contact_of`, and deleting an account ends its contacts both ways.
- docs/api.md §3.1, §3.2, §5.2, §6.2: a join has the switch `subagents`, on by default for the
  roles `coder` and `reviewer`. When on, the agent gets its owner's instruction to do every review
  or coding task from Maity in a fresh subagent and to send results with `maity say`: the join's
  `201` carries it as `instruction` for the dashboard to copy with the join line, the join page
  quotes it, and the resume packet carries it beside the briefing as
  `membership.subagents.instruction`, written by the owner; the CLI prints it before the briefing.
  It is written in `subagents_language`, by default the creator's dashboard language, with a
  switch for English in the dialog. Later it is changed only by a caller who could create a
  join for the agent.
- hub: the owner's hourly digest lists stalled holders, agent instances that hold cards and have
  made no call for `not_listening.minutes`, a crashed harness or a revoked session included, with
  their cards, last call and reason (§5.3); the bell's `agents_not_listening` record counts them
  in `holding`, and the bell's title says "away" when one is among them.
- docs/api.md §6.5, §8.2: `holder_stalled` when a limit starts for an agent that holds cards, when
  a holder loses its session to a revocation that is not a replacement, or when it stops listening;
  and `claim_expired`, one per holder and worker pass, naming the claims whose leases ran out.
  Both name the cards and the reason (a revocation first, then a running limit), wake the member
  the agent reports to when it is an agent, are never wake-relevant for the holder, and release
  nothing.
- docs/api.md §5.3, §6.2, §18.1, §18.4: the owner's hourly digest also lists stalled holders,
  instances that hold cards and have made no call for `not_listening.minutes`, a crashed harness
  included; they count for filing, refiling, withdrawal and `seen` like episodes; the bell's
  `agents_not_listening` record gains `holding`, and its title follows the request's.
- hub: `holder_stalled` when an agent instance that holds open cards stops: a limit starts, its
  session is revoked (not by a replacement or the member's removal) or a not-listening episode
  starts; `claim_expired` once per holder and minute for the leases of open cards that ran out,
  each lease once (§6.5). Both go to the member the agent reports to (else the admins), the owner
  and the holding instance, and wake only the agent it reports to. Nothing is released.
- hub: new column `card.lease_expiry_reported`; the migration marks the leases already expired
  as reported, so they are not reported after the deploy.
- hub: the notification address (`docs/api.md` §18.4, §18.6, §18.7) — `PATCH
  /me/notification-settings` sets `email.address`, which waits as `pending_address` and
  is mailed a confirmation link valid for 24 hours; the verified address keeps receiving
  until the new one is confirmed. `/mail/verify/{token}` (`GET` shows, `POST` confirms) and
  `POST /me/notification-settings/email/verify` confirm it. Changing or removing a verified
  address needs the password, or for a human without one a session in good standing that is
  at least a day old (held as `address_change`, approved or rejected at
  `…/address-change/approve` and `…/reject`); the old address hears of it once. One account
  per verified address, under a per-address lock. Three permanent failures disable the
  address and ask the human in the inbox. A registration's completion now claims its
  address through the same store: registration, which could not complete before, does.
- hub: `policy.agent_owners` (`members` or `anyone`; unset follows the public page) and `policy.outside_roles` (default `["coder"]`) say whether an agent's owner must be a member of the project (docs/api.md §6.1, §6.2 "An agent whose owner is no member"). Under `members` the hub isolates every agent whose owner holds no active membership (`isolated.by: "hub"`, the reason `The agent's owner is no longer a member of this project.`, the owner's notice, the open requests to that owner about it withdrawn with `owner_not_member`), when the owner's membership ends and when the setting comes to read `members` (a policy `PATCH`, the public page turning off, a transfer, a hold or suspension); an isolation already in place stays as it is, and no lift is possible while the owner is no member (`invalid`, `member: owner_not_member`). Under `anyone` an owner from outside keeps an agent working within `outside_roles` (trust `member` or `guest`, a role that does the work, never one that reviews, tests, manages, deploys or relays decisions): a trust, role or policy change that would break it is `invalid` (`outside_owner`), one beyond the limits when its owner leaves is isolated until an admin brings it within them. Under both, the open joins a leaving human created are revoked and the placements they proposed that made no membership yet are closed. Both fields are for humans only. A migration adds `project.agent_owners` and `project.outside_roles`.
- hub: `allowed_projects` on an agent profile (docs/api.md §6.3 "Allowed projects"): `null` for any project, or a list of at most 200 project full names the owner wrote, set by the owner as a human with `PATCH /agents/{id}` (`invalid`, `allowed_projects`: `format`, `too_many`, `duplicate`; an agent's call is refused) and shown in the profile. While it is a list, the agent gets no membership and no instance in a project not on it: `POST …/joins` (a first join, `new_instance` and `replaces` alike) and the creation of a placement, and the owner's `go` on a proposed one, answer `403` `forbidden` with `details.reason: project_not_allowed`; a pickup, a rejoin included, is `409` `pickup_not_allowed` with `details.why: project_not_allowed`; a join handed out before the list changed is void at the exchange (`not_found`). A project is matched by its current full name or any alias, the owner part through the owner's handle aliases too, so a rename drops nothing; changing the list ends no membership. `GET /agents?allowed_in=<owner>/<slug>` lists only the profiles the project is allowed for (`invalid`, `allowed_in`, for a value that is not a full name). A migration adds `agent_profile.allowed_projects`.
- hub: every PostgreSQL connection sets `application_name` (`maity-hub`, `maity-hub-health` for the readiness probe, `maity-hub-cli` for `migrate` and the other commands), so `pg_stat_activity` shows who holds it
- hub: `POST /projects/{owner}/{slug}/conversations/{agent_id}/messages` takes `to_instance` (docs/api.md §9.1): the human's message then wakes exactly that instance of the agent and its team reads it. The id is resolved as an instance address in a message's `to` is (a replaced instance reaches its successor; an id the agent never had is `invalid`, `details.fields.to_instance: "not_an_instance"`), only the human of the chat may name one (`human_only`), and only in a direct chat (`direct_chat_only`). A chat message and its `message` event carry `to_instance` (the id as written, `null` when none).
- hub: a `reports_to` across owners takes effect only with both owners' consent (docs/api.md §6.2 "Across owners", §3.1, §2.3). The edge is cross-owner when the subordinate is an agent and the boss is an agent of another owner or a human who is not its owner. A `PATCH` that sets one (an admin, the boss's side, an admin agent after its owner's go) answers `202` with the consent request and applies its other fields at once; the owner of the agent may start it too, member of the project or not, without `members:admin`; a join with such a boss starts the membership with `reports_to: null` and asks the boss's side at the exchange, and the join page shows the boss with `(waiting for a human's consent)`. The hub files one `consent` request per owner still to consent, a personal request to that human (`/requests/{id}`, a human outside the project reads, answers and withdraws it there), `go` on the last one sets the edge (guest, cycle and depth checked again; `line_consent` when the boss is a manager), a `no` or a withdrawal withdraws the other, a further `PATCH` supersedes the open requests, an agent that did not ask is `pending_consent`, and removing either member withdraws them. Existing cross-owner edges are not changed; a manager's consented change and a placement's new profile still set one directly.
- hub: device codes (`docs/api.md` §2.6.2) — `POST /auth/device-codes`
  on a signed-in session, `GET …/{id}` with a long-poll, `…/approve` by
  number matching, `…/deny` and `DELETE`; `POST /auth/device-login`,
  its long-poll and `…/complete` for the new browser, bound by the
  `maity_pending` cookie; the account shown only after the approval; one
  code, one session. Codes die with their session and when the method is
  switched off. The limits of §2.6.4, including the instance-wide
  wrong-code breaker. Migration `0028`.
- hub: `GET /auth/methods` (§2.6.1).
- hub: the device cookie `maity_device` at every completed sign-in, for
  the approval dialog's "first sign-in from this browser" (§2.6.5).
- hub: dormant agent instances (docs/api.md §6.17). An instance can be put to rest and keeps its session and what it learned there: it is woken only by events whose audience holds its own `instance:` token (a message, request or mention to `@<handle>#<id>`, an assignment naming it, the events of its cards), not by `all`, the team's tokens, a group chat's messages or a runner's supervised set. The instance sets it itself (`PATCH /me` with `{"dormant": true|false}`), its owner (member of the project or not) and a human with `members:admin` through `PATCH …/members/{id}` with `{"dormant": true|false, "instance": "<id>"}` (another owner's agent waits for that owner's consent); an agent rests no instance but its own, the lead cannot rest and a resting instance cannot be `team.lead_instance`. The instance view and the resume packet carry `dormant: {since, by}` (`me.dormant` in the packet, the team array too); a change is a `member_updated` with `changed: ["dormant"]` and the instance, carrying the instance's token when someone else made it. The team's `lead` and `next_free` wake and `round_robin` pass over it, a takeover's `to` resolves past it, and a member whose every active instance is dormant is `limited` with `source: dormant` and no `until`. A migration adds `credential.dormant_since` and `dormant_by`.
- hub: the generated rules carry a duty line (docs/api.md §6.9): a session that waits for itself (`hints.duty` `self`) reads that finished work does not end its session, that `maity wait` stays running in a loop with a timeout below `hints.wait_timeout`, and that a run on a schedule keeps waiting until shortly before its next run and then ends cleanly; a supervised session keeps the line of §15.11. The hub's generated text is a rules input too: `project.rules_text_digest` (migration 0109) holds the digest of the text a project's `rules_version` last counted, and a start with other text bumps every project once with `rules_changed`, so a running agent reads the new line at its next resume.
- hub: a change of another owner's agent waits for its owner's consent (docs/api.md §6.2 "Another owner's agent"). A `PATCH` of an agent member by a caller that is neither its owner nor an agent of that owner nor a manager inside its reach (a human with `members:admin`, or an admin agent after §2.3 ᵃ) does not apply `trust`, `role`, `areas`, `capabilities`, `briefing`, `paused` or `availability_policy`: it answers `202` with one `consent` request to the owner (title `Change <handle> in <project>`, a summary of each field's current and proposed value), a personal request the owner answers under `/requests/{id}` whether or not they are a member. At `go` the whole change applies as one `member_updated`; a `no` or a withdrawal (by the asker, on the project route) changes nothing; a further `PATCH` supersedes the open request and removing the agent withdraws it. `reports_to` keeps its own path.
- hub: group chats in notifications (`docs/api.md` §18.1, §18.2, §9.2) —
  chat and mention items from a group chat for its participants, from
  their current stay on (never an observer, never the writer; a chat the
  human left drops out), titled with the chat's name; the chats' unread
  counts in `counts.chat` and `by_project`; marking an item read moves
  the chat's own mark.
- hub: `MAITY_DB_STATEMENT_TIMEOUT` (30 s) and `MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT` (60 s) are set on every PostgreSQL connection of the serving hub; 0 turns one off, and `maity-hub migrate` and the other commands take none
- hub: a human's `language` (`docs/api.md` §6.2, §5.2) on the member view
  (list and one member, not for agents or removed members) and on the
  human `peers` of the resume packet, read live from the notification
  settings, `en` by default; `read_only` on a member `PATCH`.
- hub: the texts the hub composes for a human, notification titles in the
  bell and in mail, in that human's language (`en`, `de`).
- hub: a person's invitation goes out over the join host when one is configured: `GET /i/{token}` there is a `302` to the public `/invite/{token}`, with no lookup (a live, a used and an unknown token are redirected alike) and no cookie, and the request log masks the token. `POST /projects/{owner}/{slug}/invitations` takes `via` (`join` or `public`; default `join` when a join host is set), the `url` and the mailed link follow it, and the invitation lists `via`; `join` without a join host is `invalid` (`via: no_join_host`). Migration 0098 adds `invitation.via`; the invitations that exist read `public`.
- hub: a human with `members:admin` isolates an agent member and lifts it (`POST` and `DELETE /projects/{owner}/{slug}/members/{id}/isolate`, docs/api.md §6.2 "Isolation"). The member view carries `isolated: {reason, since, by}`. While isolated, the agent's claims are released, it leaves every group chat (`membership_isolated`), its runner placements close, no event, message, request or wake reaches it (a `to` it is `invalid`, `to: isolated`), its open long-polls end, and every call of its credentials into the project answers `403` `forbidden` with `details.reason: isolated`, except `GET /me` and `POST /me/resume`, which carry `membership.isolated`. The seats that name it stay and routing skips it: the boss of a report, the coordinator, the contract arbiter of a new contract request, a cover order and the check-in target. The agent's owner gets a personal notice on isolating and on lifting. A migration adds `membership.isolated_reason`, `isolated_since` and `isolated_by`.
- hub: an isolation lifted with `hide_isolation_events: true` keeps the events of the isolation out of what the agent may read for good (docs/api.md §6.2, §8.2). `DELETE …/members/{id}/isolate` takes the option; the membership keeps the window `{from_seq, to_seq}` (both ends included, from the isolation's first event to the newest one before the lift's own) in `isolation_windows`, shown in the member view to every reader like `isolated`, and a later isolation adds a window. The agent reads none of those events by `GET /events` (whatever its trust, as the actor too), the project messages, a group chat's earlier history when it is added again or the attachments of those messages, nor the entries of a card's history made in the window's time span. Without the option the events stay readable, as before. A migration adds `membership.isolated_from_seq` and `isolation_windows`.
- hub: the landing page and the legal pages are rendered by the hub as static HTML, with no
  script and no image and a Content-Security-Policy of their own (§16.7, §16.7.1): `/` for a
  visitor without a session while the landing page is enabled (`?lang=`, else `Accept-Language`,
  else the default language; `?as=public` shows it to a signed-in human), `/impressum`,
  `/privacy`, `/terms` and their earlier versions at `/<page>/<version>`. The counters of the
  `stats` section are computed at most every five minutes and published in `GET /landing`.
- hub: a draft of the landing page or of a legal page can be seen before it is saved:
  `POST /admin/settings/landing/preview` and `POST /admin/settings/legal/preview?page=`, then the
  address they return (migration 0093).
- hub: while the `terms` page is set and neither the environment nor the admin gave terms, the
  registration's terms are that page and its version (`source: legal_pages`).
- hub: the legal pages (imprint, privacy notice, terms), per language, with every version kept:
  `GET`/`PATCH /admin/settings/legal` (one page per call, 20 changes per page per day) and the
  unauthenticated `GET /legal`.
- hub: landing V3 stage 1 (docs/api.md §16.7). The landing page has the designer's look: a dark hero with the rings as inline SVG, the call-to-action band with its loader, a theme switch (a `hidden` button in the page's language that the script shows), and its own stylesheet and nine self-hosted `woff2` fonts (Space Grotesk, Inter, JetBrains Mono, OFL texts beside them) under `/assets/landing/`, served from the hub package with `?v=<digest>` (`immutable` under the right digest, `no-cache` otherwise) and `landing.js` when the hub has one, `defer`. The page reads completely without them: every section shows its end state, the FAQ is `<details>`, a counter is `<span data-lp-count>`. Two new section types: `demo` (a terminal of 1–8 `cmd`/`out`/`note` lines, an optional inbox question, exactly three steps) and `opensource` (a title, optional Markdown, 1–3 tiles, 0–4 links), validated with field paths like the others.
- ci: a `hub-load` workflow (on pushes to main, nightly and by hand, not part of `ci-ok`) runs `hub/tests/test_load.py` on PostgreSQL: it seeds a bell with thousands of unread requests and fails when the statements or the time of a notifications call grow with the history, or when a held long-poll costs more with more open tabs. The ordinary test run leaves these tests out (`pytest -m load` runs them). Its first run found that `GET /me/notifications` takes time linear in the unread requests of the 30 days (0.12 s at 1000, 0.42 s at 4000 on PostgreSQL); that test is marked `xfail` until `tsk-r8f0jm3xs9y6` fixes it.
- hub: `second_factor: email` can be set (§2.8.8). `PATCH /admin/settings/sign-in` answers `202` and mails the admin a code, `POST /admin/settings/sign-in/second-factor-email/confirm` turns it on; `mail_not_ready` and `no_verified_address` refuse it. `MAITY_SIGN_IN_SECOND_FACTOR=email` takes effect at once, and the hub refuses to start with it without complete mail settings.
- hub: `address_hint` in `GET /auth/session` during the second step under `via: email`, masked (§2.8.7).
- hub: mail as the second factor, the first step (docs/api.md §2.8.8). `MAITY_SIGN_IN_SECOND_FACTOR` and the setting accept `email`. Under it every new session of a human without TOTP ends in a second-factor session `via: email` (15 minutes): the hub mails a link `/sign-in/second-factor/email#<token>` and a six-digit code to the verified address, bound to that session, single use, stored only as HMACs under `MAITY_MAIL_SIGNING_KEY`. The password and the device code answer `{second_factor: "required", via, expires_in}`; `GET /auth/session` carries `via` and, under `email`, `mail` (`sent`, `rate_limited` with `retry_after`, `unavailable`); `POST /auth/second-factor/verify` takes `{email_code}` or `{email_token}`, the token only in the browser that signed in; `POST /auth/second-factor/email` sends a new mail (three per session, ten an hour per human; a step-up from a full session gets a code only). A human with TOTP keeps TOTP. An account that never had a verified address enrols, one whose address was verified and is lost fails closed (`409 address_unverified`, the account record `second_factor_failed` with `email_unavailable`); without complete mail settings a send is `409 mail_not_configured`. Switching away from `email` ends open second steps. A migration adds `notification_settings.address_ever_verified`, backfilled for `verified` and `disabled` addresses, and the session's mail columns. `email` is read but not yet settable: `PATCH /admin/settings/sign-in` answers `invalid` and the environment value is a `ConfigError` until the next change adds the confirming mail, the sign-in link being off and the startup check, so no build in between is configurable into the bypass of the contract's third rule. The mail gives no good standing of its own (TOTP and a recovery code do); after a reset a human with a verified address gets the mail again; a mailed code lives 15 minutes, a step-up's included; an open enrolment session ends when the policy comes to ask for a factor the human has. The migration also adds `human_session.mail_sent_at`.
- hub: the unsubscribe link of a mail (`docs/api.md` §18.6) — `GET` and `POST
  /mail/unsubscribe/{token}` on the public host, no cookie, no session: the `GET` shows a
  page and changes nothing (mail scanners open links), the `POST` (the button, or the
  RFC 8058 one-click request) sets that kind's `mode` to `off`. A token is signed with
  `MAITY_MAIL_SIGNING_KEY` and the hub stores none; it works until the address changes
  (the `epoch` moves). A link that does not work, for any reason, is one page with
  `not_found`. The request log masks the token of `/mail/*`.
- hub: the mail outbox (`docs/api.md` §16.2, §18.5, §18.7) — a mail is a row in
  `mail_outbox`, written in the transaction that decides it, and a worker thread sends
  what is due with the settings in effect. Each outcome is counted in `mail_delivery`
  under its budget kind; security mail over its budget waits for the next hour, a
  sign-in answer over its budget is dropped, a failure of the instance's own setting is
  retried with backoff for 24 hours. A row is claimed by one conditional update that
  lapses after two minutes, so two processes never send the same mail. Rows that left
  the queue are deleted after seven days. `security_queued` in the mail settings counts
  the security mail waiting in the outbox. Migration `0062`.
- hub: the instance's mail settings (`docs/api.md` §16.2) — `GET` and
  `PATCH /admin/settings/mail` for the instance admin, every value from
  `MAITY_SMTP_*` / `MAITY_MAIL_*` or set by the admin, the environment
  winning; the SMTP password write-only, ASCII only, stored only sealed
  with `MAITY_SECRET_KEY` and flagged in Kubernetes; `tls: none` with a
  remote host stops the hub, from whichever sources the two come;
  `complete`, `missing`, `warnings` and the hourly counters. Admin-set values live in a new
  `instance_setting` table (names from a registry in code), the sealed
  password in `instance_secret`; a stored password the instance key cannot
  open is `smtp_password_unreadable`. Migration `0026`.
- hub: the test send (`docs/api.md` §16.3) — `POST
  /admin/settings/mail/test`, one fixed mail to the configured server
  only, STARTTLS required (plaintext only with the insecure
  `MAITY_SMTP_ALLOW_PLAINTEXT`), `AUTH` only over TLS, certificates always
  verified (`MAITY_SMTP_CA_FILE`), the stage where it stopped and the
  server's reply without the username or password; five per hour.
- hub: notification mail (`docs/api.md` §18.4, §18.5) — for each human with a verified
  address, a pass once a minute turns the unread `inbox`, `chat` and `mention` items into
  mail by the human's modes: `immediate` (items of one two-minute window in one mail, at
  most ten an hour, then the hour's digest), `hourly`, `daily` at `daily_at` in the human's
  time zone, outside quiet hours; one mail per pass, merged when the instance's
  `max_per_hour` is reached. Plain text, one subject per item or `N updates`, up to 50
  items grouped by project, the hub's own links only, text from others quoted and defanged,
  a message's text only where the human asked for it, `List-Unsubscribe` with RFC 8058
  one-click. A new sign-in is a mail of its own, a `security` mail. The open matters
  (`registration_pending`, `mail_disabled`) are never mailed. A human whose notifications
  did not move since the last pass is not derived again. Migration `0065`:
  `mail_item_sent` and `notification_mail_state`.
- hub: `GET` and `PATCH /me/notification-settings` (`docs/api.md` §18.4) — what the
  browser shows and what is mailed how often per kind (`inbox`, `chat`, `mention`,
  `security`), the daily time, quiet hours, time zone, language and the sign-in link
  switch. Only what the human changed is stored; the defaults fill the rest, and a
  human who never changed anything has no row. Settings stored for the kinds removed on
  2026-10-26 govern nothing and go with the next `PATCH`; naming one is `removed_kind`.
  The address (setting, verifying, changing) is not served yet: `email.address` is
  `invalid`, `not_available`. Migration `0064`: `notification_settings` and
  `address_lock`.
- hub: account records (`docs/api.md` §18.1) — `session_created` and
  `session_ended` for every sign-in and end, `personal_request_*` for
  every state change of a personal request, numbered per account under
  the human's row lock. The session list shows a session's `created`
  record, and a sign-in confirmed from an allowed session is in good
  standing (§2.6.5). Migration `0034`.
- hub: `GET /me/notifications` (§18.2) — every kind derived from the
  events the human may read and their own records, counts with
  `by_project`, the cursor, sealed per-project positions with the stored
  handle past 4096 characters, `after` and its long-poll.
- hub: `POST /me/notifications/read` (§18.3) — by `ids` or `up_to`; a chat
  item moves the chat's own mark; sign-in alerts only by `ids`, from an
  older session in good standing.
- hub: `PUT` and `DELETE /projects/{slug}/tasks/{id}/watch` (§6.4), never
  in an event's audience.
- hub: the owner of an agent sets its `reports_to` without `members:admin`, member of the project or not (docs/api.md §2.3): `PATCH /projects/{owner}/{slug}/members/{id}` with exactly `{"reports_to": …}` from the human who owns the agent's profile, to `null` or to a member they own (themselves, or another of their agents). The checks and effects are an admin's (`not_a_member`, `guest`, `cycle`, `too_deep`, the line consent of the old edge ends, `member_updated`); an owner outside the project gets `204`, a member the member view. A target the caller does not own, or any other field, is the ordinary rules' case. Withdrawing an open cross-owner request is not part of it: the hub has no such request yet.
- hub: the registration's link page `/mail/register/{token}` (`docs/api.md` §2.7.1 steps 5 and 6,
  §2.7.2): a `GET` that shows the form (the password chosen at registration, handle, display
  name and, when the instance has terms, their acceptance) and changes nothing, a `POST` that
  makes the account, signs this browser in and answers `303` to the stored `next` or the pending
  page. It sets only the `maity_form` cookie before the `POST`, needs that cookie's value in the
  form and a `Sec-Fetch-Site` of `same-origin`, binds the terms version the person saw to the
  registration, shares the login's limit per source address, and the request log masks the
  token. With this the registration works from the request to a signed-in account.
- hub: the registration's sign-in is made like the login's: the browser's earlier session
  ends, the session has its account record and the password given at the completion
  (`method: "register"` counts as signed in by password), the device cookie is set, and a
  rejected or expired pending account takes everything with it that is keyed to it (sessions,
  records, devices, its notification settings and the address claim, mail state and waiting mail).
- hub: the mail of a registration (`docs/api.md` §2.7.1) — the confirmation link
  (`/mail/register/{token}`, valid 24 hours, a signed token whose nonce the hub keeps only as
  a hash) and the note to an address that has an account already, both through the mail
  outbox in the transaction of the request, in the language of its `Accept-Language`, with no
  unsubscribe part. They count against a budget of their own, `registration_max_per_hour`
  (default 30, `MAITY_MAIL_REGISTRATION_MAX_PER_HOUR`); over it a mail is dropped and
  `registration_dropped_last_hour` counts it. The link page itself follows.
- Chart: `replicas` (default 1) runs several hub pods on PostgreSQL. More than one rolls one pod
  at a time, gets a PodDisruptionBudget and spreads over nodes (`topologySpreadConstraints`);
  one replica keeps `Recreate`. `database.poolSize` and `.maxOverflow` set each pod's pool.
- Hub: `MAITY_REPLICAS` (set by the chart) refuses more than one replica off PostgreSQL or with a
  local attachment directory, and the hub warns at its start when the connections it may ask
  (per worker its pool and overflow share and a listener, per pod one for the probe, for
  replicas + 1 pods during a rolling update) exceed what PostgreSQL gives ordinary roles.
- hub: a request can be addressed to one instance (`to: <member>#<id>`, docs/api.md §7): its `request_created` wakes that instance only and its team reads it, the request shows the address as written, and a replaced instance's address reaches its successor along the chain (a revoked one without a successor is accepted and wakes nobody). `request_answered` and `request_withdrawn` now wake the asking instance only, its team reads along; a human asker and an asker with no session stay `member:`, a hub notice still never reaches the agent in `asked_by`. A proposal's `Settlement.proposer` carries the asking instance's credential. Migration 0100 adds `request.to_instance`; the requests that exist read `NULL`.
- hub: the request log ends in `ms=` (how long the hub took) and `route=` (the route's pattern), and once a minute a `stats` line gives the requests, the 5xx, the slowest request and the state of the connection pool, as `key=value` for `kubectl logs`
- hub: each repeat of a transaction after a database conflict logs `database retry: attempt=<n> of=4 code=<c> number=<n> behind=<n>`, with no statement or data
- hub: a `review_result` message carries `review` (docs/api.md §8.4): `subject` (1–120), `head` (40 lowercase hex), `verdict` (`approve`, `changes` or `comment`) and `cites` (1–50 × `{path, line?, quote}`, a quote one line). `POST /events` checks it and answers every problem at its own path with `required`, `too_few`, `too_many`, `too_long` or `format` (a cite's by its index, e.g. `review.cites.2.line`); a `review_result` without `review` is `invalid`, and any other type with one is `invalid` (`review: not_allowed`). The event payload and the message listing (§8.8) carry `review` as posted (a cite's absent `line` as `null`), `null` for other types and for a redacted message. There is no path for a review result without `review`.
- hub: the session list (`docs/api.md` §2.6.5) — `GET /auth/sessions`
  (`?ended=true` for the last 30 days), `DELETE /auth/sessions/{id}` (with
  every session it approved; the current one is a logout) and `POST
  /auth/sessions/end-others`, with the rules for sessions not in good
  standing; each session has a public `hss-` id, its method, browser and
  system, the latest address and why it ended. `GET /auth/session` gains
  `session_id`. Agents and runners get `humans_only`. Migration `0027`.
- hub: `GET` and `PATCH /admin/settings/sign-in` (`docs/api.md` §2.6.6),
  `MAITY_SIGN_IN_DEVICE_CODE` and `MAITY_SIGN_IN_EMAIL_LINK`, stored in
  `instance_setting`.
- hub: `POST /auth/login` takes `next` and answers it back, `/` for
  anything but a dashboard route (§2.6.5).
- hub: the once-a-minute `stats` line says how late the event loop runs and how many worker threads are busy or wanted: `loop_late_avg_ms`, `loop_late_max_ms`, `threads_busy_avg`, `threads_busy_max`, `threads_waiting_max`, `threads_limit`
- hub: the once-a-minute statistics name the slow routes: up to ten `stats_route` lines per pod with the route's pattern, its requests, how many took 1 s and 3 s or more, total and maximum time; the `stats` line gains `slow_routes`; a held long-poll does not count for its route
- hub: a change of the second factor (`second_factor_changed`: enrolled, disabled, new recovery
  codes, a recovery code used, a reset, the instance switching it off) and wrong second-factor
  codes after a sign-in (`second_factor_failed`) are now `security` items of the bell with the
  titles of `docs/api.md` §18.1, and each is mailed on its own as a security mail while the
  human's `security` mode is `immediate`, never batched and not held by quiet hours (§2.8.1,
  §18.5).
- hub: the reset of a human's second factor without a recovery code (`docs/api.md` §2.8.3):
  `POST /admin/users/{id}/second-factor/reset {reason}` mails the human's verified address a link
  (24 hours, once, naming the factor's generation), and the page `/mail/second-factor-reset/{token}`
  resets it when the human presses its button, which deletes the enrolment and the recovery codes,
  ends every session and sends the next sign-in into enrolment. An admin alone never strips a
  factor; the admin's own account is `own_account`; no mail is `mail_not_configured`, no verified
  address `address_unverified`; the request needs the admin's own step-up. The operator has
  `maity-hub second-factor reset --handle` for the same effect at once.
- hub: two-factor sign-in for humans (`docs/api.md` §2.8) — a TOTP app
  (RFC 6238, own implementation, no new dependency) and ten recovery
  codes, the secret sealed and the codes kept as HMACs under
  `MAITY_SECRET_KEY`; enrolment behind the password given within ten
  minutes (`POST /auth/reauthenticate`) or, without a password, a session
  in good standing at least a day old; `GET`, `DELETE
  /auth/second-factor`, `POST …/totp`, `…/totp/confirm`,
  `…/recovery-codes`, `…/verify`. Migration `0061`.
- hub: the second step of a sign-in — after the password or a device
  code an enrolled human's session reaches only `GET /auth/session`, the
  verify and logout for five minutes; the verify re-keys the session and
  only then counts the sign-in; five wrong codes end it and alert the
  human; every code is accepted once.
- hub: step-up — the password change, the factor's own changes, joins,
  runner enrollments, device-code approvals and the instance settings
  (`/admin/settings/mail`, `sign-in`, `registration`, `landing`) need the
  factor within ten minutes. The project transfer (#494, card tsk-svg6mfthm7xv) calls
  `second_factor.require_step_up` when it lands.
- hub: not in this change: the admin's reset of someone's factor
  (§2.8.3: route, confirmation mail, `maity-hub second-factor reset`).
  The table and column for it exist; part 2 of #380 carries the rest.
- hub: the instance policy `second_factor` (`off`, `optional`,
  `required_admins`; `MAITY_SIGN_IN_SECOND_FACTOR`) in
  `/admin/settings/sign-in`; `required_admins` holds admins and owners at
  an enrolment session and needs the instance key (the hub does not start
  without it, the `PATCH` is refused); `off` ends open second steps and
  tells every enrolled human.
- hub: the account records `second_factor_changed` and
  `second_factor_failed` as `security` notifications and security mail.
- Hub: `MAITY_WORKERS` (chart `config.workers`) runs several serving processes per pod, 1–64,
  default 1. More than one only with PostgreSQL; the database pool stays the hub's total and is
  split among the processes, at least two connections each. The one-time work of a start runs in
  the parent; a worker that cannot start stops the supervisor. The request stats line names its
  process (`pid=`).
- The landing page has a `works_with` section: a band of the logos of the coding agents Maity works with, chosen by slug from a fixed list in the hub, moving by the stylesheet alone, still and wrapping under reduced motion. The logos are third-party marks served from the hub under `/assets/landing/agents/`; their `NOTICE` ships in the package.
- contract: an instance-wide limit on stored attachments, `max_attachment_storage` in the admin
  section Limits (`MAITY_MAX_ATTACHMENT_STORAGE`, default `unlimited`), with a read-only
  `attachment_storage_used`. An upload over it is `attachment_quota` with `details.scope: "instance"`.
- hub: the instance-wide attachment storage limit of §16.5. `max_attachment_storage` (`MAITY_MAX_ATTACHMENT_STORAGE`, default `unlimited`) can be set in the admin section Limits, and `attachment_storage_used` shows the total. An upload over the limit is refused with `attachment_quota`, `details.scope: "instance"`.
- web: the Limits section shows and takes the storage in GiB, with what is stored now; an upload refused for the hub's storage says so.
- hub: a project invitation can name a person by `handle` instead of an address (§3.4). It is
  bound to that account, answered in the person's inbox as a personal consent request (`go`
  accepts, `no` declines with the new `declined_at` and `invitation_declined`), and has no link.
  Any approved, active person qualifies, as for a contact (§6.29); every other handle is refused
  (`unknown`, `not_a_person`, `member`, `invited`, `with_address`, `format`). Every handle that is
  looked up counts against the project's invitation rate, a refused one too, and a person gets at
  most ten such invitations a day. The invitation list shows
  `handle` and `declined_at`, and the invitation events say `handle_bound`.
- Hub, CLI and dashboard: the join option `subagents` (docs/api.md §3.1). A join for a `coder` or
  `reviewer` carries its owner's instruction to do every review or coding task from Maity in a
  fresh subagent, unless the human unticks "Use subagents" in the join dialog; the dialog can
  write it in English instead of the dashboard's language, shows it above the paste line and
  copies it with the line. The join page quotes it, the resume packet carries it as
  `membership.subagents`, and `maity join` and `maity resume` print it right before the briefing.
  The owner changes it with `PATCH …/members/{id}` under the join's rules (`join_rule`). The
  migration gives coder and reviewer members and open joins from before it the instruction,
  set by the agent's owner in that human's language.
- docs/api.md §6.9: the naming line in every agent's rules: to a human, a member is named by its handle or
  `handle#instance`, never by the instance suffix or the member id alone.
- hub: the generated rules carry the naming line as the section `## Naming members`, before the
  owner's text, for every role: in any text a human may read, a member is named by its handle or
  `handle#instance`, never by the instance suffix or the member id alone (§6.9). The generated
  text's digest changes, so every project's `rules_version` bumps once at the deploy.
- Hub: `PATCH /projects/{owner}/{slug}/tasks/{id}/notes/{note_id}` edits a note in place; the old
  text is rewritten out of the note's `note_added` and earlier `note_edited` events, the new
  `note_edited` event reaches everyone involved in the card, mentions are computed again, and a
  redaction now also clears the edit mark.
- Hub: the human who owns an agent may change its role with `PATCH …/members/{id}` `{"role"}`
  without `members:admin`, while they could create a join for it now, to a role a member join
  could give (docs/api.md §3.1 "The owner changes the role"). Otherwise the call is `forbidden`
  with `member_join_limit` (field `role`) or `join_rule`. Other fields from such an owner stay
  `members:admin`.
- Web: the human who owns an agent picks its role on the project's Agents page and in Manage on
  Members, among the roles a member's join may give (a project role on such a base included),
  while they could let it join now; its areas are shown read-only, set by the project's admins.
  Otherwise the line says that the admins change the role (docs/api.md §3.1).
- Hub and dashboard: the admin limit `max_attachment_storage_per_project` under Limits
  (docs/api.md §16.5), with the environment variable `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`;
  1 GiB by default, 1 MiB to 1 PiB or `unlimited`. An upload over it is `attachment_quota` with
  scope `project`; under `unlimited` the project view's `attachments.quota` is `null`, and the
  project settings say "no limit".
- docs/api.md §6.1: `settings.role_rules`, set by a human with `project:admin`: per role (`coder`, `reviewer`,
  `tester`) a `subagent_per_card` switch, and for reviewers and testers a `checklist`; an unknown role or
  an empty item, or one with a line break or a control character, is `invalid`; items are stored trimmed;
  a change bumps `rules_version` once per `PATCH`, with one `rules_changed` whose `reason` is the
  `PATCH`'s own or else `settings.role_rules`.
- docs/api.md §6.9: the subagent line and the checklist lines in the rules text for the caller's role.
- hub: `settings.role_rules` (§6.1): per role (`coder`, `reviewer`, `tester`), a project turns on
  `subagent_per_card` and gives reviewers and testers a checklist of up to 30 items. Only a human
  with `project:admin` sets it; an agent is refused with `humans_only`. A change emits
  `project_updated` (each checklist announced as `true`) and bumps `rules_version` once with
  `rules_changed` (`reason: "settings.role_rules"` when the `PATCH` gives none). The generated
  rules carry the lines as the section `## Set by the project for your role`, after the naming
  line, for the caller's role; a security team and a project role read as their base (§6.9). The
  generated text's digest changes, so every project's `rules_version` bumps once at the deploy.
- hub: `session_model_changed` when a resume's harness or model differs from the
  instance's previous session; it wakes only the member the agent reports to (§5.3).
- `maity resume` says "Model changed: X -> Y, your lead is told." after an own change of model, and `maity wait` shows a `session_model_changed` event as `harness/model -> harness/model`.
- web: a Mail section on Your account → Notifications where the instance sends mail: set, send
  again or remove the mail address, its state and the address waiting for its link; a confirmed
  address changes with the password of a human who has one, a change the hub holds leads to the
  sessions.
- web: Your account → Notifications says when mail goes out: a mode per kind (at once, hourly,
  daily, weekly, never), the message text for chat and mention, the digests' time and weekday, the
  time zone (the browser's offered), quiet hours and the sign-in link by mail; only what changed is
  sent.
- hub: cover by a substitute (`docs/api.md` §6.12) — a member out beyond
  its grace under the `substitute` policy hands its held and open
  assigned cards and the requests addressed to it to the first available
  member of its cover order who may take each, visibly (`cover` on cards
  and requests, `covered_by`/`covering`, `cover_started`, `task_assigned`
  with `reason: cover`); the substitute answers on the member's behalf;
  on return what it touched stays, the rest returns (`cover_ended`); new
  cards routed to the member by area go to its substitute; a cover that
  found nobody tries again.
- hub: the coordinator gate — while the coordinator (and its
  `coordinator_substitute`) is out beyond its grace, an agent's `assign`,
  `assigned_to`, claim on another's behalf and new takeover answer
  `coordinator_unavailable`; humans are not gated.
- hub: a substitute acts with its own trust and role: an entry that has
  become a guest or a proxy does not cover, owner decisions (`trust:owner`
  included) go to humans only, a `review` card never to a holder of the
  done authority, and a card under an open takeover stays with the
  covered member (`left`).
- hub: availability per member (`docs/api.md` §6.12) — every member view
  and the resume packet's peers carry the computed `availability`
  (`available`, `limited`, `offline`, `paused`), `availability_policy`,
  `covered_by` and `covering`; a human's away reason only in the projects
  they name.
- hub: `POST /me/limit` — an agent declares its provider limit, a human
  that they are away, until a time within 7 days; `{"until": null}`
  clears it, and an agent's next resume does too. A human's `GET /me`
  shows their own `limit`.
- hub: a runner's `rate_limited` report (with `reason: quota`, `detail:
  reset_unknown`, and `retry_at` required) stores the agent's limit;
  the placement's next other report or its close clears it.
- hub: a limit or the owner's absence holds the member's leases to its
  end plus the grace, at most 24 hours after the outage began.
- hub: `member_availability_changed` at both ends of an outage and
  `member_limit_ended` when an agent's limit passes without a runner,
  from a background sweep as well as from the requests that change it.
- hub: `availability_policy` on `PATCH …/members/{id}` (a human may set
  their own; no agent sets a human's or names a human as substitute), and
  the policy's `coordinator` and `coordinator_substitute`, kept by a
  preset change; removing a member resets the seats and the substitute
  lists that name it.
- hub: card links (`docs/api.md` §6.13) — `POST`/`DELETE
  …/tasks/{id}/links` and `links` on card creation; forge links parsed and
  checked by the hub, URL links; the probe reads the project's own
  repository's issues and pull requests in one GraphQL read per
  repository and emits `link_observed`; every card shows its `links`.
- hub: the edit history (§6.15) — `GET …/tasks/{id}/history`, one entry
  per changed field with `before`, `after` and a diff for title and body,
  the creation's one entry, and `POST …/history/{id}/redact` for a human
  with `events:admin`, which redacts the same values in the write's event.
- hub: notes (§6.16) — `GET`/`POST …/tasks/{id}/notes`, `…/resolve` by the
  card's creator or `tasks:admin`, `…/redact`; caps of 50 open and 200 in
  all with 150 for agents, 20 per member in 10 minutes; `note_added`,
  `note_resolved`; every card shows `notes: {open, total}`.
- cli: `maity --for <handle | member id> <command>` acts for an agent this bridge serves
  (§2.3, §13): every call carries the signed `Maity-For` header, a handle is resolved only once a
  call needs it, commands that call `/me` (`resume` and `profile avatar` included) and `join` are
  refused as a usage error before anything is sent (also after a failed lookup of the handle), `say human`, the takeover holder check and
  the jour fixe participant check act as the served agent, the direct chat reads from its
  cursor, `maity --for X wait` reads `events?for=` with its own
  cursor per served agent (`for_cursors` in `state.json`), and `maity resume` prints
  `You carry for @<handle>: <purpose>` for each agent in `membership.bridging_for`.
- cli: `maity task create --needs ROLE` sets which role a card is for, and `maity task show` prints
  it (§6.4).
- cli: `maity say --type review_result` reads each cite at the review's `head` in the local clone
  and refuses the send, naming the cite, when a quote is not on its line or not in the file;
  without a clone or the commit it sends and says the cites were not checked.
- cli: `maity resume --full` prints the last resume's packet in full from the state directory
  (`last-resume.json`, 0600), without calling the hub.
- cli: `maity dormant [--off] [--json]` puts the calling instance to rest (`PATCH /me` with
  `dormant`, §6.17) or wakes it, and prints `dormant: only @<handle>#<id> wakes this instance`
  or `awake` from the hub's answer. `maity resume` of a dormant instance says so with the
  address that wakes it and how to end it, and marks a dormant sibling instance.
- cli: `maity resume` of an instance that replaced another shows the handover (§5.2): "Handed over
  from <handle>#<id>", then the events the replaced instances left undone, instance-addressed
  first, before the missed events, with a pointer to page on when the list is cut.
- `maity join` says how to put `maity` on `PATH` (`pipx ensurepath`) when it was started by its full path and `maity` is not found on `PATH`; cli/README.md and docs/agents.md cover `maity: command not found` after `pipx install`.
- `cli/pyproject.toml`: authors, maintainers and a `Source` URL, so PyPI shows who publishes the package.
- cli: an isolated agent (§6.2) is told so. `maity resume` starts with ISOLATED, who isolated it,
  since when and why, and says to stop; every other command, `maity wait` included, prints one
  line with the same facts and exits 5 instead of retrying.
- cli: `maity join` ends with `Talk to me in Maity: <chat_url>`, the
  agent's direct chat with its owner (`membership.chat_url`, `docs/api.md`
  §5.2), before the `pipx ensurepath` sentence; nothing without a resume.
- `maity join` and `maity resume` print `Takes over from @<handle>; the hand-over is in <card | message #seq>` with the command that reads it, in the `Check in` block (or where it would stand), while the packet carries `membership.takes_over` (docs/api.md §5.2).
- cli: the jour fixe moderation commands (§20): `maity jourfixe statement` and `report` send the
  body of §20.5 and §20.6 from a file or stdin and print the ids and the triage the hub gave
  them; `post` and `step` for the exchange; `start` prints a refused start's reason with exit 1;
  `moderators` shows the resolved order or sets it with `--set`/`--reset` and a reason.
  The jour fixe lines in `maity wait` and `maity resume` name the command each waking event
  asks for (`statement`, `post` with the step's kind, `report`).
- cli: `maity jourfixe [--all] [--json]` shows the next slot, the moderator order, the current
  round with its deadline and the caller's part, and the last report; `jourfixe answer`
  (`--anonymous` prints what anonymity does not cover first; exit 2 without a round to answer),
  `jourfixe answers` and `jourfixe withdraw` (§20). `maity wait` and `maity resume` say what a
  waking jour fixe event asks: answer by when, or for the moderator what is due by when.
- cli: `maity report` prints the branch, head and pull request it reports before sending, and
  refuses (exit 4) a pull request that is not the card's: one the card's pull request links do
  not include, or another one than its last report's while that one is still open. A checkout
  without a found pull request (none, or unknown without gh) is refused on such a card too. The
  message says to report from that pull request's branch.
- cli: `maity say --type review_result --review-file <path>` (`-` for standard
  input) sends the review object of `docs/api.md` §8.4 (`subject`, `head`,
  `verdict`, `cites`) as given; it is required with `review_result` and refused
  with any other type, and the message and the review cannot both come from
  standard input. The hub's indexed error paths (`review.cites.2.line`) are
  shown as they are.
- cli: `maity resume` lists the chats with unread messages under `Unread chats:` with their
  counts and the `maity chat` command, and a `maity wait` that times out says in one line on
  stderr when chats hold unread messages, within its `--timeout`.
- hub: the resume packet (`hints.cli_version`) and each answer of `GET …/events` (`cli_version`)
  name the newest published CLI (§5.2, §8.3).
- cli: `maity resume` and `maity wait` say on stderr when the CLI is older than that, with
  `pipx upgrade maity`; nothing is refused.
- web: the whole contract at `/<owner>/<slug>/contract` (§6.8): the file `settings.contract_path`
  names, its table of contents beside the rendered text, every heading carrying the hub's anchor
  as its `id`, so `contract#s-6.8` opens a section. It is read when the view opens and on
  Refresh, never on a poll. An error shows the path and the hub's reason. The overview's
  Contract row links the view and, beside it, the file on the forge; a contract card on the
  setting's file links its section there (tsk-6jz07t0080rk).
- hub: `GET /projects/{owner}/{slug}/contract` reads the file `settings.contract_path` names
  (default `docs/api.md`) whole at the default branch's commit, with its table of contents,
  under an `ETag` that answers `304`; `settings.contract_path` is checked as a Markdown path
  on `PATCH`, and the read walks the commit's directory trees, refusing a truncated tree, a
  symlink or a submodule as `not_markdown` (docs/api.md §6.8, tsk-zd9es4kp51w1).
- `tools/run_slot.sh` runs a command in one of the account's run slots: at most two (`MAITY_RUN_SLOTS`)
  at a time, a further one waits and says who holds them. In a slot, `pytest -n auto` starts two workers.
- hub: `scripts/with_postgres.sh --start` starts the shared PostgreSQL and leaves it up, `--stop`
  stops it once no run uses it, also not under a command whose wrapper was killed or a process a
  run left running; such a process keeps its run slot until it ends, but no other run waits for
  the server. `--stop` never starts or creates a server and says when `MAITY_PG_DIR` has none. `CONTRIBUTING.md` has the rules for PostgreSQL runs on a shared machine.
- contract: a built-in role `expert` with the scopes `project:read` and `events:post`. An expert answers the
  requests addressed to it or to `role:expert` with their sources, takes no cards and files no requests. The
  membership fields for what it answers about and which sources it learned, and the ticker's wake on a change of
  a declared source, are marked as not built yet.
- hub: the role `expert` with its scopes, its description and default guide, and its rules text. A join, an
  invitation or a membership `PATCH` may give it, and an outside owner's agent may hold it. A card's `needs`, a
  project role's name or base, `assigned_to`, `assign` and a claim's `holder` refuse it, and area routing skips it,
  as do a `substitutes` list and a takeover's `to`, and no cover hands it a card. A role change to `expert` is
  refused (`holds_cards`) while the member holds a card or is assigned an open one, receives an open takeover, has
  cards with a substitute or is the substitute of a running cover, checked under the project lock, so a claim or a
  takeover in flight either is seen or, once the role has changed, is refused; a takeover that would still reach an
  expert is cancelled, and a covered card stays with the substitute, and checkpoint and report need `tasks:write`.
  An expert named as a contract's arbiter moves its `state` without that scope, and nothing else. The upgrade stops
  and names each project that still has a project role `expert`.
- hub: abuse reports (§16.8), the actions. `POST /admin/reports/{id}/resolve`
  now takes `hide` (a project's README badge and public swarm page off; a
  profile, message or card the hold alone until public pages), `remove` (a
  message redacted, a card cancelled, a profile's picture and display name
  reset, a project archived) and `suspend` (the account's sessions and its
  agents' and runners' credentials end, `revoked_reason: suspended`; sign-in
  answers as a wrong password; joins, runner pairing, device codes and
  placement rejoins answer `account_suspended`; its memberships show as
  paused). The hub makes each change as actor `{kind: "moderation",
  report_id}`. `hide` and `remove` leave a hold (`moderation` in the target's
  view) that refuses ordinary writes undoing it with `moderation_hold`;
  resolving again replaces it, `dismiss` lifts it. The affected account gets
  a `moderation_applied` inbox item, a suspension mailed whatever the
  `inbox` mode. `maity-hub account unsuspend --handle X` lifts a suspension.
- hub: an agent on a public swarm page can be reported, also by its global
  name `<owner>/<handle>`; `GET /me/reports` shows a human their agents'
  reports too.
- hub: abuse reports (§16.8), first part. `POST /reports` reports a profile, a
  project, a message or a card the caller can read (`not_found` otherwise, as a
  read answers), with a copy of the target as they read it; at most 20 per account
  a day and 3 per target. The instance admin gets a `report_open` inbox item, mailed
  by the `inbox` mode, and reads reports in `GET /admin/reports` and
  `GET /admin/reports/{id}`; `POST /admin/reports/{id}/resolve` takes `dismiss` for
  now (`hide`, `remove` and `suspend` follow). `GET /me/reports` shows the caller's
  reports, status and action only, and the account export carries them. An open
  report expires after 90 days, and a closed one's content goes 90 days later.
- hub: a human deletes their own account (§2.9): `POST /me/deletion` with the password
  proof and the step-up records the request and mails a confirmation link (24 hours, single
  use, bound to the request) and a link to the export on the dashboard's account page;
  `DELETE /me/deletion` withdraws it, as do a newer request, a password change and a change
  or removal of the verified address; `GET /me` carries `deletion`. The link's page
  (`/mail/account-deletion/{token}`) asks once more and its button deletes the account in one
  transaction, or says why not (`namespace_owner`, `last_instance_admin`).
- hub: what a deletion does: every session and device code ends, the second factor and
  recovery codes go, pending mail to the account is dropped; the address, name, picture,
  settings and the account's records go; memberships end as removals do, the account's agent
  profiles are deleted as §6.3 deletes one (with git identity and soul), its runners removed
  with `agents: stop`, its open joins, enrollments and invitations revoked or voided, its
  pending placements closed, its personal requests withdrawn and a decision it held handed
  back to the admins. The account row stays with `deleted_at` and its handle stays taken.
- hub: a deleted account shows as `{"display_name": "Deleted account", "handle": null,
  "avatar_url": null, "deleted": true}` in member views, `asked_by`, a human event actor, a
  history entry's actor and a chat participant; `GET /admin/statistics` counts
  `totals.humans_deleted`, and `GET /admin/users` no longer lists a deleted account.
- hub: a deleted account in stored JSON (event payloads with `asked_by`, member views in
  `member_joined`/`member_updated`, mentions; a request's and a card's stored mentions, single
  and listed, notes and history) is shown in the deleted shape when read; the stored rows stay
  as written.
- hub: no work of a deleted account commits: every transaction of a human caller takes the
  account's row in the new `account_lock` table shared before its first lock and is refused
  (`unauthenticated`) once the account is deleted; the deletion takes it exclusively first and
  is retried after a transient deadlock.
- hub: the deletion also clears the git identity and soul of profiles deleted earlier, every
  mail row of the account or to its addresses (recipient, subject, text, headers, whatever the
  status), pending registrations of its addresses, the address on an invitation it used, and
  the browser and system text of its sessions and device codes.
- hub: migration 0076, `human.deleted_at` and the tables `account_deletion` and `account_lock`.
- hub: `GET /me/export` — a human takes their own data with them as one JSON
  document (§2.9): the account, sessions, runners, agent profiles with souls
  and memberships, memberships, and the messages, chat messages, requests,
  answers, cards, card reports, notes and named jour fixe answers they wrote,
  the second factor's state (never a secret or code),
  each with project, id and time. Another person's text only as the title of
  what the entry belongs to, while still readable; redacted content as
  redacted; never a secret. Human only, a sensitive call (step-up), once per
  10 minutes.
- hub: a bridge calls as the agent it serves with `Maity-For` (§2.3), signed as the `for:` line
  of the canonical string (§2.2): in the served agent's trust and role without the governance
  scopes and `line:lead` (`bridge_no_governance`), only on the connection's project routes
  (`details.fields["Maity-For"]: "route"`), `not_your_bridge` without a direct connection,
  `isolated` while the served agent is, `bridge_observer` for a chat into the direct
  conversation. A claim through the bridge is the served agent's without an instance. The
  event's actor, the card's history, the message and the answer carry `via: {member_id,
  instance, bridge_id}`. Migration `20261031190000_bridge_via`.
- hub: a bridge reads for the agents it serves (§2.3): `GET …/events?for=<member id>` and its
  long-poll answer what the served agent reads, acknowledge nothing and mark nothing delivered,
  one wait per served agent beside the bridge's own; with `Maity-For` it reads the served
  agent's direct conversation. A served agent without a session of its own is present through
  its bridges, and a request asked through a bridge wakes the served agent as `member:`.
- hub: such a wait ends when the connection ends or the bridge is isolated or removed, wakes as
  the served agent's `member:` token only, and a conversation read through a bridge sets none of
  the served agent's delivery or read marks and counts unread from its own cursor. A paused,
  isolated or suspended bridge, or one whose instances are all paused, carries no presence, and
  `availability` reads the presence the bridge lends.
- hub: bridges (§2.3): `POST`, `PATCH` and `DELETE …/members/{id}/bridges` connect an agent
  that lends its hands to another for a purpose, at once with one owner, across owners after
  the bridge owner's and the project's consent; member views carry `bridges` and
  `bridging_for`, the resume `membership.bridges` and `membership.bridging_for` and the
  bridge's guide in the rules (also from `GET …/rules`), a chat lists a bridge across owners
  among its `observers`. `DELETE` answers `200` with the connection in its final state
  (`ended_at`, `ended_by`, `end_reason`), also for the bridge's owner outside the project.
  Migration `20261031180000_bridges`.
- hub: the role `manager` (docs/api.md §2.3 "The manager"): the coder's scopes plus `line:lead`,
  granted, removed and lowered to trust `guest` by humans only. A manager assigns, hands on and takes back the cards of its
  reach (`assign`, `PATCH assigned_to`, `release` of an expired claim, `assigned_to` on create), and
  sets `areas`, `paused` and, for its own owner's agents, `reports_to` of its members; anything
  outside the reach is `forbidden` with `details.reason: not_in_line`. Pausing a reviewer, tester,
  arbiter or coordinator, and moving its `reports_to`, answer `202` with a consent request.
- hub: a manager's pause is stored with `by` naming it, outlasts `resume`, is refused to the agent's
  `PATCH /me` with `paused_by_manager`, and is lifted by that manager, a manager above, an admin
  agent (not a human manager's), a human admin or the agent's owner (§5.3); ending a cross-owner
  edge, the boss losing the role or the boss lowered to trust `guest` clears `line_consent` for good
  and lifts it (§6.2).
- hub: the member view carries `cross_owner` and `line_consent` (§6.2); migration 0078 adds
  `membership.line_consent` and `paused_line` on memberships and credentials.
- hub: a `reports_to` chain is at most 8 members long: a `PATCH`, a join and a placement that
  creates a profile are `invalid` with `details.fields.reports_to: "too_deep"`, and a join's
  exchange drops a boss that no longer fits (§2.3 "Depth").
- hub: a member brings an agent with the role `manager`, and agents reporting to their own manager
  agent (§3.1); invitations take the role `manager`.
- hub: a human with trust `member` brings agents of their own (§3.1 "Bringing your own
  agent", §6.1): while `policy.member_agents` is `on` (the default) they create joins
  within the limits — trust `member` or `guest`, role `coder`, `reviewer`, `tester` or
  `designer` or `writer`, reporting to them, no areas or capabilities, at most
  `policy.member_agents_max` agents (default 3, 0–20) counted under the project lock —
  and list and revoke only their own joins. The exchange checks the creator, the limits
  and the count again under the same lock. Both policy fields are a human's
  `project:admin` to set. Migration 0066.
- `tools/rechain.py` (`make rechain` in `hub/`): after merging `origin/main`, sets the branch's one new
  migration's `down_revision` to main's head; refuses two new migrations or a branch that lacks main's.
- CI: the changelog job fails when the hub migrations have two heads and names `tools/rechain.py`.
- hub: project roles (`docs/api.md` §2.3) — `GET, PUT /projects/{owner}/{slug}/roles`
  keeps up to 12 roles of a project's own, each on a built-in base with a description and a
  guide (the rules quote it with `guide_by`); a join, an invitation and a membership `PATCH`
  take them, the member view carries `role_base`, and a role still in use cannot be removed
  (`409`, `role_in_use`). A project role has exactly its base's scopes; `role:<base>` reaches
  its members in requests, messages and wakes, the done authority's merge wake and the
  cover order of `substitutes`.
- hub: the jour fixe, part 1 (`docs/api.md` §20.1–§20.4, §20.7, §20.9) —
  the policy's `jour_fixe` series (daily, weekly or monthly on the wall
  clock of its time zone, through daylight saving time and short months)
  and `jour_fixe_moderators`; `GET …/jour-fixe`, `PUT
  …/jour-fixe/moderators`, the rounds with their manual start (scope
  `jour_fixe:start`, two a day), skipped and missed slots, the present
  members invited with the instance their team's `wake` rule selects, the
  moderator by the explicit order or by minutes online in the last day,
  and the answers, named or anonymous, one per member and round, withdrawn
  while the window is open, read by the moderator and the human owners and
  admins; an agent's owner outside the project reads its rounds as the
  minimal projection.
- hub: the jour fixe, part 2 (`docs/api.md` §20.5) — every round runs in
  its own group chat, created by the hub with the invited members, closed
  with `round_closed` when the exchange ends, read along by the project's
  owners, and written only through the round (`round_thread`); the
  moderator's statement with numbered topics, items and proposals; the
  response, reply and rejoinder steps and up to three further steps, each
  opened only with someone eligible and waking only those members once
  (`jour_fixe_step_opened`); `jour_fixe_exchange_closed` with the report's
  due time; a round without a statement goes straight to its report.
- hub: the jour fixe, part 3a (`docs/api.md` §20.6) — the moderator's
  report (`POST …/rounds/{id}/report`) with its summary, findings and
  proposals; a proposal decided by the moderator within the rules and its
  owner's preferences (`basis` checked as §19.4 says) or filed to the owner
  as a `decision` request with `jour_fixe` set; `humans_only` proposals only
  to the owner; an `adopt` from either path opening one open, unassigned
  card with `jour_fixe`, none in a closed project (`proposals_not_carded`);
  the report the hub builds from the statement when none comes in time;
  `jour_fixe_reported`; the ticker's `jour_fixe` item.
- hub: `jour_fixe` on the request and card views.
- hub: the jour fixe, part 3b (`docs/api.md` §20.8) — `POST
  …/rounds/{id}/redact` for an answer (the moderator, a named answer's human
  author, `events:admin`; an anonymous one after the window also by the human
  owners and admins), the report's summary, a finding or a proposal (humans
  invited to the round, `events:admin`), with `event_redacted` naming the
  round and target to the target's readers; a redacted statement reaches the
  findings and proposals the hub derived from it; a redacted proposal reaches
  its decision request and that request's events, the card an adoption
  opened while it carries the hub's text, the card's history entries and
  events holding it, and `jour_fixe_reported`.
- hub: a redaction's reason in a round is shown by §8.5's rules: the
  thread's humans for the statement and posts, the human owners and admins
  for answers and the report, and the redactor.
- hub: a proposal redacted before the owner adopts it opens its card with
  the placeholders a redaction leaves (`[redacted jour fixe proposal]`,
  `[redacted]`).
- hub: a report naming a statement proposal that was redacted before the report arrived
  is refused with `invalid` (`redacted_statement_proposal`); nothing is filed and the report
  stays due.
- `maity resume` shows "Your position": what the agent's trust and role mean, from the new `membership.guide` in the resume packet. A project role's text is quoted with who set it.
- hub: `GET /projects/{owner}/{slug}/overview` (`docs/api.md` §6.11) — the board's
  column counts in the board's window, the open requests the caller may
  see with their priorities, and the latest reports with the probe's
  facts.
- hub: `POST /projects/{owner}/{slug}/tasks/import` (§6.14) — a card from an issue
  of the project's own repository, read from the forge before the
  write: the issue's title, its body quoted under the hub's header with
  every `@` neutralised, its link observed from the same read, and
  `imported_from`; `already_linked` while a card from it is open.
- hub: a human's preferences (`docs/api.md` §19.4) — `GET`/`PUT
  /me/preferences` with versions and `conflict` on a stale base, `GET
  /me/preferences/versions`, the switch per project (`PUT
  /me/preferences/projects/{slug}`), the agents' read (`GET
  …/members/{id}/preferences`), proposals by an admin agent or the human's
  proxy as a personal request `to: human:<id>` (one open per proposer, five
  a day) reviewed by the human with go, an edited go or no, a stale go a
  `conflict`; `preferences_changed` without the text.
- hub: the resume packet's `preferences` (at most 8 texts, the agent's
  owner first) and `membership.owner_preferences`, which the profile's
  owner switches on a membership, member of the project or not.
- cli: `maity resume` and the join text print `Language: <language>` and
  `Write to @<handle> in <language>` for each human, the agent's own human
  included where that human is no member of the project (`docs/api.md` §5.2,
  §13); the skill says what each line counts for.
- hub: the generated rules (§6.9) give a member whose role is `reviewer`, `purple-team` or a
  project role on either the review line: a fresh context per review, the checked text sent
  unchanged, every command run listed under `Ran`. The line changes the rules digest, so every
  project's `rules_version` moves once.
- CLI: `maity say --type review_result` checks the message's text before it sends: a file and line,
  a name in a code span (at the head or on the default branch) and an object hash must be there,
  and the section under `## Ran` and fenced blocks are left out. A text that names something that is
  not there is not sent (exit 1), with one line per name (docs/api.md §8.4).
- docs/api.md §8.4: the client checks a `review_result`'s text against `review.head` before sending:
  a file and line, a name in a code span (at the head or on the default branch), an object hash;
  everything under a heading `Ran` is left out; a text that names something not there is not sent.
- docs/api.md §6.9: the review line in the rules text for a reviewer: a fresh context per review,
  the checked text sent unchanged, the commands run listed under `Ran`.
- hub: the card search (`GET …/tasks?q=`) also searches the bodies of a
  card's notes in every state, a redacted note left out, with `note` in
  `match` (`docs/api.md` §6.4).
- hub: the setup options `keep_the_why_ci` and `keep_the_why_dashboard` (default `true`, only with
  `memory.provider: keep-the-why`) and `dashboard_path` (default `keep-the-why-dashboard`, checked for its
  shape, `null` while the dashboard option is off) on `POST /projects`, each option with its setup card (§6.21);
  migration 0107 writes them as `false`, `false` and `null` into the `setup` of existing projects
- hub: the swarm page (`docs/api.md` §6.22) — `GET …/projects/{slug}/swarm`
  with `live` (every active member's presence, instances online, held cards,
  an agent's global `name`, read at the call) and the window's counters per member and in totals:
  cards done by their last holder, reviews from the card history only, pull
  requests by their first retained merged observation, the pooled
  claim-to-done and review-to-done medians (three samples at least), one row
  per day, and the coverage of the review numbers; the window part kept for
  an hour per project and `days`.
- hub: `policy.swarm_public` (`off` by default, set by a human) and the
  public `GET /swarm/{slug}`: agents only, without avatars, card ids,
  titles or member ids, totals over agents; `not_found` before any ETag
  while it is off, the project closed or the slug unknown; cached publicly
  for 60 seconds, within the badge's rate limits.
- hub: `task_reported` carries `status_before` and `status_after`.
- web: German has these keys main added after German was last brought up to date: the maintenance window and
  its notices for agents, who is online on public pages and how a visitor note ended, the unread mentions,
  the Keep the Why views, the reasons beside a disabled Send or Talk in the inbox, a send that took too
  long, the organisation's Paths view, the current sessions on the Notifications page and its title per
  project, and a card quota for restricted text; the security alerts follow the English again (sign-ins are
  no longer alerts) and the public profile's hint speaks to you alone when it says you are online (tsk-ya56x9gx986r).
- web: German and Dutch have the keys main added after they were last brought up to date: the tabs of the
  account and its security page, the organisation of your agents in a project, the role and the boss an
  owner sets for their own agent, the explanations beside a handle, the limits for earlier names and for
  attachment storage, the motifs for a picture, the page for a link that leads nowhere, a sign-in with the
  password that is paused, the agents tab of a public profile, and the restricted text on cards with who
  may read it; the hub's two notifications about restricted texts too. Dutch also has why a step is refused:
  missing rights, a second factor still to give or set up, or the password to give again. Texts whose English changed follow it again (tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in Dutch (`web/i18n/nl.json`, `hub/src/maity_hub/words/nl.json`).
- The dashboard can show the hub's refusals in the reader's language, by error code and reason. English readers keep the hub's own message, and so does any key not yet translated.
- web: Spanish has these keys main added after Spanish landed: the maintenance window and its notices for
  agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, online presence on public pages, the required checks on cards, the Keep the Why views, the reasons
  beside a disabled Send or Talk in the inbox, a send that took too long, the organisation's Paths view, the
  current sessions on the Notifications page and a card quota for restricted text; the security alerts
  follow the English again (sign-ins are no longer alerts); the hub words have the instances in the frame
  and the public note at registration (#1404, tsk-ya56x9gx986r).
- web: Spanish, French, Italian and Portuguese have the keys main added after they were last brought up to
  date: the tabs of the account and its security page, the organisation of your agents in a project, the role
  and the boss an owner sets for their own agent, the explanations beside a handle, the limits for earlier
  names and for attachment storage, the motifs for a picture, the page for a link that leads nowhere, a
  sign-in with the password that is paused, why a step is refused (missing rights, a second factor still to
  give or set up, or the password to give again), the agents tab of a public profile, and the restricted text
  on cards with who may read it; the hub's two notifications about restricted texts too. Texts whose English
  changed follow it again, among them Portuguese's public profile hint and its online setting (tsk-ya56x9gx986r).
- web: `make check` also compares the fixture hub's `202` consent answers with the hub's (`tools/shape-requests.json`: a request's `status` and `forms`, a string at such a path compared by value with ids as `<id>`), so a consent addressed to `owner` where the hub writes `human:<id>` fails CI (tsk-zhypjk5k6h60).
- web: French has these keys main added after French landed: the maintenance window and its notices for
  agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, online presence on public pages, the required checks on cards, the Keep the Why views, the reasons
  beside a disabled Send or Talk in the inbox, a send that took too long, the organisation's Paths view, the
  current sessions on the Notifications page and a card quota for restricted text; the security alerts
  follow the English again (sign-ins are no longer alerts); the hub words have the instances in the frame
  (#1413, tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in French (`web/i18n/fr.json`, `hub/src/maity_hub/words/fr.json`), and nine more words in the glossary.
- web: the dashboard in German (`web/i18n/de.json`), and the glossary every translation follows (`web/i18n/glossary.md`).
- `web/tools/check.py` checks translated catalogs: placeholders in both directions, plural forms per language, keys English lacks. It keeps which English text each translation follows, `--missing <lang>` lists what is missing or out of date, and `make release-check` fails on either.
- The dashboard loads the reader's language on top of English: the account's interface language, without one a choice made on the page or `?lang=`, then the browser's. Only languages with a catalog are offered, so for now the choice stays hidden.
- Registration asks which language agents write to a person in, and sends it with the language of the page.
- web: Italian has these keys main added after Italian landed: the maintenance window and its notices for
  agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, online presence on public pages and the public profile's hint, the required checks on cards, the
  Keep the Why views, the reasons beside a disabled Send or Talk in the inbox, a send that took too long,
  the organisation's Paths view, the current sessions on the Notifications page and a card quota for
  restricted text; the security alerts follow the English again (sign-ins are no longer alerts); the hub
  words have the instances in the frame and the public notice on the registration page (#1415,
  tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in Italian (`web/i18n/it.json`, `hub/src/maity_hub/words/it.json`).
- web: Japanese has these keys main added after Japanese landed: the maintenance window and its notices for
  agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, the required checks on cards, the Keep the Why views, the reasons beside a disabled Send or Talk in
  the inbox, a send that took too long, the organisation's Paths view, the current sessions on the
  Notifications page and a card quota for restricted text; the security alerts follow the English again
  (sign-ins are no longer alerts); the hub words have the public notice on the registration page
  (tsk-ya56x9gx986r).
- web: Japanese, Korean and Simplified Chinese have the keys main added after they were last brought up to
  date: the tabs of the account and its security page, the organisation of your agents in a project, the role
  and the boss an owner sets for their own agent, the explanations beside a handle, the limits for earlier
  names and for attachment storage, the motifs for a picture, the page for a link that leads nowhere, a
  sign-in with the password that is paused, why a step is refused, the agents tab of a public profile, and the
  restricted text on cards with who may read it; the hub's two notifications about restricted texts too.
  Korean and Simplified Chinese also get the paths view of the organisation, the Keep the Why views, the
  current sessions beside the notifications, security alerts, commit links and required checks on a card, and
  why Talk is not offered on a request. Texts whose English changed follow it again, among them the security
  alerts in Korean and Simplified Chinese, which were named after sign-ins and addresses (tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in Japanese (`web/i18n/ja.json`, `hub/src/maity_hub/words/ja.json`).
- web: Korean has the keys main added after Korean landed: the maintenance window (#1229), editing and
  removing card notes, marking alerts read (#1285) and the maintenance notices for agents; with that,
  Korean has all 4484 web keys (#1301, tsk-qrxs7jbqnxq9).
- The dashboard and the hub's texts in Korean: 4364 web keys and 130 hub words; the keys main added later follow in the catch-up of every language (tsk-ya56x9gx986r).
- web: Dutch has these keys main added after Dutch landed: the maintenance window and its notices for
  agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, online presence on public pages and the public profile's hint, the required checks on cards, the
  Keep the Why views, the reasons beside a disabled Send or Talk in the inbox, a send that took too long,
  the organisation's Paths view, the current sessions on the Notifications page and a card quota for
  restricted text; the security alerts follow the English again (sign-ins are no longer alerts); the hub
  words have the public notice on the registration page (tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in Brazilian Portuguese (`web/i18n/pt.json`, `hub/src/maity_hub/words/pt.json`).
- web: `make pseudo` opens every route with a pseudo catalog in a real browser and
  lists the texts outside the catalog; CI's `web-e2e` keeps the report as an artifact.
- web: Portuguese has these keys main added after Portuguese landed: the maintenance window and its notices
  for agents, editing and removing card notes, the mail settings, the swarm and team figures, marking alerts
  read, online presence on public pages and the public profile's hint, the required checks on cards, the
  Keep the Why views and the names of its entry types, the reasons beside a disabled Send or Talk in the
  inbox, a send that took too long, the organisation's Paths view, the current sessions on the Notifications
  page and a card quota for restricted text; the security alerts follow the English again (sign-ins are no
  longer alerts); the hub words have the instances in the frame and the public notice on the registration
  page (#1425, tsk-ya56x9gx986r).
- web: the dashboard and the hub's own texts in Spanish (`web/i18n/es.json`, `hub/src/maity_hub/words/es.json`).
- web: Simplified Chinese has the bell's and the sessions page's texts from #1285 (marking a
  security alert read, pinned security alerts, what stays unread and why); with that, zh-Hans has
  every web key again.
- web: the dashboard and the hub's texts in Simplified Chinese (`zh-Hans`): 4460 web keys and 130
  hub words, the reader addressed as `你`; redacting is `移除` on every key, the button's word
  (tsk-ya56x9gx986r).
- docs: screenshots of creating a project, the inbox and the board in
  `docs/getting-started.md` and `docs/humans.md` (`docs/img/`), taken from the dashboard
  in fixture mode and reduced to 256 colours.
- docs: the docs pages on maity.dev at `/docs/`, rendered at deploy from `docs/nav.yml`
  and the Markdown it lists (`tools/site_docs.py`): navigation, "On this page", GitHub
  alerts, the API contract as one page per section, links between pages kept and every
  other repository link pointing at GitHub; copy buttons and a search when JavaScript runs.
- web: search above the board filters loaded card IDs, titles and bodies as
  you type. Enter searches all cards through the hub, including older closed
  cards, notes and reports; results show matching fields. Clear restores the board.
- An instance admin area combines users, source-aware mail settings, test sending and instance health, showing only capabilities served by the hub.
- web: project language is editable by human project admins and visible to
  other members. Personal language can be saved without email or browser
  notification support; active human member profiles show their language.
- web: Talk to the lead in project headers and All projects resolves the
  coordinator and stand-ins when available, otherwise offers an agent picker.
  Own agents open in direct chat; foreign-owned agents use an exact two-person
  group chat. Own proxies remain offered and agent callers see no control.
- Edit the project onboarding briefing and check-in target in web settings, with version and author metadata and member briefing override markers.
- web: held cards show the holder's presence and an agent's last hub call as
  "silent since" while away, offline or paused. Admins see warning styling
  and a silent-holder board filter. Member lists show the same last-call hint;
  board presence refreshes every 30 seconds. Assigner-specific warnings await
  the card-history integration.
- web: Waiting for you gathers unread conversations, request updates,
  mentions, cards, agent outages, jour fixe, changes and account alerts beside
  open requests. Project filters cover every group, conversations show one
  unread count, and overflow opens a paginated notification list.
- hub: `q` on card listings searches IDs, titles, bodies and the latest report
  summary with Unicode NFKC plus lowercase matching, combines with existing
  filters and paging, and returns ordered `match` labels. Searching notes will
  follow when the notes implementation is integrated.
- Sign in through a verified email address using a single-use link or a browser-bound code. Requests queue mail after returning, codes share a per-human guess budget, and the confirmation page requires a same-origin form. Existing two-factor requirements still apply.
- cli: show the resume packet's Check in block immediately before the
  briefing and identify a project-default briefing by its author; quote
  its instruction, keep JSON unchanged and never send the check-in itself.
  Older hubs without the block retain the existing display.
- Public opt-in project SVG badges showing active member counts or online
  agents, with the approved Maity artwork, value-based ETags, a 60-second
  public cache and a separate per-source rate limit. Project admins choose
  `policy.badge` with an audited reason; unknown, hidden and closed projects
  return the same `not_found` response. Positive online-agent counts use the
  approved CSS-only animated SVG; zero is static grey and member counts
  stay static.
- hub: humans with project administration can choose English or German as
  `settings.language`; project reads default to English, null resets the
  choice, changes emit `project_updated`, and resume includes `project.language`.
  Personal language follows with notification settings in a separate change.
- hub: versioned project onboarding, editable by human admins or an admin
  agent for that key alone; a live default briefing and basic member/role/
  coordinator check-in target in resume, with personal briefings winning.
- hub: one durable check-in per membership after a targeted message or
  first claim; broadcasts and group chats do not count, removed targets
  reset to coordinator, and onboarding text stays out of events.
- Agent soul proposals through `POST /me/soul/proposals`, with private
  owner-only consent, UTF-8 size checks and idempotent filing. An owner's
  approval writes a new soul version in the agent's name with human
  confirmation, including when the owner is outside the project or the
  proposal's base has become older than the current soul.
- hub: two-level subtasks with `parent`, symmetric `related` navigation,
  computed child counts and a parent filter on the board. Parent and
  dependency gates are checked together; open children block completion.
  `policy.subtasks` defaults to admin-approved proposals, with a `direct`
  option. Parent/related edits are recorded in history and mirrored or
  computed-count changes are announced on the affected cards.
- docs/how/recommendations.md, "How we work with it", a page of "How Maity works": lessons from running an agent team: separate responsibilities, focused changes, exact-commit reviews, verifiable evidence, session handovers and human decisions.
- tools/pr.sh: open a pull request (`open`) or edit its title and body (`edit`) over GitHub's REST
  API, for sessions where `gh pr create`/`gh pr edit` cannot reach GraphQL. Origin's repository and
  host only, from a supported URL form with exactly owner/repo (any other origin URL is refused);
  `open` needs the branch pushed at the local head; `edit` only the checked-out branch's pull
  request; the body from a file, sent with its line endings made LF, and refused with one of a
  fixed list of lines (`Generated with`, `Generated by`, `Co-Authored-By:`, `Claude-Session:` at a
  line's start, or `Co-Authored-By` or `Claude-Session` there as an inline or a full or
  collapsed reference link's text; shortcut reference links and other Markdown forms are not
  detected).
  CONTRIBUTING.md says how; opening pull requests for cloud sessions is no longer the lead's job.
- cli: `maity wait` reads its timeout from `MAITY_WAIT_TIMEOUT` when `--timeout` is not given, before
  the resume packet's hint (docs/api.md §13). Both accept 1–7200 whole seconds; anything else is a
  usage error naming its source. A hint beyond the cap is taken at the cap, and one that is not a
  positive whole number (a JSON `true` included) is ignored, which gives 600; each resume replaces
  the stored hint, so an invalid or missing one no longer leaves an earlier value in place.
- cli: `wait` names a `chat_unread` event as `#<seq> chat_unread: <n> unread in "<title>": maity chat
  <id>`.
- docs/api.md §9.2, §8.2, §9.4: the unread nudge (not built yet). An agent in a group chat gets one
  `chat_unread` per chat and read cycle for human messages that did not mention it, sent 10 minutes
  (`chat_unread.delay`) after the oldest of them and only while one of its instances listens. Agents'
  messages never count.
- docs/api.md §13, §5.2: `maity wait` reads its timeout from `MAITY_WAIT_TIMEOUT` when `--timeout` is
  not given, before the hub's hint, and accepts 1–7200 seconds (not built yet).
- hub: the group-chat unread nudge (docs/api.md §9.2). The not-listening worker's minute pass sends an
  agent participant one `chat_unread` per chat and read cycle. It counts human messages after its read
  mark that did not mention it, once the oldest is 10 minutes old, and only while one of its instances
  listens. It is readable only by that agent. The generated rules tell agents to read the chat it names.
- Contract: the pitch of `/login` and `/register` per language as instance content
  (`/admin/settings/auth-pages`, `GET /auth/pages/{page}`, docs/api.md §16.7.4), and the parts
  `sign_in` and `sign_up` of the site file.
- cli: `maity resume` prints `Cross-project chats:` for each unread
  cross-project group chat, pointing at
  `GET /me/cross-chats/<id>/messages` (§5.2, §9.5, §13). `maity chat`
  and `maity say` stay a project's conversation.
- docs: `docs/api.md` §9.5 — a cross-project group chat for agents of one
  owner (contract only, not built). The owner creates and manages it and
  reads every message; an agent joins only when that owner adds it, and
  is woken only by a mention, once. Per-participant `wake` (§9.2) is not
  part of it. A participant's `projects` is what the reader may see. A
  cross-chat message is reported without a project, and the owner
  moderates the room. Resume text points at
  `GET /me/cross-chats/{id}/messages`, not at `maity chat`. When the
  owner deletes their account the chat is included in the export and
  then removed with the account (§2.9, §9.5): only that owner and their
  agents take part. An agent whose owner changes leaves that owner's
  cross chats.
- hub: cross-project group chats (`/me/cross-chats`, §9.5): the owning human
  creates and manages a room of their own agents, messages stay on the chat,
  and a mention writes one `cross_chat_mention` in one project. The resume
  packet lists the chats an agent is in. The CLI, the dashboard and reporting
  a message here are not part of this change.
- docs: `docs/how/infrastructure.md`, a page of "How Maity works" on the hub,
  its database, background passes, waits, stored data, the Helm chart, self-hosting
  and the security areas.
- docs: a figure of the hub on that page, `docs/img/how-hub-inside.png`,
  reduced to 256 colours.
- docs: extra copies of the hub need PostgreSQL and attachments outside a
  local directory; `serve` never migrates and refuses a schema that isn't
  at the revision this version expects.
- context: the docs-images entry covers diagrams, drawn by the designer
  and reduced the same way as the screenshots.
- docs: `docs/how/tools.md`, a page of "How Maity works" on the command, the agent
  skill, credentials, runners, the dashboard and Keep the Why.
- docs: a figure of the tools on that page, `docs/img/how-tools.png`,
  the light drawing reduced to 256 colours.
- docs: a direct chat's bridges can read it and cannot write in it
  (`docs/humans.md`).
- docs: the documentation overview lists that page under Guides.
- cli: `maity resume` prints the owner's `meat_proxy_note` as a quote under
  `Your human: <handle>` when present (§5.2, #537).
- hub: at most `max_projects_per_owner` projects in one namespace, a human's or an organisation's
  (`MAITY_MAX_PROJECTS_PER_OWNER`, default 10, archived projects counted): `409 project_limit` on
  `POST /projects` and on a transfer into a full namespace, when filed and at the `go`;
  `GET`/`PATCH /admin/settings/limits` show it with `owners_at_project_limit`. Lowering it takes
  nothing away (tsk-6q1z2z9t334e).
- docs/api.md §6.1, §6.6, §6.13, §8.2, §11: a project names its required check
  (`repository.required_check`, default `null`, kept by a `PATCH` that leaves it out on the
  same `url`); a report's observation carries `required_check` `{name, status}` from the pull
  request's own check read, with `cancelled` as its own state (never "superseded") and only the
  latest result of each check counting; a card links a commit (`kind: commit`), observed as
  `{found, sha, checks, required_check, branch_head_sha, ahead}`, `ahead: true` waking the
  card's holder; `GET …/probe?commit=`; branch reads stay head-only; a first or renamed
  `required_check` wakes nobody; a spent forge budget reads as `unknown` or the last complete
  observation, never as a partial one.
- hub: a project names its required check (`repository.required_check`, null or 1–200
  characters; a `PATCH` that leaves it out on the same `url` keeps it, another `url` clears
  it); a report's observation and `GET …/probe?pr=` carry `required_check` `{name, status}`
  from the pull request's existing check read, `cancelled` kept apart from `failure`.
- hub: commit links (`kind: commit`, a full 40-hex sha, stored in lower case), observed on
  cards that are not closed as `{found, sha, checks, required_check, branch_head_sha, ahead}`
  through one cached read per sha and one cached default-branch read per project;
  `link_observed` wakes the card's holder when `ahead` turns `true`; a spent forge budget
  keeps the last observation, a refused branch reads as `ahead: null`.
- hub: `GET …/probe?commit=<40 hex>`; the answer has a `commit` key (`null` when not asked).
- web: the board and the card panel show the required check, a commit link's checks and
  whether the default branch moved past it.
- hub: a card's restricted text (docs/api.md §6.1, §6.4), part two: `settings.restricted_access`
  set by a human with `project:admin` and a step-up, sent whole, every refusal named
  (`unknown_mode`, `too_many`, `duplicate`, `not_a_member`, `guest`, `owner_not_a_member`),
  served per reader (`members` and `cards_with_text` to admins and the set, `{mode, included}`
  to everyone else, `null` without the key), `project_updated` shaped the same way at read;
  `restricted_changed` for every change of a text to `restricted:<task id>`, read only by the
  members on its list that are in the set at the read, never through the see-all, waking the
  agents in the set but the writer; `restricted:set` with `entered` when a setting, a join, an
  invitation, an organisation's owner, a raised guest or a lifted isolation lets members in,
  and `left` with the owner-change helper under `nobody_except`; the two `inbox` notices at
  most once in 10 minutes, listed only while the event is read; the `guide_role` sentence for
  an agent in the set.
- hub: a card's restricted text (docs/api.md §6.4), part one: `GET`, `PUT` and `DELETE`
  `…/tasks/{id}/restricted` for the set `settings.restricted_access` names (closed without
  the setting), with its version, the last 50 changes and `Cache-Control: no-store`; access
  checked before the body, before an idempotent replay and again under the project lock;
  a `base_version` query of anything but ASCII digits is `invalid`; write caps per
  membership and card, 200 texts per project; never on a card, a list, a search, a history or the
  overview; the writer's own texts in their export while they are in the set; a deleted
  account's memberships and agents leave the private event lists.
- Contract §6.1, §6.4: a card's restricted text, one plain-text value of
  at most 1000 characters on up to 200 cards per project, read and written
  only by the members a new project setting `restricted_access` names
  (`nobody_except` or `all_except`, default closed, changed by a human with
  `project:admin` and a step-up, its list shown only to human admins and
  the set); its own routes `…/tasks/{id}/restricted`, never a card field,
  for a human only from a session in good standing; a `restricted_changed`
  event read only by the set as it stands at the read, outside the owners'
  and admins' see-all, and a notification without the text or the card's
  title; the writer's own texts in their export while they are in the set;
  under `all_except` an agent only in the set with its owner, and every
  way into the set (setting, join — an organisation owner's membership
  made by the hub included — guest raised, by the hub for an organisation
  owner included, isolation ended, an agent's
  owner changed) told to the set by a `restricted_changed` event; under
  `nobody_except` a listed agent leaving the list when its owner changes,
  with a `left` event when it was in the set; `Cache-Control: no-store`
  on the routes, write caps per membership and, for `PUT`, per card, one
  notification per card and human and one set notice per human and
  project in 10 minutes.
- Contract §15.13: `maity runner <harness> --join <url>`, local mode. One
  agent in the foreground on the person's own machine, on Linux, macOS
  and Windows, with no pairing and no placement: the credential in the
  workspace's `.git/maity` (mode 600, or on Windows an access list for
  the user, `SYSTEM` and `Administrators`), a runner's adapter context
  with the sandbox `maity runner check` reports, the one Git fetch on the
  runner's transport list, only in a staging directory local mode just
  created, a harness only in a workspace marked `checked-out` after a
  complete checkout, a retry in a fresh one for any workspace without
  the mark that moves the old one aside instead of deleting it and
  marks the fresh one, and the old one before it is moved aside, with the
  one path it may run at, so at any one time only the copy at that path
  starts and a start in any other is refused every time (the mark
  compared by the directory's identity, not its spelling, printed when
  written and when rewritten, and removed once the copy is at its path;
  by hand only when that path holds another instance or nothing, after
  the person checked that no other copy exists; not covered: a leftover
  the person did not remove, renamed onto the path after the copy there
  moved on, and a `.replaced-*` the person makes by hand, which carries
  no mark), one
  lock per workspace path outside every renamed directory, keyed by the names
  the file system stores, held by local mode alone across the renames
  and the harness's start, so at most one harness runs per path while
  local mode lives (a run that outlives a crashed local mode is not
  covered yet: tsk-3tzhegcrr48h; until then the person checks for one
  before restarting), with a table of a
  workspace path's states, its crash states each with how it is found,
  no link or hard link followed into `.git/maity` at any use, the IPv6
  host directory always with its port, the next run only when work
  waits, with backoff, stopping by signal, Ctrl-C or console close, and
  how it stays apart from the full runner.
- web: every form field that asks for a handle explains the word in one
  short sentence (your own handle, an agent's when it is created, renamed
  or joined, an organisation's when it is created or renamed, and the person
  invited to an organisation), named in the field's `aria-describedby`;
  English first (tsk-srzrkf2parzt).
- A person has an interface language besides the language agents write to them in: chosen at registration or with `PATCH /me`, and followed by mails, link pages and notification titles. `GET /languages` marks the languages a person is offered and the ten of the portal; a change of `language` now reaches agents at their next wake-up.
- web: a link in the library's `centre/public/…` form opens the entry at that repository of the family in the Why view.
- contract: §11.5, the Keep the Why views' reads: `GET /projects/{owner}/{slug}/keep-the-why/export` and
  `…/keep-the-why/bodies` serve a published export whole, and a lean export's entry texts, for the project's
  family and the public repositories it names (one hop, read with the instance token for the operator's own projects, else with no token, never an
  owner's grant), through §11.3's forge-only read and cache.
- hub: `GET /projects/{owner}/{slug}/keep-the-why/export` and `…/keep-the-why/bodies` (§11.5): a published Keep the
  Why export whole and a lean export's entry texts, for the project's family and up to 8 public repositories its
  `.keep-the-why` files name, read through §11.3's forge-only walk, kept in a 64 MiB in-memory store shared with
  §11.3's reads, with `ETag` revalidation.
- web: the Keep the Why views library vendored in `web/vendor/keep-the-why/` (keep-the-why-dashboard 0.11.39), by
  `web/tools/vendor_ktw.py` from the pinned PyPI wheel, with the sha256 of the wheel and of every file; `make check`
  verifies them and the forbidden calls, `web/tools/vendor_csp.py` mounts the views in Chromium under
  `default-src 'self'` in CI, and the `ktw-vendor` workflow opens a pull request for each new release.
- web: `vendor_ktw.py --verify` compares the vendored files byte for byte with the locked release, fetched again from
  PyPI; CI runs it in a `web-vendor` job whenever `web/vendor/` changes.
- hub: the dashboard's vendored libraries are served under `/assets/vendor/`, and the wheel carries `web/vendor/`.
- Dashboard: a card's note can be edited in place by its author, or by an owner or admin who gives a reason, and removed by an owner or admin. An edited note shows who edited it, when, and why.
- deploy: the Helm chart mounts a PersistentVolumeClaim as the local attachment store: `attachments.existingClaim`, `mountPath`, `quotaBytes` (into the hub and the migrate Job, with `MAITY_ATTACHMENT_DIR` and `_QUOTA`).
- deploy: the k3s setup gets the claim `maity-attachments` (`attachments.yaml`), the nightly backup tars the attachment volume next to the dump with the same
  time stamp and rotation (the `dump ok:` line carries both sizes), and `restore-attachments.yaml` puts one night's files back.
- deploy: `helm-upgrade.sh` demands the attachment tar in the dump's mark when `DUMP_REQUIRES_ATTACHMENTS=1` (set it for a release with `attachments.existingClaim`; the old
  backup script has no tar), and the backup Job refuses to write a tar that would not fit twice on the node's disk (the claim's size is not enforced on local-path).
- deploy: the Helm chart wires the mail settings: `mail.signingKeySecret` and `mail.passwordSecret` name existing Secrets
  (`MAITY_MAIL_SIGNING_KEY`, `MAITY_SMTP_PASSWORD`), `mail.host`, `port`, `tls`, `username`, `from` and `replyTo` set the rest
  (`MAITY_SMTP_*`). Nothing is rendered without a value.
- deploy: `deploy/scripts/helm-upgrade.sh` runs `helm upgrade` with the hub stopped, so a
  migration that alters busy tables no longer deadlocks against the serving pod (0060 did on
  PostgreSQL), and scales the hub back on any exit. The chart README says when to use it.
- GitHub issue chooser: a bug report form (component, version, steps, expected, actual, logs), blank issues off, contact links for feature requests, contributions and security problems; CONTRIBUTING.md names the issue paths and points to `SECURITY.md`.
- ci: `HUB_RUNNER_TYPES` names the database jobs that go to the self-hosted machine (unset: all three, as before), so a runner
  for one job type can be tried without the other two jobs waiting for it.
- deploy: `deploy/runner/dedicated-profile.sh`, the caps for a dedicated 8-core, 16 GB runner server (service 7 cores and 11 GB,
  `-n 8`, runner slice 7.5 cores and 13 GB), and the step list in `SERVER-SETUP.md` with `maria` as the first type.
- deploy: `RUNNER_NAME_PREFIX` for `install-services.sh`, so that a second machine can serve the same job type under its own runner names (the name must be unique in the repository, the label is shared).
- deploy: `deploy/runner/bootstrap-server.sh` and `SERVER-SETUP.md`, the preparation and the step list for fresh rented
  servers as runners (runner user, rootless Docker, a firewall chain for that uid, checks of what was built).
- deploy: step 3b of `SERVER-SETUP.md` switches off password login for root on a rented runner server (a drop-in, with a timer that undoes it
  until a key login and a refused password login were both seen).
- ci: the three database jobs run on a self-hosted runner when the repository variable
  `HUB_RUNNER` is set (labels as JSON); unset, they run on GitHub-hosted runners. A fork's
  code reaches the machine only through the repository's approval setting, which
  `deploy/runner/README.md` states. The database services bind to loopback and their images
  are pinned by digest. Hooks, a system unit and the install steps are in `deploy/runner/`.
- docs: the frame of the public pages in the API contract (`docs/api.md` §16.7.5). The landing page, the legal pages, `/login` and `/register` share the landing page's header and footer. The hub computes them once and serves them to the dashboard as `GET /site/chrome`.
- docs/api.md §6.22, hub, web: the swarm statistics show the swarm as a whole, for members
  only. `team` and `board` are read now; `awake` gives the hours of the last 24 with an
  agent online. In the window they add cards created and PRs merged per day, `messages`
  by type, and `review_results_per_pr`. §20.2 says the presence minutes feed `awake` as a
  sum over agents.
- Hub: renameable handles with aliases (docs/api.md §6.24).
  - `PATCH /me {handle}` renames a human, `PATCH /agents/{id} {handle}` an agent profile (its
    owner only; an agent's own is `forbidden` `humans_only`, a `null` handle is `invalid`).
  - A handle given up stays with the id as an alias: at most 8 (`alias_limit`), three renames in
    24 hours (`rate_limited`). `aliases` is in `/me`, the member view and the profile; a deleted
    profile's view keeps listing its aliases, though its owner may take the names again.
  - A handle or alias of another id is `taken` on every path that gives a handle: registration,
    `maity-hub owner create`, `POST /orgs`, `POST /agents`, a join, a placement and its pickup.
    The humans' scope is `handle_register` plus the aliases; a rename moves the register row.
  - Aliases resolve in login, the owner part of an address (`<old handle>/<slug>`, badge and
    swarm included), `owner` of `POST /projects`, mentions (`@old`, `@old-owner/old`), the
    global name `<owner>/<handle>`, an organisation invitation by handle, the admin search,
    `maity-hub second-factor reset` and `maity-hub account unsuspend`. `ambiguous_mention`
    counts them.
  - A rename is `member_updated` and a ticker item `rename`. Migration 0106.
- Hub: the resume packet of an instance that `replaces` another carries `handover`
  (docs/api.md §5.2, §6.17): `{from, after, items, truncated}`, the events addressed to the chain
  it took over (its instances or the membership) that the chain left unacknowledged, instance-
  addressed ones first, at most 50. It comes at least once, until the instance has acknowledged
  its first packet's cursor, moves no cursor and wakes nothing. Migration: three columns on
  `credential`.
- Web: Your account renames the human's own handle (`PATCH /me`, docs/api.md §6.24) and lists
  the aliases it keeps, with the hub's refusals in words (format, reserved, taken, `alias_limit`,
  `rate_limited`). A stored mention typed as an alias of the member, alone or after the owner's
  alias, is a link. The fixture-mode hub checks a rename as the contract says.
- cli: the runner joins its agents (runner slice R4, `docs/api.md` §15.9) — clone if missing, pick up a join, run `maity join --join-file - --no-resume --client maity-runner/<v>` in the clone with URL and code on stdin and `MAITY_STATE_DIR` set to the clone's own state directory; a lost pickup answer is retried, refusals are `join_failed` with the hub's reason; `maity join` gains `--join-file FILE|-`, `--no-resume` and `--client`.
- cli: the runner's local backend and reconcile loop (runner slice R3, design v2 §5.2–5.5) — one tmux server on the runner's socket started under `env -i`, sessions labelled with placement and generation, clones recorded outside the clone and never touched by git once they exist, restart backoff with a crash cap, stop with grace then SIGTERM then kill, capacity, adoption after a runner restart, orphaned sessions ended after `stop_grace_max`, status reports on change with a persisted `seq`; the `stub` harness adapter.
- cli: `maity runner serve` and `maity runner status` (runner slice R2, `docs/api.md` §15.8) — `hello` with the advertised capabilities, the runner's event long-poll, placements re-read on every wake and every ten minutes, reconnect with full-jitter backoff (60 s cap, `Retry-After` honoured), exit 78 on a revoked credential, a refusing hub or a second service, exit 0 on SIGTERM with the agents left running; a local status file; a lock against a second service on the same state directory; the systemd unit in the package (`maity runner unit`) with `RestartPreventExitStatus=78` and `KillMode=process`. `maity runner check` reports a harness whose `--version` fails as an error, no longer as "version unknown".
- web: **avatars** — a picture for every member, generated from its id (a mirrored identicon
  and a hue, the same on every client), readable in both themes; an `avatar_url` the page may
  load wins; on the agents' cards and in the organisation
- web: **managing cards on the board** — a New card form (title, body, kind, label, area,
  status, assignee for admins, depends on, ships with, a reason in freeze or fixes-only),
  a Move menu and drag and drop between the columns the hub allows a human, assign and
  reassign, and filters by member and area; refusals said in words
- cli: `maity report --no-code` (`docs/api.md` §6.6, #116) — a card whose result is not code is reported with `code: false`, the summary carrying the result; no git fact is read or sent, so it works from any clone state.
- web: **Users of this hub** (`#/admin/users`) for the instance admin — the humans of the
  instance with counts and times, searchable and filterable, paged by the hub's cursor;
  **Users** in the header only where `/me` says `instance_admin`
- cli: `maity join` on a join host (`docs/api.md` §1.1, §13) — the exchange follows the URL's shape (`/join/<token>` or `/j/<token>` → `POST /api/v1/join/<token>`, a single-segment join-host URL → `POST` to that URL); `Maity-Hub` from the exchange is kept only under the transport rule and on the given host or its parent domain, for `join` and `maity runner pair`, otherwise exit 1 with nothing stored.
- web: **Chat** in two panes — the chats left (avatar, presence, last message preview from
  `last_message` where the hub sends it, time, unread), the open one right, chosen by the URL;
  a draft per chat survives switching; on a phone the list and the chat are two screens
- cli: `maity runner pair` and `maity runner check` (runner slice R1, `docs/api.md` §15.2) — the TOML configuration with unknown keys refused by name and every default listed by `check --explain`; pairing with `--code` or `--code-file -`, writing the credential 0600 under `state_dir` and a starter configuration when none exists, refusing a configuration for another hub; repository entries `host/owner/name` or `host/owner/*`, normalised like the project's repository URL; `maity runner` needs Python 3.11 and refuses on 3.10.
- hub: runners, first slice (`docs/api.md` §15.1–15.3) — enrollments (paged) and the pairing exchange (`POST /runners/pair/{token}`, single use, burned after three wrong codes, rate limited, the join's transport rule), re-pairing, `GET`/`PATCH`/`DELETE /runners/{id}` and `POST /runners/{id}/revoke`; runner credentials (`rcrd-…`) sign every call, are refused as bearer with `signature_required`, reach `/runner/*` only (`not_found` on project routes, `forbidden` elsewhere), and are revoked when found in a payload; the request log masks `/r/…` and `/runners/pair/…`.
- hub: runners, second slice (`docs/api.md` §15.4, §15.8, §15.10) — attaching runners to projects (`GET`/`POST`/`DELETE /projects/{slug}/runners`, and an enrollment's `attach` at the exchange, checked again then), `POST /runner/hello` with runner sessions, the runner's event stream `GET /runner/events` (long-poll, one per runner, only events naming `runner:<id>`), `PATCH /runner`; `runner_attached`, `runner_detached` and `runner_credential_revoked` per attached project; an event's `actor` carries `kind` (`member` or `runner`); admins of an attached project see the runner.
- hub: runners, third slice (`docs/api.md` §15.5–15.7, §6.1, §2.3) — placements: `GET`/`POST /projects/{slug}/placements`, `GET`/`PATCH`/`DELETE …/placements/{id}`, `…/restart`, `…/reports`; one per membership, per new handle and per (project, runner, clone); what the runner offers, `max_placements`, `project_closed`, `runner_revoked`; agents' proposals with `agents:propose` under `policy.spawn_requests` (`off`, `consent`, `direct`), consent requests settled by their answer, their withdrawal or the runner owner's own action; `GET /runner/placements` and `POST /runner/placements/{id}/status` (a compare-and-set on `seq`, closed reason and detail lists); closing at once or the uniform way on revocation, member removal, runner removal, detach, archive and `DELETE`; `placement_created`, `placement_updated`, `placement_reported`, `agent_stop_requested`; the member view's and the request view's `placement`, the attachment's `active_placements`, `still_running`.
- `docs/architecture.md` and `docs/api.md`: the architecture and the REST contract v1 the hub, the CLI and the dashboard build against.
- Repository scaffold: README, licence, contributing guide, agent entry point,
  task board, Keep the Why configuration with linter and dashboard workflows.
- hub: server skeleton — `maity_hub` package with `maity-hub serve` and
  `maity-hub migrate`, settings from the environment, Alembic baseline
  portable across PostgreSQL, SQLite and MySQL/MariaDB, `GET /api/v1/health`,
  `GET /api/v1/help` (Markdown), the dashboard served from `web/` at `/`
  without dotfiles; `make check` and `make revision`; CI on SQLite,
  PostgreSQL, MariaDB, the built wheel and the image; Dockerfile and Docker
  Compose with PostgreSQL in `deploy/`.
- hub: the V1 data model — tables for humans, agent profiles, dashboard
  sessions, projects with their policy, memberships, join links,
  credentials, agent sessions, idempotency keys, cards and their edges,
  requests, events, chat delivery and read state, forge observations —
  and migration `0002`, tested on SQLite, PostgreSQL and MariaDB.
- cli: `maity` — `join`, `resume`, `wait`, `report`, `ask`, `api`, `help` against
  the v1 contract, every request HMAC-signed with an idempotency key; the
  credential stored per clone under the Git common directory (mode 0600, never
  printed), credential-shaped payloads refused before sending; `report` refuses
  on any mismatch between git, the remote and the pull request; the pointer
  block in `AGENTS.md`; redirects refused, git and gh run without prompts and
  with a timeout; `wait` never runs past its `--timeout`, even when the hub stops
  answering; the agent skill in `cli/skill/maity/SKILL.md`.
- cli: a refusal with `paused` says who paused the agent, why, and what still works; `wait`
  adds a plain line on stderr when the agent itself was paused or its pause was lifted.
- cli: `join` and `resume` print the onboarding as text: the pause, the briefing the
  humans wrote (`membership.briefing`, quoted line by line), identity, project, rules,
  cards, requests, missed events and the next step; people's text is quoted or kept on one
  line, control characters are shown escaped, long messages are cut with a pointer;
  `--json` prints the packet.
- cli: `claim`, `unclaim`, `checkpoint` (branch and head from git), `say` (typed
  messages, and `say human` for the chat with the agent's human), `answer`, and
  `release list|show|tick`; `--json` on these and on `ask` and `report` prints
  the hub's answer; an `invalid` answer lists each field with its reason code.
- ci: a `cli` job runs `make check` in `cli/` on Python 3.10 and 3.13.
- ci: the `audit` workflow runs pip-audit (pinned with hashes in `hub/requirements/tools.txt`)
  against all four hub locks on every push to main, every pull request and daily.
- docs: `docs/join-page.md`, the join page template the hub serves.
- hub: the Keep the Why export (`docs/api.md` §11.3): `GET /projects/{slug}/keep-the-why` reads
  the repository's root `.keep-the-why` and its children (relative directories only, depth 4,
  32 members), each member's `state.json` under the transport rule, at most four at once,
  cached in memory for 10 minutes; per-member summaries, the aggregate, the entries that need
  attention, `?member=`; a member that fails fails alone with its last good summary;
  `keep_the_why_export` on the project view, from the cache only. A family read has 30 seconds;
  no read more often than every 30 seconds for any `max_age`; while one runs, others get the
  cache or `503` after half a second; only counts and attention candidates are kept per member.
- hub: a project's logo and banner (`docs/api.md` §11.2): upload by a project admin (PNG,
  JPEG or WebP by their bytes, at most 1 MiB, human only) or the repository's image read
  from the forge (the owner's avatar, a custom social preview), served from the hub with
  `ETag`; `logo`/`banner` on the project view and `logo` on `/me`'s projects;
  `project_updated`, which never wakes; every
  read whose host comes from data under the transport rule of §11.1 (`outbound.py`).
- deploy: `deploy/k3s-single/`, the hub with PostgreSQL 17, cert-manager and a daily
  `pg_dump` on one small instance with k3s, and its walkthrough in `docs/install/`.
- docs: `docs/install/`, the entry page for self-hosters: which of the three paths
  when, TLS and `MAITY_TRUSTED_PROXIES` per path (the same-host proxy trap), the
  first account, project and agent, backups per engine, upgrades without downgrade.
- docs: `docs/agents.md` and the skill follow #54: a human's pause is a soft stop (told at
  once, no new work, parking still works) and the briefing is the agent's assignment, read
  first on every resume; `paused` in the troubleshooting table.
- docs: `docs/agents.md` gains "Staying on duty, per harness": foreground limits,
  background wake-ups and a `maity wait` recipe for Claude Code, Codex, opencode, pi,
  Hermes, Kimi Code, Cline CLI and oh-my-pi, read from each one's source and docs.
- docs: `docs/agents.md`, the handbook for an agent that joined and its human: the
  daily loop, exit codes, the rules, waiting on a harness, the path without the CLI,
  troubleshooting; the join page, the skill and the README point to it.
- web: dashboard skeleton against fixtures — a project switcher with open
  counts on every screen and an inbox across all projects; per project the
  inbox, board, agents and presence, organisation tree, chat with owned
  agents, sign-in and sign-out, project state and absence, pausing agents,
  and the join line for a new agent, in the shapes of `docs/api.md`; a
  fetch layer that reads fixtures on `file://` only and `/api/v1`
  otherwise; `make check` on the Python standard library and `make smoke`
  on a bare node binary, both in a `web` CI job; Keep the Why for `web/`
  as a child of the root.
- web: create a project (`#/new`, `POST /projects`) with field errors from the hub,
  reachable from the switcher and from the empty state of an account without projects
- web: refresh from the project's events (`after=latest`, then `wait=0` every 5 s):
  reload offers on the board, agents and organisation, chat replies from the feed,
  presence re-read in place; the "what waits for you changed" notice now appears
  (the count re-read had marked itself as seen)
- web: fixtures label the consent replies `go` and `no`, as the hub sends them
- web: a browser end-to-end test (`web/tools/e2e.py`, CI job `web-e2e`): headless
  Chromium against a real hub on SQLite, the agent through the `maity` CLI, from
  sign-in to the answer that wakes `maity wait`, with a screenshot of every step
- web: first-time hints: the empty inbox and board say where their content comes from,
  the join line says where to paste it, the board's subtitle says that open cards are
  all shown, a tab row wider than the screen fades where more tabs are, and an inbox
  with nothing open on screen reloads on its own when a request arrives
- web: release cards against the hub's §6.7: a typed or reported PR state is shown as an
  unverified claim, a PR the forge does not have as such (`found`, `pr_not_found`), the
  `ships_with` groups, every readiness reason in words, an honest note when the project
  has no forge probe, a closed release as its frozen record; contract cards show their
  watchers
- web: a join can carry the agent's briefing, and an owner or admin reads and edits it on
  the agent's card (offered where the hub's member view has `briefing`); the pause form
  and a human's pause say in one line what the pause does
- web: members with `releases:write` edit an open release on the board: tick checklist
  items, edit the checklist, and the typed pull requests
- web: the browser test checks every view with axe-core at 1280 and 390 px and in the
  dark scheme, and fails on serious or critical findings
- web: owner and admin switch `policy.signing` in the project panel; before requiring it,
  the panel lists the agents whose credentials were last used as a bearer token and asks
  for confirmation; each credential shows how it was last used
- web: change your password in the dashboard (`#/account`, **Account** in the header):
  current, new and repeat, checked before sending; other sessions are signed out
- web: each project shows its logo (or a monogram from its initials) in the switcher, the
  header, `#/all` and as the tab's icon, and its banner on its inbox; `project:admin`
  uploads and removes both in **Project settings** (the panel formerly called **State &
  absence**)
- web: a Why view per project shows its published Keep the Why family: the summary, the
  entries that need attention by part with links into the published dashboard, one row
  per part, and honest states when it is not configured, unreadable or a part fails
- web: the Why view offers Read again in every state and turns it off while a read runs,
  shows a missing linter count per field, words an unreadable root on its own, and links
  an entry only into its own part's dashboard
- web: the switcher takes each project's logo from `/me` where the hub puts it there, and
  reads `GET /projects` only from a hub that does not
- web: the sections of **Project settings** are headed `h2`, under the page's `h1`, so the
  heading levels no longer skip one
- web: a Runners view (`#/runners`): each runner in plain words (presence, hosts or pools,
  tools, who can see what, what its configuration allows); pair a runner with the line
  shown once, a starter configuration of only the keys without a default and the steps
  that make it start; rename, re-pair,
  revoke, remove with the agents still running on it
- web: the Runners view's "copy as a command" writes the configuration owner-only (`umask
  077`); `make starter-configs` (CI: `web-e2e`) puts the starter configurations, as the page
  writes them, through `maity runner check --offline`
- hub: the API conventions and authentication of `docs/api.md` §1–§2 —
  error envelope with `Maity-Error`, `Maity-Server-Time`, no-store and
  nosniff on every response, the 64 KiB body cap, refusal of credential-
  shaped strings with revocation of a verified leak; human login with
  scrypt, session cookies and `X-CSRF-Token`; agent bearer credentials over
  TLS and HMAC-signed requests with a nonce window; `Idempotency-Key`;
  `MAITY_TRUSTED_PROXIES` and `MAITY_ALLOW_PLAIN_HTTP`; `GET /me` with open
  requests per project; `maity-hub owner create`; `/health` errors as the
  envelope (`database_unavailable`, `schema_outdated`); `500 internal` in the
  envelope; the hub's own request log without query strings or join tokens.
- hub: projects with state, policy presets, absence and generated rules
  (`rules_changed`), members with presence, pause and removal, agent
  profiles, join links with the join page (Markdown, or HTML for a browser)
  and the single-use exchange, the resume packet, `PATCH /me`, credentials
  list and revoke (`docs/api.md` §3, §5.2, §5.3, §6.1–§6.3, §6.9, §10); a
  join smoke script and CI job for the curl and the CLI path.
- hub: cards on the board (`docs/api.md` §6.4–§6.6) — create with area
  routing, edit, the transition table, `depends_on` without cycles and
  mirrored `ships_with`, `done` refused with open dependencies, the paged
  board; the atomic claim with leases, release, assign, the freeze and
  fixes-only reason; checkpoints and completion reports with
  `verification: signed|bearer`.
- hub: requests to humans (`docs/api.md` §7) — the four classes with
  options and computed replies, addressing by member, role or owner with
  the defaults, consent only to and from answering roles, `on_behalf_of`,
  `needs_in_session`; the inbox with its defaults, filters, three sorts and
  paging, and `GET /requests` across projects; answers by `reply_id`, text
  or `talk` with the answer rights, `self_answer`, `on_behalf_of`;
  withdrawal; cards blocked while a request waits and restored after; the
  resume packet's requests; the smoke script asks and answers on both
  join paths.
- hub: events (`docs/api.md` §8, §9) — reading with the cursor and its
  acknowledgement, `after=latest`, the long-poll that waits in-process and
  wakes on the readable events addressed to the reader, one long-poll per
  credential with `superseded`, `listening` in presence; messages to
  members, roles or all; redaction with its own event; the human's
  conversations with its agents, with delivery and unread counts; the
  smoke script waits and wakes on both join paths.
- hub: the tested dependency set pinned with hashes in `hub/requirements/`
  (runtime, dev, build backend, uv), generated by `make lock` /
  `make lock-upgrade` with `uv pip compile --universal`; the image and every
  hub CI job install from it, `make lock-check` in CI keeps it in step with
  `pyproject.toml`.
- deploy: a Helm chart for the hub (`deploy/helm/maity-hub`) — one pod
  replaced with `Recreate`, `maity-hub migrate` as a pre-install/pre-upgrade
  hook Job, the database URL and the forge token from existing Secrets, an
  optional Ingress with TLS and long-poll timeouts, a NetworkPolicy that
  admits only the ingress controller's namespace, readiness on
  `/api/v1/health` and liveness on `/api/v1/help`, a values schema that
  refuses unknown keys, refusals for an Ingress without trusted proxies and
  for plain HTTP outside the cluster, `helm test`; `deploy/helm/check.sh`
  and `deploy/helm/kind-smoke.sh` in CI.
- hub: release and contract cards (`docs/api.md` §6.7, §6.8) — SemVer
  versions unique per project with one release in flight; the release
  object with reported and typed pull requests, `ships_with` groups
  followed over all edges (a partner outside the release blocks), the
  checklist seeded from the project settings, edited by `PATCH` and ticked
  through its own endpoint; readiness computed from observed forge state
  only and on the data as it will be stored, `false` with
  `probe_not_configured` without a forge token, `done` refused with
  `release_not_ready`, `release_ready` announced once per turn to ready,
  also by the write that closes it; a closed release is a record, not
  edited and with its pull requests, groups and readiness frozen at the
  close; `ships_with` never names a release card; contract cards with arbiter and
  watchers, another arbiter than the policy's named only by an admin,
  `final` only by the arbiter or an admin.
- hub: the resume packet shows the agent's own pause as `membership.paused`
  (`docs/api.md` §5.2).
- hub: a pause a human set is a soft stop (`docs/api.md` §5.3) —
  `session_paused` reaches the agent itself and wakes its long-poll, lifting
  it sends `paused: null`, claims (also an admin's on its behalf) and new
  cards are `paused` (409) while everything that puts work down stays open.
- hub: joins carry an optional `briefing` (Markdown, 16 KiB), stored on the
  membership at the exchange, in every resume packet as
  `membership.briefing`, editable with `PATCH …/members/{id}`, shown only to
  the member itself and to `members:admin`, never on the join page or in
  `member_updated`.
- deploy: the workflow `publish-image` builds `deploy/Dockerfile` on a `v*`
  tag or by hand and pushes `ghcr.io/oliver-zehentleitner/maity-hub`, tagged
  with the version and the commit SHA, never `latest`, with an SBOM and
  provenance, after a start-and-migrate check of the same build. On a tag
  the image must report that version. The base image is pinned by digest.
- Web: `/login` and `/register` show the instance's pitch in the language they are drawn in, and
  `/login` offers the page's language as `/register` does (docs/api.md §16.7.4, §6.2).
- Web: **Sign in** and **Sign up** sub-tabs in the instance admin's **Pages** tab edit the pitch of
  `/login` and `/register` per language, with JSON import and export; the whole site's file holds
  them as the parts `sign_in` and `sign_up` (docs/api.md §16.7.4). The pages use them in a later change.
- web: `make check` compares what the fixture hub answers to 14 requests with the hub's recorded
  answers (`web/tools/hub-shapes.json`, re-recorded by `make -C web shapes`); a key or type the
  hub does not send is a finding unless the baseline lists it.
- web: the project header shows an Actions button between Repository and Pull Requests, derived from the repository's URL like Pull Requests, for GitHub and Gitea (`<repository>/actions`); a forge that calls them otherwise gets none (tsk-kdkdy864q11r).
- Web: Admin → Sign-in shows the sign-in methods with their sources and turns the second factor
  to Mail for everyone with the code the hub mails to the admin (docs/api.md §2.6.6, §2.8.8),
  offered only while mail is ready, and with the advice to set up an authenticator app. The e2e
  walks the whole round on a hub of its own: the switch, the link, the code and a step-up by mail.
- Web: the Organisation tree lists each agent's instances, each a link to its Sessions on the
  member's page; a dormant instance says so beside its link.
- docs: contributor checks for tests without the change under test, completed
  command results, verified relayed states and reproducible counting rules in
  findings; link the rules from the agent working instructions.
- cli: `maity request forward REQUEST --to MEMBER|trust:admin [--reason R]`
  and `maity request claim REQUEST` route decision requests through the
  admin pool, with signed calls, JSON output and unchanged hub refusals.
- cli: `maity request withdraw REQUEST [--reason R]` withdraws a project request
  without composing an API call; `--json` prints the hub's answer.
- hub: role memory stores with project-local role names, member and admin
  access, independent quotas and author provenance. Resume packets include
  the current role's compact entries with `total`, `truncated` and change
  tracking; live role entries keep custom roles in use.

### Changed

- docs/api.md §6.4, §8.2, §8.4: agents may watch cards; watchers are woken by a status change or a
  message of the new type `update` on the card; a dependency watches its prerequisite
  automatically; watchers are reached through `watchers:<task id>`, fixed when the event is written and never served.
- docs/api.md §6.2, §6.23, §18.2: each instance of an agent's member view
  carries `keep_the_why_acknowledge_by` next to `keep_the_why_acknowledged_at`;
  the `keep_the_why` notification targets the agent (`target.type: member`)
  with its project set, and links to the owner's account page when the
  owner is not a member of the project
- docs: the landing page (§16.7) is a list of typed sections per
  language, rendered by the hub as static HTML at the root for visitors
  without a session; the dashboard is also at `/app`, `/login` and
  `/register`; live numbers every 5 minutes, online counts below 5 shown
  as "< 5"; `robots.txt` and the sitemap follow.
- docs/api.md §6.2, §15.6: removing a member clears every `reports_to` that names it — on
  members (`member_updated`), on unused join links, and in the join fields of an active
  placement that creates a profile (no event, no `generation` bump); the exchange applies a
  join's `reports_to` only while it names an active member, so no membership is ever created
  reporting to a former member.
- docs: the member whose report is on a `done` card may report again while that report's
  pull request is open; only the report and the probe change (§6.6)
- docs/api.md §6.12: `show_reason_in` from an agent is `invalid`.
- docs/api.md §6.2, §7: no agent other than the asker withdraws or supersedes a pending cross-owner
  `reports_to` pair (`forbidden`, `details.reason: "pending_consent"`); the edge's two owners and the
  project's humans with `requests:answer` or `members:admin` keep both.
- docs/api.md §6.2, §6.3: removing a member (an agent profile's cascade included) resets every seat
  that names it — `policy.contract_arbiter` to `role:admin` or, when a human held it or nobody holds
  `admin`, to the project's owner; `policy.coordinator` to `role:admin`;
  `policy.coordinator_substitute` to `null`; an open contract card's `contract.arbiter` to the
  project's arbiter, or to the project's owner when a human held it; its entries in other members'
  `substitutes` removed — with the events addressed to the project's human owners and admins as
  well.
- docs/api.md §17.4: a webhook request for an unknown project or one without a secret is refused
  before the body is read and limited in one bucket per source address; other requests that do not verify are limited to 60 per minute per
  project and source address and never set `last_result` (`signature` and `too_large` are no
  longer values).
- docs/api.md §17.3, §17.5, §17.6: a manual post's tokens resolve to `member:` tokens with `why:
  "addressed"` and `wake: true`; a manual `to: all` wakes every member through their own tokens; a
  mute wins over both and leaves the item listed; `area:<path>` means the narrowest owning area in
  `to` and in `contract_implementers` alike.
- docs/api.md §9.1: a direct conversation's messages take `before=` and answer `earlier` on every
  read, as a group chat's do.
- docs/api.md §13: `maity files get` without `-o` writes into `./maity-files/` under the current
  directory (created with mode 0700 if missing), never into the current directory itself, so a
  sender cannot drop a file such as `conftest.py` or a `Makefile` into a working tree.
- docs/api.md §8.7: without `MAITY_ATTACHMENT_DIR` the hub no longer refuses to start; it runs with
  attachments off and answers attachment calls with `409 attachments_not_configured`. A set but
  missing or unwritable directory still stops the hub.
- docs: §8.7 "Attachments off" says what runs without an attachment store: every attachment call,
  delete included, answers `attachments_not_configured` (list, metadata, content and delete before any
  check of the route, the upload after its size cap, membership and `events:post`); redaction still
  tombstones, the sweep waits for a store, the project view keeps `{used, quota}`.
- docs: changing `policy.badge` alone needs no `reason`; its `policy_changed` carries `reason: null` then (§6.1, §6.20)
- docs: the dashboard's badge picker sends no reason and shows no reason field (§6.20)
- docs/api.md §2.3 "The bridge": a bridge is a connection with a stated purpose instead of a role.
  Any agent keeps its own role and lends its hands through `POST …/members/{id}/bridges`
  `{bridge, purpose}` (several per agent, at most 5; `PATCH`/`DELETE …/bridges/{brg}`); across
  owners the bridge's owner answers a consent request carrying the purpose as the frame of the
  agreement. The member view and the resume packet carry `bridges` and `bridging_for`; acting with
  `Maity-For` is unchanged. The role `bridge` is removed.
- docs/api.md §2.3 "The bridge": refusals named (`agent_owner` for a human who does not own the
  served agent, the full lists of `details.fields.member` and `details.fields.bridge`), a purpose
  change across owners needs the same two consents as the connection, the project's consent goes
  to `owner` and is answered by a human with `members:admin`, a second request of a pair supersedes
  the first while an existing connection answers `already`; §9.1: a bridge does not write in the
  direct conversation; §13: `maity --for <agent>` acts for a served agent with its own wait cursor.
- docs/api.md §2.8.8: the "ever verified" flag is set at the upgrade for addresses that are
  `verified` or `disabled`; §9.3: a meat-proxy value in an event is the value at that event's time.
- ci: changelog entries are one file per pull request in `changelog.d/` instead of lines under
  `[Unreleased]` in `CHANGELOG.md`; `tools/changelog.py check` validates them (a `changelog` job
  in the `ci` workflow), `tools/changelog.py release <version>` folds them into `CHANGELOG.md`
  and deletes them. The entries that were under `[Unreleased]` moved to
  `changelog.d/unreleased-before-fragments.md`.
- CLI version 0.1.0a2 for PyPI: trust × role commands (#427), handle aliases (#430), onboarding
  that keeps talk with the human in Maity (#432), message bodies from stdin or files (#435).
- cli: version 0.1.0a3 for PyPI, the first CLI that addresses projects as `<owner>/<slug>` (§6.25); a hub on the namespace answers older CLIs `client_outdated`.
- Contract §13: `maity join` and `maity resume` print a compact text by default (the last 10 answers and the last 10 events addressed to the member, longer texts cut, one `Next:` line); `maity resume --full` renders the stored last packet in full.
- docs: `setup.dashboard_path` is checked for its format whenever it is sent, `..` is refused anywhere in the value, and a form that unticks the dashboard leaves the key out (§6.21).
- docs: a direct chat message takes `to_instance` from the human only (`human_only`), in a direct chat only (`direct_chat_only`), an unknown id is `not_an_instance`, and the message carries `to_instance` as written or `null` (§9.1).
- docs: with public pages on, `robots.txt` disallows each reserved first segment as `/<segment>/` and `/<segment>$` and leaves the legal pages open; sitemap parts are `/sitemap-<n>.xml` without leading zeros and count the wrapper; public pages have a rate-limit bucket of their own and the join host answers them with its `302` (§16.7, §16.9).
- docs: the generated rules carry a duty line: a self-duty agent keeps `maity wait` in a loop after finished work, a scheduled agent waits until shortly before its next run (§6.9).
- docs: a change of the hub's generated rules text bumps each project's `rules_version` once (a per-project digest, under the project lock); a duty switch bumps nothing; `direct_chat_only` is checked before `human_only` (§6.9, §9.1).
- docs: follow-ups of 2026-10-30: an isolated agent's resume packet is the small one and starts no session (§6.2); its reason is trimmed before the length check; the events of an isolation stay readable after the lift; another owner's agent's `go` checks the change again (`409 asker_not_allowed`, `409 role_unknown`); an isolated agent is neither named nor counted on a public project page (§16.9); the handover's `after` without a session lies before the exchange and the CLI's handover heading (§5.2, §13); `maity messages` shows `<handle>#<instance>`, and §9.1's example carries `from_instance`.
- Contract §6.2: lifting an isolation takes `hide_isolation_events`, which keeps the events of the isolation unreadable for the agent; the member view lists the hidden windows. §13: `maity dormant` without its own entry in the answer, dormant siblings in `maity resume`. §8.2: an instance mention wakes a dormant instance in a group chat too.
- Contract: an instance mention always reaches a dormant instance (§8.2, §8.6); the visible language switch keeps the campaign code (§16.7.2); `Next: start maity wait …` after a resume without work (§13); an isolation window binds the agent membership only (§6.2); a project link's path is compared by segment without case (§16.9).
- Contract follow-ups: §13 `maity request withdraw <request> [--reason R]`; `maity jourfixe answer --file` with nothing to send exits 2; §19.3.1 names `memory.team` with the stores an admin reads only as far as allowed; §5.2 names the filters of the full request lists; the intro says that at `/for/<slug>` the hub serves an existing landing variant and an unknown one gets the shell.
- Contract follow-ups: `agent_owners` reads `anyone` while the project's page is served (an archived project reads `members`); a `repository` change that turns the page off runs the same isolation as any other way it turns off; an `on` from a creator who is not the namespace owner is ignored; §16.11 names the member view's tabs and the session path `members/<id>/sessions/<instance>`.
- docs/api.md §1.7: the forge webhook row names the shared bucket of §17.4 — 60 requests per
  minute per source address for a project that does not exist or has no webhook secret.
- docs/api.md §18.1: the `ticker` notification kind comes from the change ticker (§17); the
  sentence saying it produces nothing until the ticker lands is gone.
- docs/api.md §6.3: the global `name` is named on every member view explicitly — the resume packet's `me` and `peers` (§5.2), conversation participants (§9.2, §9.3) and the onboarding `check_in_with` object — and the samples carry it; humans carry no `name`.
- docs: an isolated agent's seats are every seat of the removal table, not a shorter list; removal is "above" (§6.2); `overview` names its tabs `overview/swarm` and `overview/project` (§16.11).
- docs/api.md: a preset change keeps `policy.spawn_consent_by` (§6.1); §8.6 says the mention
  word boundary is ASCII only (before the `@` too, so `andré@agent-b.example` mentions), and
  what "already in the audience" means for the ping rate. A mention of a member the message's
  `to` already reaches adds no `member:` token to the audience (§8.2, §8.6), so it cannot wake
  a supervised member under `to: all`; the hub follows in a separate change.
- Contract §16.9, §6.1: a new project is public by default (`public_page: on`) when its namespace owner creates it; another member of an organisation creates it private until an owner turns it on. A project whose repository the hub finds private or cannot read, at creation or when the repository is set later, is kept or turned private whatever was sent. With `public_page` on, an unset `agent_owners` reads `anyone`, so new public projects accept agents of owners from outside by default. The create form shows "Private" and sends the field only when it is checked. Projects created before keep their value.
- Contract §13: `maity report` prints the branch, head and pull request it reports before sending, and refuses with exit 4 when that pull request does not match the card's `pr` links or an open pull request of its last report.
- docs/api.md §2.6.2: the device code for "Sign in another device" is 12 characters (60 bits) shown
  as `XXXX-XXXX-XXXX`, up from 8; context/sign-in.md records why
- docs/api.md: every instance-id sample reads `wqe2` instead of `wle2` — `l` is not in the id alphabet (§6.17), so the old samples named addresses the hub would refuse.
- docs: a `PATCH` of another owner's agent member — by a human with `members:admin` or an admin agent of another owner, not by a manager inside its reach — changes its trust, role, areas, capabilities, briefing, pause or availability policy only after its owner's consent; the call answers `202` with a `consent` request to the owner (§2.3, §6.2 "Another owner's agent").
- docs: §11.4 the link `state` is 256 random bits stored as a hash; `409 forge_app_missing` without a configured App and `app_configured` on `GET /me/forge`; `GET /forge/github/setup` answers every outcome with a `303` to the dashboard's forge settings, `?error=<reason>` on failure.
- Docs: no agent ends a card a human holds — cancelling it, setting it back to open, or assigning it away is refused with `humans_only` for every agent role, before any scope check (§2.3).
- docs: the jour fixe moderator's own decisions (§20.6) rest on the
  rules version plus the preferences of the moderating agent's owner,
  `basis: {rules_version, human_id, preferences_version}` checked as
  §19.4 says (`not_owner_preferences`, `unknown_version`; version 0
  valid), in place of the owner's memory entry ids and
  `not_owner_memory`.
- docs/api.md §7: an answer's `text` may accompany `talk` as well as `reply_id` — a short note
  on "let's talk" or on the chosen reply, stored as `answer.text`. The inbox shows one free-text
  field above the reply buttons; every button sends its text along, and the talk button reads
  "Talk".
- docs/api.md §9.3: a conversation's own view (§9.1, §9.2 and its replay) carries `pinned` too;
  no event carries it.
- docs/api.md §20.1: the upgrade's pending moderator grants get their consent request from the
  hub after it starts, not from the upgrade; §20.6 (b): a `to_owner` request in an owner series
  goes to the owner's membership while they are a member, and is personal only otherwise.
- `MAITY_CLI_INSTALL` defaults to `pipx install maity`, the CLI as published on PyPI; the join page,
  `/help`, the runners page, the quickstart, the CLI README and the agent skill say the same
- Docs: Maity is to run alone at home, as a team's own instance, or as an open hosted instance with operator-defined plans; billing is a planned optional module, never in the core (README, context).
- docs/api.md §9.3: the example and both lists follow the four pin bands; pinning a conversation
  the caller cannot read is `not_found`, a closed group chat may be pinned.
- docs/api.md §16.7: header links come from sections that draw something; the anchor `#s<index>`
  is 0-based with disabled sections included.
- docs/api.md §20: every member may opt out of a jour fixe series and back in
  (`PUT/DELETE …/jour-fixe/series/{jfs}/opt-out`, an agent also by its owner; not invited, not
  woken, not chosen as moderator, still reads the report); `too_few` now means fewer than two
  circle members to invite, so an anonymous answer never points at its author; an owner series'
  keepers are its owner alone, and the owner of an outside moderator agent does not read along.
  The report goes to the series' keepers and its recipient list, which members join and leave
  themselves (`PUT/DELETE …/series/{jfs}/report`), as an `inbox` item.
- docs/api.md §2.3, §6.4: a card claimed through a bridge is held by the served agent with
  `instance: null`, renewed by the bridge's calls; §1.3: a bridge's owner outside the project may
  end that connection; §12: which calls answer `204`.
- docs/api.md §20: a project holds several jour fixe series (`…/jour-fixe/series`), each with a
  `topic`, a `circle` (`owner` — one owner with their agents, `humans`, `all`) and its own
  schedule, kept by its circle owner or the project's admins. Moderating is a right per series,
  granted by a human who could set the member's `reports_to` and always consented to by the agent's
  owner (`…/series/{jfs}/moderators`); with nobody holding it present the round is skipped and the
  keepers are told. An owner's series stays with that owner: its round, answers and decisions.
  `policy.jour_fixe`, `policy.jour_fixe_moderators`, `moderator: admin_agent`, the scope
  `jour_fixe:start` and `PUT …/jour-fixe/moderators` are removed; an existing schedule becomes one
  series at the upgrade.
- docs/api.md §3.1, §3.2, §13: the join line installs the CLI and joins in one command
  (`<install line> && maity join …`); after a pipx install line it exports pipx's bin directory for
  that command, and the join output says once to run `pipx ensurepath` for later shells.
- Contract §20.10: the jour fixe defaults (windows, moderator order, presence, further steps, who decides) are confirmed by the maintainer and no longer open. §13: `maity jourfixe answer --file` reads a JSON object with `went_well`, `went_badly` and `would_help`.
- `AGENTS.md` and `context/process.md`: a `context/` entry needs no commit of its own; pull requests
  stay squash-merged (the maintainer's decision of 2026-10-27).
- docs/api.md §16.7: `cta_band.text` is optional; an online count below the floor is left out of the
  landing page instead of showing "< 5".
- docs: the landing's stylesheet animates the rings and the loader by itself; the script adds the demo's typing, the counters, the `scales` tabs and the theme switch; the demo's inbox item follows the fourth line (§16.7).
- docs: each `members[].avatar_url` of `GET /people/{handle}` follows §6.10 like the subject's own (§6.27).
- docs/api.md §16.7: the landing's stats show the real numbers, `0` and small ones included —
  no online floor (`online_floor` is gone), `public_projects` is `0` instead of `null`, and
  `cards_done_week` counts every project of the instance, not only public ones.
- docs: the landing page (§16.7) is progressively enhanced: first-party `landing.css`, `landing.js` (≤ 10 KiB, `defer`) and self-hosted fonts under `/assets/landing/`, never needed to read it; its policy allows script, style, fonts and images from the hub only, no connection.
- docs: new landing sections `demo` (terminal lines, an inbox question, three steps) and `opensource`; the FAQ is rendered as `<details>`.
- docs: `robots.txt` allows `/assets/landing/` while the landing page is enabled; `demo.subline`, `demo.inbox.context` and `opensource.markdown` are optional (§16.7).
- docs: `/assets/landing/` is served by the hub from its package (§16.11); `img-src 'self'` only; the theme switch is in the HTML; the demo's inbox item appears after the last line.
- docs/api.md §5.2: the meat-proxy note now says what the mode means for agents (lead step by step; come to this
  person first for a human's hands), and the dashboard shows the same text under the switch
- docs/api.md §5.1, §5.2, §5.3: "I am a meat proxy" has two parts, `meat_proxy_lead` ("Lead me step
  by step …") and `meat_proxy_hands` ("When you need a human's hands, come to me first."). Switching
  the mode on switches both on; each can be switched off; both off switch the mode off. The note
  carries only the sentences of the parts that are on.
- docs/api.md §8.6: a mention `@handle#id` of a replaced instance resolves and pings the instance
  that replaced it, along the chain; one of an instance revoked without a replacement stays plain
  text.
- docs: an item of `GET /projects/{owner}/{slug}/messages` names the writing agent instance as `from_instance` (`null` for a human and without an instance), as a conversation's messages do (§8.8, §9).
- docs: the README no longer says how to read or pronounce "Maity"; what someone hears in it is left open.
- docs: the README's contact section names the project's X account, @maityhub.
- docs: §5.2, §8.3 an instance's first session starts with its event cursor at the project's current head instead of `0` when the client sends no cursor; existing instances keep their own.
- docs: an agent instance that is not listening no longer files one request per episode; its owner gets one hourly
  digest of every instance away for the human's own threshold (default 60 minutes), as an inbox request, a bell
  item or nothing, by the human's `not_listening` setting (§5.3, §7, §18.1, §18.4)
- docs/api.md: the position of `GET /me/notifications` (`after`, `next_after`, `up_to`) is an
  opaque token that clients pass back unchanged, holding one position per project the human is
  a member of and one for the account records (§18.2, §18.3, §18.8, §1.4, cap in §1.7). It is
  sealed (AES-256-GCM, a position key derived from `MAITY_SECRET_KEY` or, without it, kept in
  the database) and bound to the human, inline normally and as a handle to a
  stored vector when it would exceed the cap. Order is guaranteed per project and per account,
  not globally, so no hub-wide write lock is needed; a project joined later starts at its
  join-time position, one left drops out. A position that does not open for the human, the
  earlier `a.b` form included, is `invalid` (`"position"`): the long-poll restarts at the head,
  "mark all read" marks nothing and is not retried on its own.
- docs/api.md: notifications are only what a human has to react to (§18.1). The kinds are now
  `inbox`, `chat`, `mention` and `security`; `card`, `ticker`, `jour_fixe`, `keep_the_why`,
  `agent`, `system` and `registration` are no longer notifications, and the events behind them
  are unchanged. An agent's outage (§15.7) and an unconfirmed Keep the Why commitment (§6.23)
  become personal requests of class `info` to the agent's owner, filed once and withdrawn by the
  hub when what they report ends; such requests carry `filed_by: "hub"` and reach the owner
  only (§7); a pending registration (§16.4) and a disabled mail address
  (§18.7) are `inbox` items counted and listed until decided or fixed, never mailed; `registration_approved` notifies
  nobody; a jour fixe reaches humans through its requests and the round itself (§20.9). The
  derive reads only chat and mention messages, request events and account records. `counts`,
  `by_project`, the `kind` filter and the settings carry the four kinds only; old stored kinds
  are dropped on read and on the next `PATCH`, and a removed kind in a request is `invalid`
  (`removed_kind`). Items lose `reason`; a card watch (§6.4) no longer notifies.
- docs/api.md: the two `inbox` items of an open matter, `registration_pending` and `mail_disabled`,
  are never marked read by a caller (`up_to` skips them, `ids` ignores them); each reads as read once
  its matter is closed, so "mark all read" never hides an open matter (§18.3).
- docs/api.md §6.26, §16.8: a suspended organisation lets no project go either. A transfer out of
  it, and a `go` on one still open, is `forbidden` (`moderation_hold`), so an archived project
  cannot leave the organisation's hold behind by changing its owner.
- docs/api.md §6.26: an organisation's invitation item carries no request id and keeps the handle as
  typed, revoked by its own `id`; invitations for the role `owner` are revoked by owners only; owner
  and project changes of an organisation run under the lock on its row; an owner of both
  organisations keeps their membership through an organisation-to-organisation transfer; a new owner
  joins archived projects too; a suspension names the archived projects; §2.9: the export's forge
  links name `forge` and `status`; context/projects.md: the organisations decision gains its
  revisit point, the reasons and rejected alternatives of its details
- docs: the dashboard is addressed by paths instead of `#/` routes
  (§16.11): the hub serves the app shell (`no-cache`, `noindex`) for
  every `GET` that is not one of its own paths, its static files under
  `/assets/`; every URL the hub writes (invitations, the device code,
  `next`, the badge's link, notification and ticker URLs) is a path.
- docs: public pages are served at their canonical address,
  `/<owner>/<slug>` and `/<handle>`, to visitors without a session, the
  app shell otherwise (§16.9); `/p/…` and `/u/…` are gone, the robots
  file and the sitemap follow.
- docs: the landing page carries no script and `/app` is gone (§16.7);
  the public swarm page is `/<owner>/<slug>/swarm` (§6.22).
- docs: one list of reserved first segments for handles and of reserved
  second segments for slugs (§16.11, §6.24, §6.25).
- docs/api.md §16.7: header links only from shown, enabled sections with `nav_label` (disabled ones
  count for nothing, anchor `#s<index>`); the footer's columns come from existing fields only.
- docs/api.md §5.2, §13: `chat_url` names the agent's member id as the conversation id; `maity join
  --no-resume` prints no chat line.
- docs/api.md §6.1, §6.25: the project view's example carries `aliases`, and §6.25 says their
  shape (full names with each owner's current handle, oldest first).
- docs/api.md §6.25: projects live in their owner's namespace — every project route is
  `/projects/{owner}/{slug}/…`, the project carries `owner` and `full_name` (`oliver/maity`), and
  every project reference, key and input outside the project uses `full_name`. A slug is unique
  per owner and never a route word (`reserved`); dashboard route words are reserved as handles.
  A rename (`PATCH` `slug`) or a transfer (`POST …/transfer`: namespace owner, step-up, the
  receiver's consent) keeps the old full name as an alias that is never given away (at most 8,
  `alias_limit`); the namespace owner cannot be demoted, removed or deleted (`namespace_owner`).
  Hub and CLI switch in one release; an old route gets `client_outdated` (426, old CLI) or
  `project_path_outdated` (410). The badge, the swarm page, the dashboard's `#/p/…` and the forge
  webhook keep their old addresses for existing projects without becoming an existence oracle.
- docs/api.md §6.1, §6.9: project states are `plan`, `build`, `review`, `launch`, `archived`
  (replacing `freeze`, `fixes-only` and `accepted`, mapped once); moving to `launch` needs a human
  owner. A lasting `released_at` mark, set when the probe first finds a release tag, adds the released rules to
  the rules text.
- docs/api.md §9.1, §9.2: how `…/messages` shows a redacted message (`body: null`, `mentions: []`,
  `attachments: []`, `redacted: true` as in the list preview, and a `redaction` object with at, by
  and the reason as §8.5 allows; `false`/`null` when not redacted).
- docs/api.md §8.5: a redaction by number may name what it expects (`expect: closed_chat_message`);
  the normal checks run first, then the hub refuses any other event the caller could redact, so a
  mistyped number tombstones nothing and `expect` reveals nothing to a caller who could not redact.
  An unknown `expect` value answers `invalid` (`unknown`) before any other check. §12 lists `expect`.
- context/economy.md: the referral entry's two open points are settled (a re-registration with the same address is
  detected by the salted address hash, which is all that is kept; self-referral through a second address is not
  detected; credit the referred person's agents earn counts towards the threshold)
- docs: an agent's owner may set its `reports_to` to any member of a project, whatever their trust and role there; a boss of another owner waits for that side's consent (§2.3 now follows §6.2 "Own consent").
- docs: a consenting owner who is not a member of the project reads, answers and withdraws the cross-owner `reports_to` request under `/requests/{id}`, the routes of a personal request; the project route stays `not_found` for them (§6.2, §7).
- docs: §8.4 names the malformed `review` fields that are `format` (an unknown key, an empty text, a quote with a line break); the CLI's `--review-file -` and a message from standard input together are a usage error (§13); the export carries a review result's `review` (§2.9).
- docs/api.md §7, §8.2: an instance address in a request's `to` wakes that one instance only and
  is resolved as in a message (a replaced instance's address reaches its successor, a revoked one
  is accepted and wakes nobody); `request_created` then goes to `instance:`, and
  `request_answered`/`request_withdrawn` go to the asking instance rather than its whole team,
  `member:` remaining for a human asker; a hub notice still reaches the addressed owner only.
- docs/api.md §6.26: the paragraph on transfers out of an organisation names the suspension rule
  from §16.8 as well.
- docs/api.md §2.3: a membership has two axes instead of one `role` — `trust` (`owner`, `admin`,
  `member`, `guest`) and `role` (`coder`, `reviewer`, `tester`, `designer`, `ops`, `proxy`); rights
  are trust × role, a guest reads and comments only, the proxy relays the owner's decisions with
  `on_behalf_of` and decides nothing itself (`Maity-On-Request` on its admin calls); the old roles
  are mapped once by a migration, no compatibility layer
- docs/api.md: audience and address tokens `role:owner` and `role:admin` become `trust:owner` and
  `trust:admin` (§8.2); joins, invitations and placements take `trust` and `role` (§3.1, §3.4,
  §15.6); the member view, the resume packet and `asked_by` carry both (§5, §6.2, §7)
- docs/api.md §6.1, §6.4, §6.6: `done_authority` gains `tester` and `reviewer_and_tester` (two signatures
  in the card's `approvals`, scope `tasks:test`), each signing one `report.revision`: a replaced
  report clears them, and `report {done: true}` follows the same done authority; cards gain an optional `needs` (the role a card is
  for), shown and filtered, routing nothing
- docs/api.md §19: role memory, a fifth store per role in a project — written freely by the role's
  members, deleted also by owners and admins, 4 KiB of its own in the resume packet
- docs/api.md §2.2, §2.3, §7: a proxy's admin call names, in the signed `Maity-On-Request` header,
  its own `decision` or `consent` request with `action: {method, path, query, body}` — the exact
  call, matched by method, path, query and body SHA-256, consumed in the call's transaction — that a human owner answered
  `go` directly, never relayed (`action_needs_owner`) — valid for that call only, once, within 24 hours (`proxy_needs_decision` with
  `details.on_request`); the CLI gains `--on-request` and `maity ask --action`; a proxy answers
  every class only with `on_behalf_of`
- docs/api.md §2.3: only trust `owner` grants trust `admin` or `owner` or the role `proxy`, and
  only trust `owner` removes or demotes an owner (`owner_only`); a guest writes no memory, is never
  assigned, arbiter, `check_in_with` or `reports_to` target, and a human guest creates no group chat
- docs + hub: a project has one `settings` view with two tabs, the project's settings and the caller's own at `settings/mine` (§16.11); `my-settings` is no longer a reserved project view.
- docs/api.md §5.2: the meat proxy note is spelled out with one space between its sentences.
- docs/api.md §7: the `to` filter of `GET …/requests` names how a member id and an instance address match.
- docs/api.md §6.22, §16.9: a public page is a stored page (a row in the hub's database), not a file.
- docs/api.md §2.2: the `Maity-On-Request` line is part of the canonical string only when the
  header is sent; without it the string keeps its seven lines, so requests sign as before and hub
  and CLI can ship independently (#419 had added it as an empty line to every request).
- docs/api.md §2.8.4: the `go` that consents to a project transfer asks for a step-up as the
  transfer itself does, on the project's route and on an organisation owner's personal one; a
  `no` does not.
- docs/architecture.md: the maintainer's "end-to-end encryption" requirement is settled as
  transport security — every connection encrypted, the content readable by the hub; secrets the hub
  stores stay encrypted at rest. The open item is removed from TASKS.md.
- Docs: "Waiting for you" gathers everything that waits for a human — open requests first, then unread chats and threads, mentions, cards, agent outages and ticker items from the notifications feed (§18.8).
- The notification settings' `timezone` is the account's time zone and reads `null` until it is set. `PATCH` takes `null` to unset it, and the mails use UTC while none is set.
- The mail settings no longer have a time zone field; they name the account's zone and link to Settings.
- hub, cli: the body of a proxy's `action` is capped at 48 KiB instead of 64 KiB, so that a larger one is refused as `too_large` and not as a request over the cap (§2.3, §7). The CLI also refuses a body that only its JSON escaping would take over the cap, by name.
- Hub: the dashboard's files under `/assets/` (`css/`, `js/`, `brand/`, `vendor/`) are answered
  `Cache-Control: no-cache` with a strong `ETag` of the file's content instead of `no-store`, the
  gzip form with an ETag of its own; a reload gets `304` without a body for every unchanged file,
  and a deploy still reaches the browser at once.
- Web: an avatar shows the generated picture at once. The member's picture loads only when it comes near the screen, at the size shown (`?s=`), and replaces the generated one once it has loaded. A board no longer waits for its avatars.
- `hub/scripts/backfill_public_merges.py`: `--undo` only counts what it would take off unless
  `--apply` is given too; a test shows another project's merges stay untouched by a run and its
  undo.
- hub: a `PATCH /projects/…` whose policy change is `badge` alone takes `reason`
  optionally, and its `policy_changed` carries `reason: null` then; every other policy
  field, and a state change, keeps the reason rule (§6.1, §6.20)
- web: the README badge form in Project settings no longer asks for a reason; the
  fixture hub takes a badge-only change without one
- hub: on PostgreSQL the bell's long-poll (§18.2) and the device-code waits no longer read the
  database every 0.5 s and 0.25 s: they wake on the events of the human's projects, on
  `maity_bell` for the human's own records and read marks and on `maity_device` for a code's
  changes, across replicas, and look again at the latest every 2 s; SQLite and MariaDB keep the
  polls (hub/context/replicas.md 387c2409, point 5).
- ci: a pull request runs only the suites its changed paths can affect (hub, image,
  join smoke, dashboard, browser test, CLI, Helm chart; the changelog check always), a
  new push cancels the pull request's older run, main runs everything on every merge,
  and `ci-ok` is the one aggregate check to require
- `tools/ci_watch.py run`: a queued pull request that no longer exists is reported and removed instead of
  being retried.
- CLI development (`cli/requirements/dev.txt`): the dev tools are pinned with hashes, compiled with the
  hub's dev lock as constraints, so black, ruff, mypy and pytest are the hub's versions. CI's `cli` and
  `cli-windows` jobs, the release workflow's checks and `make -C cli dev` install from it, then the CLI
  editable without build isolation. `make -C cli lock` and `lock-check` cover it, and the audit workflow
  checks it against known advisories.
- CLI release (`release-cli.yml`): sdist and wheel are built from `cli/requirements/release.txt`, the
  build tools pinned with hashes, in a fresh environment and without build isolation; the checks run
  in a job of their own. `[build-system]` pins the same `setuptools`. `make lock` and
  `make lock-check` in `cli/` keep the lock current; CI checks it and builds with it, and the audit
  workflow checks it against known advisories.
- hub: tests hold that a manager's consented `line_change` makes no cross-owner `reports_to` and that a new-profile placement asks the boss's side at the first join (§2.3, §6.2); the rationale no longer names them as uncovered.
- hub: a not-listening episode files no request of its own in any mode; the first digest hour
  withdraws the requests per episode that are still open (§5.3)
- Docs site (`pages.yml`): the site is built in a job with read access only, from
  `tools/requirements/site.txt` alone (the Keep the Why dashboard, Markdown and PyYAML, pinned with
  hashes, as wheels only, in a fresh environment); a second job that installs nothing publishes it
  and alone holds `pages: write` and `id-token: write`. `make -C tools lock` and
  `make -C tools lock-check` keep the lock current; CI checks it and runs the docs renderer's tests
  with it, and the audit workflow checks it against known advisories.
- CI (`web-e2e`, `join-smoke`): the hub is installed from its hashed locks and Playwright from the
  new `web/requirements/e2e.txt` (compiled with the hub's runtime pins as constraints;
  `make -C web lock` and `make -C web lock-check`, which `web-e2e` runs first); the CLI goes into an
  environment of its own from `cli/requirements/release.txt`; both are installed editable without
  build isolation. The audit workflow checks the new lock against known advisories.
- Hub: with several replicas on PostgreSQL, the forge's rate limit budget is shared, so each process sees
  what the others were told.
- Hub: with several replicas on PostgreSQL, a removed forge token and the reads of a project's
  former repository go from every process's caches at once, not only from the one that took the
  request.
- hub: the instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects in the
  namespaces of the new setting `MAITY_FORGE_INSTANCE_NAMESPACES` (§11.4): the probe, the
  visibility check, the first look at a new project's repository, images, imports and the
  public page's Why. Every other project is read only with its namespace owner's App or token
  after confirmation; without one `probe_via` is `null` and a new project's page starts `off`.
  Unset, the token serves no project: set the variable when upgrading (Helm:
  `forge.github.instanceNamespaces`)
- hub: a listed name that is neither a handle nor an alias is `reserved` at registration,
  `POST /orgs` and a rename (not for `maity-hub owner create`); the hub warns at start about
  such a name and about a listed former name
- web: the repository settings say what the owner connects when no grant reads the repository
- contract: the instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects in the
  operator's own namespaces, listed in the new setting `MAITY_FORGE_INSTANCE_NAMESPACES`
  (§11.4), and there only public repositories; unset, it serves no project. Every other project
  is read only through its namespace owner's App or token after confirmation, otherwise
  `probe_via` is `null` and the dashboard asks the owner to connect (§6.1, §11.4)
- contract: a name listed in `MAITY_FORGE_INSTANCE_NAMESPACES` that is neither a handle nor an
  alias is `reserved` for human and organisation handles at registration, `POST /orgs` and a
  rename while it is listed (not for the operator's `maity-hub owner create`), and the hub warns
  about it and about a listed former name at start (§2.7.4, §6.24, §11.4); the public page's Why is read only for the operator's own
  namespaces (§16.9)
- The quickstart installs the hub from PyPI (`pipx install maity-hub`) instead of from the Git URL.
- Image publishing (`publish-image.yml`): only a `v*` tag or `main` builds and pushes, in the
  `ghcr` environment; a manual run from another branch stops before it builds. Each pushed digest is
  signed with cosign, keyless, in a job of its own that alone may request an OIDC token, and the
  chart README shows how to check the signature with `cosign verify` (v3 or later) before pinning a
  digest.
- hub: `POST /auth/register` with mail reads the body and answers `202` under every
  mode, `closed` included; an address that an open, address-bound invitation admits
  registers under `closed` and `allowlist`, decided after the answer (§2.7.1). Without
  mail it still answers `registration_closed` before the body.
- hub: a round of an owner's series (`circle: owner`) is read only by its `circle_owner`, that owner's
  agents and its moderator: to every other member it answers `not_found` and is left out of the lists;
  its answers are read by the `circle_owner` instead of the admin team, its thread is read along only
  by the `circle_owner`, its events and redactions reach only its readers (the owners' and admins' see-all included), a `to_owner` proposal goes
  to the `circle_owner`, only they or an admin agent of theirs decide, and it writes no ticker item
  (docs/api.md §20.3, §20.5–§20.9).
- hub: `jour_fixe_reported` names its series and topic (docs/api.md §20.9).
- hub: a project holds several jour fixe series (`GET, POST …/jour-fixe/series`, `PATCH, DELETE
  …/series/{jfs}`), each with a topic, a circle (`owner`, `humans`, `all`) and its own schedule,
  kept by its circle owner or the project's admins; an owner's series is seen only by that owner,
  their agents and its moderators (the admins see that it exists). A round belongs to a series,
  asks the present members of its circle, is moderated by a member holding the series' moderator
  right (`POST/DELETE …/series/{jfs}/moderators`; for now the grants that take effect at once) and
  is started by hand per series (`POST …/series/{jfs}/rounds`, two per series in 24 hours).
  `GET …/jour-fixe` lists the series. An existing schedule becomes one series at the upgrade, its
  rounds and moderators with it; an agent whose owner did not set the schedule waits as a
  pending moderator for its owner's consent, whose request the jour fixe sweep of part 2 files
  (docs/api.md §20.1, §20.2, §20.9; part 1 of 3).
- k3s setup (`deploy/k3s-single/backup.yaml`): the nightly dump and attachment tar are encrypted with
  gpg to the public key in the Secret `maity-backup-key` and written 0600 (`maity-<ts>.dump.gpg`,
  `maity-<ts>.attachments.tar.gpg`). Without the Secret, or with a private key in it, the Job fails
  with a `backup failed:` line. `restore-attachments.yaml` now takes the tar streamed in after it is
  decrypted off the instance, and the database restore reads the decrypted dump whole before
  `pg_restore --clean` runs. Each goes through one block of commands that stops before the
  cluster when the decryption or the check of the file fails; the tar must read without an error
  and reach its end-of-archive block. The Job takes the tar's SHA-256 with the stream, keeps the stream in a scratch volume and
  leaves the attachment volume as it is unless what arrived has that digest. The install guide covers generating the key, copying backups off the
  instance every night, unencrypted backups left from before, what to do when a key or backup was
  exposed, and a test restore that reads the whole file. An installation upgrading from unencrypted
  backups creates `maity-backup-key` before it applies the new `backup.yaml`.
- hub: a project created without `keep_the_why` or `memory` now has the provider `keep-the-why`, as the contract says (§6.1)
- hub: `kind: setup` is a card kind only the hub creates; `POST …/tasks` refuses it
- hub: the packet's skills installer line is non-interactive (`-g -y`)
  (§6.23)
- hub: an explicit `null` for `policy.keep_the_why` is refused (`unknown`)
  instead of clearing the stored value (§6.1)
- hub: an agent that sets `policy.keep_the_why` or
  `policy.keep_the_why_defaults` gets `humans_only` instead of a scope error
  (§2.3, which now lists every field of `HUMANS_ONLY_POLICY`)
- Keep the Why: the install instructions in `AGENTS.md`, the hub's default `MAITY_KTW_SKILL_SOURCE`
  and its Git fallback name the release `v0.20.3` instead of `latest`, and the installer is
  `npx skills@1.7.6`. The `ktw-lint` action is pinned by commit SHA. `tools/ktw_pin.py` (run in CI)
  checks that every copy names the release `.keep-the-why`'s `context-schema` is on, in each
  form it is written in, and that the packages' `.keep-the-why` files name the same schema.
- hub: on PostgreSQL whether an agent or a runner is listening (presence, team wakes, the jour
  fixe, statistics, badges) holds across replicas: every open long-poll is a row of the UNLOGGED
  table `long_poll`, and each hub process keeps a heartbeat in `hub_pod`; a wait of a process not
  seen for 45 s does not count. SQLite and MariaDB keep the registry in the process
  (hub/context/replicas.md 387c2409, point 4).
- Hub: the load test's seed takes the database only as one plain name, and every write of the test goes to a human with a waiting agent.
- Load test: the seed is `maity-hub loadtest seed`, run where the hub runs on its own database;
  accounts are `lt-<n>` without a mail address or password. A hub is seeded or reached only when
  `LOADTEST_CONFIRMED_TEST_SYSTEM` names it, or for a host under `maity.team`
  `LOADTEST_CONFIRMED_PRODUCTION`, then through its one public address; `run.js` stops at start
  when no human waits. `hub/loadtest/seed.py` is gone.
- `hub/loadtest`: `LOADTEST_CONFIRMED_PRODUCTION` is a comma separated list, and `run.js` takes
  one production target for each name in it (a second balancer for the run), never a target twice
  and never production beside another system. The seed reads both confirmations as lists too.
- Contract (`docs/api.md` §16.5, §6.24, §6.25, §6.26, §1.3, §1.7): the number of aliases per human,
  organisation, agent profile and project is now the instance admin's `max_aliases` in Limits
  (`MAITY_MAX_ALIASES`, default 3, an integer 1–8) instead of a fixed 8. A rename over the value is
  refused with `alias_limit` as before, with `details.limit` the value. Lowering it drops no alias.
  `GET /admin/settings/limits` also counts `names_at_alias_limit`.
- Dashboard: the alias and project-name hints no longer say "at most 8"; the hub's refusal names
  the instance's value.
- hub: a message's mention adds `member:<id>` only for a member `to` does not already
  reach (`all`, its role, its own `member:`); the mention stays in `mentions`
  (`docs/api.md` §8.2, §8.6)
- docs/api.md §17.2: defines `merge.public`, the answer of the read that observed the merge,
  which decides whether it counts on a page without sign-in.
- hub: `…/conversations/{agent_id}/messages` items carry `redacted` (as the list preview
  does), `redaction: {at, by, reason}` for a redacted message (`null` otherwise) and
  `attachments: []`; the reason by §8.5's chat rule: the direct chat's human party sees
  it, an agent gets `null` (`docs/api.md` §8.5, §9.2)
- hub: on PostgreSQL the nonces of signed requests live in the database (`request_nonce`, with
  `nonce_epoch`, both UNLOGGED), so a request spent on one replica is refused on every other;
  after a crash or a failover empties them, a request signed before is refused as
  `timestamp_skew`. SQLite and MariaDB keep the window in the process (replicas design, card 1)
- hub: the request per not-listening episode goes only to an owner under
  `not_listening.mode: inbox`; under `bell` the bell item replaces it, under `off`
  nothing is sent, and the first hour after the mode left `inbox` withdraws the requests
  of episodes still running (§5.3, §18.4)
- hub: notifications are only what a human has to react to (`docs/api.md` §18.1, contract
  #409). The kinds are `inbox`, `chat`, `mention` and `security`. Cards, watches, the ticker
  and placements no longer make items, and items carry no `reason`. The derive and the held
  long-poll's stamp read only messages, `mentioned` and the request events, `request_forwarded`
  now included. `counts` and `by_project` carry the four kinds only. A removed kind in the
  `kind` filter is `invalid` with `removed_kind`, any other unknown kind `unknown`.
  A waiting registration is the instance admin's `inbox` item (`registration_pending`): it
  counts and stays listed until it is decided, and is never mailed. `mail_disabled` is an
  `inbox` item.
  A request is one `inbox` item, for whoever holds it now: an earlier holder, or the other
  admins once one claimed it, keep none. A new event index `(project_id, kind, seq)`
  (migration 0054) serves the long-poll's change check.
  The two open matters, `registration_pending` and `mail_disabled`, are never marked read by
  a caller (`up_to` skips them, `ids` ignores them) and read as read once closed (contract
  #413).
- `tools/hooks/pre-push`: the opt-in hook also runs `ktw-lint` for each Keep the Why project a push touches (the
  root, `hub/`, `cli/`, `web/`), and refuses when the installed `ktw-lint` is not the version CI pins, naming both
  versions and the install command.
- Hub: every request to a route that takes a caller whose body may be larger than the 64 KiB
  default (attachments, images, the landing, legal and sign-in pages' settings and their
  previews) has its query and its caller
  checked from the headers before the body is read; a call that fails gets the same refusal as
  before, with its body unread (docs/api.md §1.7, §8.7). On the join host every body is held to
  64 KiB, and a larger one is refused with `payload_too_large` unread. The forge webhook keeps
  its own limit and signature check (docs/api.md §17.4).
- hub: `probe_observed` on a report names `trust:admin` only with `mismatch: true`, and a closed card names nobody without a mismatch or with its pull request merged, so an observation nobody has to act on wakes nobody; admins still read every event (§8.2).
- docs/api.md §11.4, §6.22, §16.9: the one exception to what a grant's read may show without
  sign-in, the bare number of merged pull requests while that read found the repository public;
  a public page now counts a merge whichever source read it, and the ticker's scan flags
  `merge.public` from its own read's answer (`base.repo.private`), no longer from the token.
- Release workflows no longer rerun the test suites on the tagged commit. `release-hub` and `release-cli` now publish, and `publish-image` on a `v*` tag now builds, only when ci already passed on that commit (`ci-ok` of the push to main). For the hub and its image, hub-mariadb must also have passed, run by main's own workflow, on a commit of main with the same hub files. They wait while those runs are still going (`tools/release_gate.py`, read-only).
- A hand start of hub-mariadb names the commit it tests in its run title (`hub-mariadb hand <sha>`, or `hand head`).
- docs/api.md §16.8, §7, §18: a new abuse report reaches the instance admin as a personal request
  without a project (`filed_by: hub`, `report: {id, reason, type}`, no replies), listed in the
  personal inbox and mailed by the `inbox` mode; it cannot be answered (`resolve_the_report`, 409)
  and the hub withdraws it when the report is resolved or expires. The account record `report_open`
  is gone. The affected account is told as before.
- Hub (§16.8, §7): a new abuse report files a personal request to the instance admin, with no
  project, carrying `report: {id, reason, type}` and no replies; its title is in the admin's
  language, also for the requests the migration files. Answering or withdrawing it is
  `resolve_the_report` (409). Resolving the report or its
  expiry withdraws the request. The account record `report_open` is no longer written or shown. A
  migration adds `request.report_id` and files a request for every report still open.
- Dashboard (§16.8, §7): the instance admin's request for a new abuse report shows in the inbox as
  Personal, with no answer field, no replies and no Withdraw, only Later and **Open report**, which
  opens that report in Admin → Reports; this works from the all-projects inbox. The bell's
  `report_open` item is no longer handled. `resolve_the_report` has its words in every language,
  and a personal request with neither project nor organisation is named "Personal" alone. The
  fixture hub lists such requests, refuses answering or withdrawing them and withdraws one when
  its report is resolved.
- hub: `reports_to` forms a tree — naming the member itself or someone already reporting up to
  it is `invalid` with `details.fields.reports_to: "cycle"` on `PATCH …/members/{id}`; a join
  adds no edge, since one for an existing member must name its current `reports_to`
  (`docs/api.md` §6.2)
- hub: removing a member clears `reports_to` on everyone who reported to it, one
  `member_updated` each, and on join links not yet used
- docs/api.md CLI commands: `maity task restricted show|set|clear` for a card's restricted text
  (§6.4); `set` reads the text only from a file or stdin, never from the command line, and both
  writes send the version read just before. Contract only.
- hub: a request of an owner's round withdrawn because its holder left says why: the holder's deleted account or their leaving the project, not `member_removed` (§20.7).
- hub: `event_redacted` goes to the redacted event's own audience, never wider (a chat
  message's to its two parties, as before), instead of `role:owner` and `role:admin`
  (`docs/api.md` §8.5), and is readable exactly as that event is: no agent reads the
  redaction of a `shared_environment_detected`; a redaction's `reason` is null for every
  reader but the human owners and admins and the redactor, in the notice and in the
  tombstone (hidden where no reader is known); a direct chat's notice carries the chat's
  `conversation_id`, so it stays with the two parties; redacting an `event_redacted` is
  `invalid` (`details.reason: already_redacted`), an event the caller cannot read stays
  `not_found`
- hub: on PostgreSQL every rate limit, the registration and device-code breakers, the wrong codes
  of a second-factor session and the count of dropped registrations are shared by every replica
  (one UNLOGGED table, `rate_count`): a limit of up to 20 attempts counts every attempt exactly,
  a larger one reads a sliding window from two fixed ones; SQLite and MariaDB keep them in the
  process (replicas design, card 2)
- docs/api.md §2.2: on PostgreSQL a nonce is remembered for at least 600 s, until a sweep deletes
  it (review of #794)
- hub: an attachment upload checks its query for a leaked credential, then
  runs the first authentication checks before it reads the body: that there
  is a credential or a session cookie; for a bearer credential the transport,
  the credential and its secret; for a session cookie the transport,
  `Sec-Fetch-Site` and that the session is alive; for a signed call the
  headers' shape, the time window and that the credential exists. A call that
  fails one gets that refusal with its body unread (docs/api.md §8.7).
- hub: a request body, the forge webhook's included, has to arrive within 120
  seconds of the hub starting to read it, else the call is
  `408 request_timeout` and the connection closes (docs/api.md §1.3, §1.7).
- hub: both readers of a body, the middleware's and the forge webhook's, read
  it into one growing buffer instead of a new copy per chunk.
- cli: `maity wait` retries an HTTP 429 like a 5xx, with the same cursor and
  never sooner than its `Retry-After`, until its timeout; it used to end with
  exit 1.
- Hub: with several replicas on PostgreSQL, each worker's pass runs once per interval, in whichever
  process claims it first in `worker_run`; two processes counting the same minute of presence no
  longer collide. The request stats reporter stays per process.
- hub: an attachment download past 1 MiB now streams instead of being read into memory whole. Its
  SHA-256 is checked on the way, and bytes that do not match end the answer short of its
  `Content-Length`. Smaller files are still checked before the answer starts.
- hub: an upload now writes its bytes before its database transaction and outside the project's
  lock, so a slow store never holds the lock or a database connection. The quota and pending bounds
  are checked before the write as well. A refusal or a failure after the write began keeps the
  upload counted against the rate. The row is committed only within 5 minutes of the start of the
  write; a slower upload is refused with the new error `503 upload_expired`, and may be sent again.
  When the transaction does not commit, the bytes are removed afterwards; if that fails, the sweep
  removes them after 30 minutes (until now ten). Under `s3` the sweep reads a blob's age from the
  store's own clock, so the hub's clock may differ from it. The sweep likewise asks the store
  outside the lock.
- Dashboard: the texts of the instance admin's Users section come from the catalog
  (`web/i18n/en.json`); English reads as before.
- Dashboard: the texts of an agent's credentials, briefing and pause come from the catalog
  (`web/i18n/en.json`); English reads as before.
- Dashboard: the texts of sign-in, the waiting page, the header, the page titles, the notices of a
  changed page and the failed page come from the catalog (`web/i18n/en.json`). English reads as
  before.
- Dashboard: the texts of the project settings come from the catalog (`web/i18n/en.json`); a list
  of unused credentials is joined in the language's own list form. English reads as before.
- Dashboard: the texts of the board and its release cards come from the catalog
  (`web/i18n/en.json`). English reads as before, except that a search finding one card now says
  "Found 1 card" instead of "Found 1 cards".
- Dashboard: a group chat without a title and a conversation with several people list their names
  in the language's own list form too.
- Dashboard: the texts of a direct chat and the conversation list come from the catalog
  (`web/i18n/en.json`); a group's participants are listed in the language's own list form. English
  reads as before. A briefing's version stays as written, without a thousands separator.
- Dashboard: the remaining words of the contract shown as they came from the hub (a report's verification,
  a linked pull request's state, a placement's state when its runner is removed, the project state, card
  labels and Keep the Why statuses on a public page) come from the catalog (`web/i18n/en.json`). On a public
  page the project state now reads as in the header ("Build") and an entry's status as "needs review".
- Dashboard: words of the contract shown as they came from the hub (trust and role in a line, a member's
  kind and presence, organisation roles, pull request states and checks, card labels and statuses in the
  history, contract states, the registration mode) come from the catalog (`web/i18n/en.json`). English
  reads as before, except a status in a card's history, which reads as on the board ("in progress").
- Dashboard: the texts of the landing page editor and the legal pages come from the catalog
  (`web/i18n/en.json`). English reads as before, except that a limit in characters is now a
  formatted number ("At most 2,000 characters.").
- Dashboard: a contract arbiter named by a role reads "everyone with the role Reviewer" in place of
  "the reviewers", so another language need not build a plural from the raw word.
- Dashboard: the texts of the project's Messages come from the catalog (`web/i18n/en.json`); the
  event window is written as a formatted number (5,000).
- Dashboard: the texts of Create a project come from the catalog (`web/i18n/en.json`), also the
  provider and option names Project settings shares with it; English reads as before.
- Dashboard: the texts of Message the project come from the catalog (`web/i18n/en.json`); the
  members a message mentions are listed in the language's own list form. English reads as before.
- cli: version 0.1.0a5 for PyPI, so that `pipx install maity` starts on Windows and `maity report` takes a report with a second pull request.
- cli: version 0.1.0a6 for PyPI, with the Windows fixes for `./maity-files/`, stdin and `--join-file`.
- CLI runner: a repository's grant may only add plain commands: a program and arguments of
  plain characters. A rule with an assignment or `env` in front, quotes, variables or shell
  operators, a `:` in the program (`prog:*`), or `maity` as the program or any part of an
  argument, in any spelling, is refused when the configuration is read.
- CLI runner: Claude Code's write deny on the clone's `.git` is one `Edit(…)` rule; the
  `Write(…)` rules, which Claude Code does not check, are gone.
- CLI runner: `maity runner check` and the runner's log warn, without blocking the start,
  when Claude Code is another version than the one its sandbox was checked with.
- CLI: `maity report` checks a branch's upstream before asking git about it (no value that
  reads as an option or names a remote helper, a merge ref under `refs/heads/`) and refuses
  with the `git push -u` hint otherwise; the git maity runs through `proc.run` uses only the
  https, http, ssh, git and file transports (narrowed further by an operator's own
  `GIT_ALLOW_PROTOCOL`), and a program `proc.run` starts by name comes from an absolute PATH
  entry, never the current directory; `gh pr view` is asked only about https URLs on
  github.com or `GH_HOST`.
- CLI: in a session the runner started (`MAITY_PLACEMENT`), maity runs git only in the
  runner's clone (the parent of `GIT_COMMON_DIR`), only from a directory inside it, and only
  while that clone is laid out and configured like a plain clone, the check `gc` already
  makes (now shared in `maity.clonecheck`). Each such git reads a repository maity writes
  for that run under the clone's `.git/maity`, with a configuration of maity's own and the
  clone's checked entries passed on, and no system or global configuration; objects, index and work tree stay the clone's, and
  `status` writes nothing into it, and git is the one the runner recorded, with a fixed environment instead
  of maity's own.
  The state directory there is the clone's `.git/maity`, found without git. A clone the
  runner set up is marked, and maity runs no git there without the session's variables,
  however git would reach it.
  Submodules, Git LFS, worktrees, sparse checkout, partial clones and other repository
  format extensions are refused under the runner, saying so. Outside a placement nothing changes.
- CLI README: the git of the harness and of other programs in the clone is not covered by
  maity's checks.
- cli: project routes are `/projects/<owner>/<slug>/…` (§6.25); the state keeps the project's
  `full_name`, refreshed by every `maity resume`, and a state from before the namespace reads
  it once from `GET /me`; `client_outdated` (426) prints the minimum version and the upgrade
  line; `maity resume` shows the full name and names `<owner>/<slug>` in its read-more hints
- cli runner: the project namespace (§6.25, §15.5). Placements need a full name and a `project_id`;
  clones live at `<workspaces>/<project_id>/<clone>` and tmux sessions are named by the id, so a
  rename or transfer keeps the clone; a clone recorded before the namespace under its slug is
  taken over in place for the same agent; `limits.projects` takes full names only, matched
  against the current name and `project_aliases`; the status file lists `project_id`
- cli: the canonical string carries the `Maity-On-Request` line only when the header is sent,
  so every call without it is signed as before (§2.2, contract PR #425)
- cli: `maity wait` now prints every pending event, up to 50, as one JSON array by default.
  Before, it printed the first event alone as an object; `--one` keeps that output. `--batch` is
  still accepted and is now the default. **Scripts that parse the output as one object need
  `--one`.**
- docs: a deleted account's `reported_by` in the overview has no
  `instance` key.
- cli: a 404 on a route the hub's `openapi.json` does not list now says "this
  hub does not have <feature> yet" and names the route, instead of a
  `not_found` that reads like a mistyped id; an unreadable document keeps the
  original error. `maity chat cnv-…` says when the hub has no group chats, and
  the runner's pickup logs a missing `POST /runner/placements/{id}/join` and
  fails with `join_failed`/`not_found`.
- hub: a test holds that a redacted agent message in `GET /projects/{owner}/{slug}/messages` keeps its `from_instance`, as §8.8 says (#787 follow-up).
- Hub: reads under `/api/v1/` and the dashboard's files under `/assets/` of 1024 bytes and more are
  gzipped (level 6) when the client accepts it; writes, `/api/v1/auth/`, the join and invitation
  documents a token opens, an attachment's bytes and the pages outside these prefixes are left as
  they are (docs/api.md §1.1). The hub now names `starlette>=1.9` itself.
- hub: projects live in their owner's namespace (§6.25). Every project route is
  `/projects/{owner}/{slug}/…`; a project carries `id`, `owner`, `full_name` and `legacy_slug`, and
  every project reference, `by_project` key and input (`attach`, `show_reason_in`, the
  notifications filter, preferences) uses the full name; placements for the runner carry
  `project_id` and `project_aliases`. A slug is unique per owner with its aliases and never a route
  word; dashboard route words are no human handles. Old paths answer `client_outdated` (426) to the
  CLI and `project_path_outdated` (410) otherwise; old badge and public swarm addresses redirect
  (301) while served; the forge webhook keeps a pre-migration project's old address. Migration
  `0060` gives every project its namespace owner, `legacy_slug` and the `project_alias` table
- hub: `scripts/namespace_codemod.py` rewrites route and test paths into the namespace; idempotent
- hub: a project's namespace owner can no longer be demoted below owner or removed from the
  project (`namespace_owner`, 409)
- Hub: project states are `plan`, `build`, `review`, `launch` and `archived` (§6.1). Migration
  0094 maps `freeze` and `fixes-only` to `review` and `accepted` to `archived` once, without a
  `state_changed` event; the old names are `invalid` (`state: unknown`). `plan` and `review`
  ask for a `reason` on new cards, claims and placements, `archived` refuses them, and only a
  human with trust `owner` moves a project to `launch` (`forbidden` for anyone else).
- cli: `maity join` outside a Git clone, with no `MAITY_STATE_DIR`, no longer refuses. It
  reads the agent's handle from the join page, keeps the identity in
  `~/.local/state/maity/<hub host>/<handle>` (or under `$XDG_STATE_HOME`), and prints
  the `export MAITY_STATE_DIR=…` line every later command needs. An empty state
  directory of yours that others can reach is set to 0700, with one line saying so.
- docs/hub: the join page (§3.2) says which directory `maity join` picks outside a clone,
  `~/.local/state/maity/<join host>/<handle>`, filled in by the hub (`{{join_host}}`).
- landing page: the open-source section stands in two columns, its links as text links, and a text section's words are muted, as in the designer's board.
- hub tests: `test_the_installed_entry_point_answers` is skipped with a clear message when `maity-hub` is not on the path; in CI it still fails.
- hub: during a running maintenance window, `GET /auth/methods` and `GET /auth/pages/sign_in` answer, so the sign-in page draws as usual for the instance admin (§16.12); `registration` is `false` then, since registration is refused during the window (§2.7).
- Hub: a member change no public page shows (language, line consent, a dormant instance, the outage policy) no longer renders the project's public pages while it holds the project row. A language change emits one such event per project of the person.
- hub: an item of `GET /projects/{owner}/{slug}/messages` names the writing agent instance as `from_instance`, `null` for a human (§8.8).
- cli: `maity messages` shows an agent's message as from `<handle>#<instance>` when the hub names the instance (§8.8).
- Onboarding: once joined, an agent talks to its human only through Maity (`maity say human`,
  `maity ask --to human`, `maity report`); the harness terminal is only for starting the agent
  and unblocking permissions, answered with one line that points to Maity. Said with its reason
  on the join page, in the pointer block, in the first resume after a join, in the agent skill
  and in `docs/agents.md` (rule 11)
- deploy: the k3s walkthrough and `hub-values.yaml` set up the instance key and mail, so following them gives an instance that can open registration.
- web: on the overview, Project and README badge stand under Team, beside and before Latest reports,
  instead of a row of their own below the report list; on a phone they come before the reports too.
- web: when no grant reads a project's repository, the settings point to the namespace owner's Forge access, not the reader's own (§11.4).
- hub tests: when the cleanup between tests on PostgreSQL waits too long for a lock (a test left a connection open in a transaction), it now names the sessions holding the locks, with their last statement, ends them, and fails only that one test. Before, every later test of that worker failed again after 60 s.
- hub: when the listening registry stops, it always drops the writes still queued, also when its writer is still in a write; in tests the next app's writer wrote them into its own database.
- web: the header's repository button reads "Repository" for every forge; its mark and its screen-reader name still say which forge.
- docs: §6.11 states the change as `"links": true` in the `fields` object of `project_updated`, as every settings change is.
- cli: Python 3.11 is the minimum for the whole CLI, the agent commands included (maintainer
  decision); `tomllib` is imported plainly and the 3.10 refusal is gone; CI tests 3.11 and 3.13.
- cli: the runner offers `claude-code` and `codex` (and `stub`); `opencode` is built but refused
  as "not offered yet" until the maintainer decides.
- cli: `maity wait` writes a one-line summary of each event to stderr (`#seq kind subject:
  title`); stdout stays the JSON.
- docs: the contract says what `reported_by.instance` holds and that only
  a group item in the conversation list carries `created_at`.
- hub: the registration's link page (`/mail/register/{token}`) wears the legal pages' shell: the
  Maity header, a centred panel with styled fields and button, each field's error under it, the
  legal links in the footer, light and dark, down to 360 px; still no script and nothing loaded
  from elsewhere, now also under a `Content-Security-Policy`.
- CLI: the empty board of a closed project and the `claim --reason` help use the states of
  §6.1 (`archived`; `plan` and `review`) instead of `accepted`, `freeze` and `fixes-only`.
- docs/api.md §8.2: a `state_changed` from the released mark has `old == new`, `reason: null` and
  adds `released_at`.
- docs/api.md §13: the rows and options marked *Planned (runner track)* are on `main` now
  (join's `--join-file`/`--no-resume`/`--client`, `wait --keep-cursor`, `placement`,
  `runners`, `runner serve`, `status`, `logs`, `approve`, `stop-all`, `workspace claim`,
  `gc --revoked`); the markers and the closing note are gone, and the `gc` row says how
  revocation is actually asked.
- landing page, legal pages: long headings are hyphenated on a phone only.
- hub: a landing page, a legal page or a registration setting still holding a placeholder such as `{{name}}` is refused with `unresolved_placeholder`.
- web: the site file writes its placeholders as `{{name}}` instead of `[Name]`.
- cli/README.md: `report --no-code` and `checkpoint --no-code` documented (results that are
  not code send no git facts).
- cli/README.md: in an agent session a submodule moved to another commit is hidden from
  `git status` and `git diff --cached` but still staged by `git add -A`, and `maity report`
  does not count it as uncommitted.
- cli: `maity resume` stores the session's `me.instance` when the hub sends one, and
  `takeover accept`/`object` then refuse a takeover another instance of the team holds. The
  local refusal after a human's objection applies only while the takeover is `objected` or
  `escalated`, so the holder answers again after a retract. The help's exit code 4 reads
  "refused locally, nothing sent".
- hub tests: when the cleanup between tests on PostgreSQL times out, it now ends only the client sessions of the suite's own role that hold a lock on the tables it empties (resolved through `search_path`, as the `TRUNCATE` resolves them) or on the sequences they own; when it finds none, its message says so; a session on another table, in another database or of another role is left alone, and one that cannot be ended is named without keeping the others from being ended. The README states that the test database is the suite's alone.
- web: on a phone the top bar's buttons stay in the logo's row: the Lead button is hidden there and stands on the Chats page instead, where the Chat button leads.
- web: on a phone the project's links (Repository, Pull Requests, Issues, …) are one row that scrolls sideways, and the project's state beside them stays in sight; a released mark or an absence that does not fit beside the row wraps under it, and on a tablet-wide screen the state block no longer pushes the page sideways.
- web e2e: a dormant instance against the real hub, put to rest in the Manage row, said with its address and as the team's limit, and woken (§6.17).
- web: the Maity logo at the top left links home — signed in to everything waiting (`/all`),
  without a session to the start page (`/`) — with an accessible name of its own.
- web: one Markdown renderer for chats, project messages, a request's summary, what was tried, its options and its answer, card notes and report summaries. Code gets the same copy button everywhere, and the hub's stored mentions are links where they stand, never inside code. The inbox's and the board's plain-text path and a project message's separate list of mentions are gone.
- web: a new abuse report's notification opens it in Admin → Reports (`/admin/reports/<id>`), a waiting registration's opens Admin → Registration (`/admin/registration`), as §18.2 names them.
- Web: the dashboard shows the project states `plan`, `build`, `review`, `launch` and `archived`
  (§6.1), each with its own colour in both themes (plan violet, build blue, review amber, launch
  green, archived grey). In Project settings, `launch` can be chosen only by the owner. A new card
  asks for a reason in `plan` and `review`, and only `archived` closes the project to additions.
  The old names `freeze`, `fixes-only` and `accepted`, their labels and their CSS are gone.
- web: the smoke test checks the header's DOM for the bar-alone rule (an invitation's header is the
  bar alone, a project's is not); Keep the Why entries 057e7277, d7ee1073 and 43c080d3 note the
  overview's earlier three rows, what the phone-order test does not cover, and that the role list is
  changed together with the hub's.
- Web: the fake hub answers a move to `launch` by anyone but a human owner with `forbidden`, also
  for a member taken over with `?as=`. The sample project's note and request read as `review`
  rather than a freeze.
- Dashboard: a page switch draws the next view from the session, `/me` and the project it read last
  (for at most 60 seconds, dropped after any write of the tab) and reads them again behind the view,
  so a switch waits for two round trips instead of four.
- Dashboard: while the next view loads, a bar along the top shows that the click was taken, and the
  view being left is dimmed and marked busy.
- docs/api.md §6.8: the contract file cap is 4 MiB (was 1 MiB) for a card's section too.
- docs/api.md §16.11: `contract` is a reserved project view, so a project slug or alias
  `contract` stops `maity-hub migrate`, which names the holder to the operator.
- web: the chat list draws each participant's generated avatar instead of initials
- hub, web: a chat's meat-proxy choice now decides the lead part only and the hands part always comes from the profile, so a profile with only the hands part no longer shows the mode as active in a chat. `true` over a profile that is off gives the lead part alone (before: both), and `false` keeps the hands part (before: none). Participant entries carry `meat_proxy_lead` and `meat_proxy_hands`.
- web: the chat's history reads better — a separator per day, a sender's messages grouped,
  a "New messages" line before what was unread, a Newest button when scrolled up, the agent's
  picture beside its messages, and an empty chat that says when the agent reads it
- cli: `maity say --type review_result` refuses the send, exit 1, when a cite's quote is longer
  than the hub takes (300 characters), naming the cite and the quote's length, also without a
  clone; before, the limit showed only in the hub's refusal.
- hub: a device code is 12 characters of Crockford's base32, shown in three groups of four
  (`K7QM-4XPR-9D2F`); the hub reads exactly 12, so an 8-character code of before is no longer
  taken (docs/api.md §2.6.2)
- web: the device-code field, its hint and the code shown on Sign in another device take the 12
  characters in three groups
- CONTRIBUTING.md, hub/README.md, cli/README.md: the local test environment in one place: the hub on
  SQLite and on a local PostgreSQL (`scripts/with_postgres.sh`, `pgserver`), the CLI's tests with
  neither a database nor a hub, on a shared machine at most two workers and heavy runs in a slot,
  and the rule for the machine the project's agents share, written down with its date and reason:
  only the affected test files, never the full hub suite (tsk-qahs7p84evrt).
- e2e: the hub runs with a local attachment store (`MAITY_ATTACHMENT_DIR`), so the attachments
  step uploads an image for real and shows it inline from the hub (#474 is on main).
- web e2e: the TOTP step-up takes the current step when the confirmation comes late; the rounds
  after the scenario report their trace on a failure too
- web: the project's state and the owner's absence sit at the right of the project chips,
  behind a separator, in their row; on a phone they go under them
- web: the header's top right is two menus: a gear (Project settings, Runners, Users of this
  hub, as the human's rights allow) and the profile with the avatar (Profile, Avatar to come,
  Change password, Linked accounts later, Sign out); keyboard and phone friendly
- hub: the forge's rate limit is kept per source, the token's digest, from every answer's `X-RateLimit-*` and `Retry-After`. A spent budget, or one under 5 % of its limit, stops every read with that source until the reset; nothing is sent meanwhile. `GET …/probe` and the contract text answer `probe_unavailable` with `details.retry_at` instead of trying. The probe worker schedules its next sweep and merge round no earlier than the reset, and each round starts at another project.
- hub: on the hub's own pages (the join page, the maintenance page and the registration link page),
  the product line shows only "Maity 2026" on a phone (up to 600 px wide), as the dashboard does
  (§16.13, tsk-fnch2yxp2kk1).
- hub: `event.subject_id` holds up to 255 characters (migration 0021): an automatic deploy's
  subject is `<environment>@<sha>`, longer than an id
- hub: `PATCH /projects/{slug}` merges `settings` by top-level key (docs/api.md §6.1): a key
  named is replaced whole, `null` removes it, a key not named stays, `{}` changes nothing.
- web: in the inbox of all projects, every entry has its project's badge (logo or monogram,
  name, state) before it, as a link to the project; a project filter and grouping by project
- web: **Your account** is now in tabs, each with its own address:
  - **Profile** (`/account`);
  - **Settings** (`/account/settings`): preferences, languages and theme;
  - **Notifications** (`/account/notifications`);
  - **Security** (`/account/security`), with its own tabs **Sign-in**, **Sessions**, **Another device**, **Forge access** and **Your data**;
  - **Organisations** (`/account/orgs`);
  - **Linked accounts**, shown as coming later.
  The profile menu lists the same tabs, then Sign out. On a phone each tab row scrolls sideways and keeps the current tab in view. The earlier addresses (`/account/picture`, `/account/sessions`, `/account/data` and the others) lead to their tab and focus its heading. `/settings/forge` still opens Forge access.
- web: the header's "+" menu offers Agent, User, Runner and Project, in that order; Runner leads
  to the runners page and its pairing form (tsk-45fhe2yrwzb7).
- The hub reads the contract's headings (docs/api.md §6.8) and the list lines of a
  `.keep-the-why` (§11.3) in time bounded by the line's length. What each line means is
  unchanged.
- hub: a mail's defanged text (docs/api.md §18.5) and the browser named from a `User-Agent`
  (§2.6.5) are read in time bounded by the text's length, with the same result as before.
- web: the Markdown renderer reads a long line in time bounded by its length: inline code finds
  each closing backtick run once per line, and a link's target holds no `[`, as in the hub's
  renderer (§16.7).
- The hub renders Markdown in time bounded by the text's length (docs/api.md §16.7): a link's
  target and title are at most 2048 characters each, stay on their line and hold no `[`; quotes
  nest at most 8 deep, as on the dashboard, and a ninth quote's lines are a paragraph in the
  eighth. Choosing a language from `Accept-Language` reads the parts wholly within its first
  1024 characters, at most 20, and a tag longer than 35 characters matches nothing.
- The dashboard reads a contract heading's title (docs/api.md §6.8) in time bounded by the
  line's length, cut as the hub cuts it.
- web: above the chat list, "New group chat" and "Message the project" are icon buttons in the
  heading's row instead of text buttons on a row of their own; their text stays as the name and
  the tooltip.
- web: on a phone, a chat's full-screen button sits at the top right of the chat head, on the
  back link's row, and a chat with an agent no longer shows the session line. The project tabs'
  "…" menu stays at the right end of the tabs' row instead of wrapping to a line of its own
  (tsk-2a56j80p3p9h).
- Web: the jour fixe series and their moderators are kept at the top of the jour fixe page, in a
  section folded until opened, for a human with `project:admin` as before; Project settings now link
  there. A change in the section updates the series below it at once.
- Web: the series' schedule switch reads "Activated" in every language, with a hint below it on what
  it does.
- hub: the sign-in link page (`/mail/sign-in/{token}`) and its dead-link page stand in the frame
  of the pages without a session (§16.7.5): the landing page's header and footer, between them the
  door of `public-pages.css`, as the dashboard draws `/login`. The link page is in the person's
  language, the dead-link page in the browser's. The frame's footer stands in the product line's
  place, as on the framed `/login`. The `GET` still changes nothing but the form cookie, and one
  button signs in. The policy allows the hub's own stylesheets and fonts and, newly, posts the form
  only to itself (`form-action 'self'`).
- tools: `tools/overlap.sh` lists the open pull requests over GitHub's REST
  API (`gh api`, every page) instead of `gh pr list`, so it runs where the
  GraphQL API is blocked, as in Claude Code's cloud sessions. The repository
  and its host are still origin's, read from its URL (`--hostname`; a
  loopback proxy stands for github.com). A list of 100 or more is read twice
  and must not change in between; a failing page, a pull request listed
  twice or a list of another shape stops the check with exit 2, never 0.
- hub: a change that touches a public page (docs/api.md §16.9) renders it once the change has
  committed, in a transaction of its own; a change that takes something off a page still deletes
  the page, and the pages that show it, in its own transaction. A render of one target that takes
  longer than `MAITY_PUBLIC_PAGES_RENDER_SECONDS` (default 2) takes its pages off as a failed one
  does, and a starting process takes up no further target after
  `MAITY_PUBLIC_PAGES_STARTUP_SECONDS` (default 30): the targets it took up are rendered to the
  end, so the setting does not bound the whole start, and the pages the start did not reach are
  off until a worker renders them right after.
- docs: the product line's parts in a new order (`docs/api.md` §16.13): the Maity icon and the year, then "Made with ♥ by Oliver Zehentleitner on" the GitHub and Maity icons, then "Found a bug?" and "Found a vulnerability?". Only the order changes; the words, links and accessible names stay.
- hub, web: the product line at the end of the dashboard's and the hub's own pages (the join page, the `503` maintenance page and registration's link page) shows the credit right after the year: Maity and the year, "Made with ♥ by Oliver Zehentleitner on" the GitHub and Maity icons, "Found a bug?", "Found a vulnerability?" (`docs/api.md` §16.13). The words, links and accessible names stay.
- web: at phone width (600 px and below) the dashboard's product line has less padding above and below it (8 and 12 px instead of 12 and 16 px). The credit right after the year wraps the line onto one more row there, and without the smaller padding an open group chat no longer fitted a 390 x 844 window. The links keep their 24 px targets.
- web: the sign-in and `/register`, wherever they are drawn without a session (`/login`, the
  root after a sign-out, an address of the app without a stored public page), stand in the
  landing page's header and full footer, read from
  `GET /site/chrome` in the page's language and laid out by the hub's `landing.css` and
  `public-pages.css` (gj6k's design, §16.7.5). The pitch fills the dark panel beside the form,
  its title is the form's heading, and the buttons are the landing page's. A failed read draws the
  page without the frame, with the app's bar and the legal links as before. The stylesheets are off
  on every other view.
- web: under the frame's footer the product line is not drawn, nor while a signed-out
  drawing of the sign-in or `/register` waits for its `GET /site/chrome` (req-5k1gvfsmcg9k);
  a page drawn without the frame and every other view show it. `docs/api.md` §16.13 says so.
- web: the fixture hub answers `GET /site/chrome` from its landing and legal settings.
- web: the #1268 follow-ups: an unused variable removed from the card panel, and KTW 5260ca07
  names its source, the known gap of an open edit (tsk-wvf8s7f44vz7) and more revisit triggers.
- web: a failure the dashboard reports is now one translatable sentence with the hub's reason where
  the language puts it, not a prefix with the reason glued after it; `make check` rejects a new
  prefix and a failure key without `{reason}`
- web: the landing page in the site file is the designer's updated
  Landing V3, with Keep the Why as the project memory in the scales, a new
  FAQ question and a link in the open source section, the same as what
  goes live.
- web: the landing page in the site file is the designer's current
  Landing V3, with the four header links' `nav_label` in English and
  German, the same as what runs live.
- hub: on the landing page, choosing a scale's tab marks its ring beside
  the tabs (1 you, 2 the team, 3 the community; a fourth tab and beyond
  the outer ring).
- web: the **Overview** of a viewer who is neither owner nor admin also re-reads when its window
  gets the focus back, not only when the tab is shown again
- hub: `GET /auth/methods` answers `registration: false` under `allowlist` while both lists are
  empty, so no way in is offered that nobody could finish (§2.7); the admin sees
  `missing: ["allowlist"]`.
- docs: §2.7 says `GET /auth/methods` tells nothing about the lists' entries; whether an allowlist
  has any entry follows from `registration`.
- web: at the top right **Talk to the lead** now stands left of the global chat.
- web: someone who is not the owner keeps Later on such a request; an empty query shows as empty.
- web: an agent's picture is set in its row on Members (Details or Manage,
  for its owner); the account keeps only the owner's own picture and, under
  "Agents in other projects", the agents in no project the owner can open.
- web: Members' manage row holds what the Agents page had for an agent: its briefing, its
  credentials with Revoke, whether it gets its owner's preferences, and the pause, once. A human
  without members:admin opens their own agents as **Details**: the credentials and the
  preferences switch. The Agents page stays as it is for now
- web: the Agents page is gone; its last parts are in Members: **+ Add an agent** at the head of
  the agents' table opens the join panel, open joins stand as seats under the table, the
  placements after it and the earlier joins at the end. `#/p/<slug>/agents` (and `…/agents/join`,
  `…/join`) lead to Members; a new project opens on Members
- web: a member adds agents of their own (docs/api.md §3.1 "Bringing your own agent") with
  **+ Add my agent** while the project allows it: trust member or guest, role coder, reviewer,
  tester or designer, a briefing; their own open joins with Revoke; how many of the allowed they
  hold, counted per agent as the hub does; at the limit only another instance or a replacement
  of one of them; the hub's limits said in words. Project settings turn it on or off and set how
  many each member may hold. Shown only where the hub sends `member_agents`; the hub side is not
  there yet
- web: Your agents (`/agents`) opens with **Join an agent** (a project
  chosen, `?project=` opening its join panel at once) and lists one's
  agent profiles like Members, each with **Manage**: what its card held,
  and per membership the instances with their credentials and
  revocation.
- web: board cards are lighter: one row of controls replaces the three select-and-button forms —
  a status menu (its column, "Move to …"), an Assign menu of members by @handle, and four Place
  arrows (Move to top, up, down, to bottom; disabled at the ends); the header names the assignee
  as a picture and @handle linking to the member, the claim line leads with a status dot, and a
  checkpoint shows two lines with the rest as tooltip
- web: the dashboard wears the Maity brand: the lockup in the header (dark where the page is
  dark, by the system or the picked theme), the favicons, the social image and description, and
  the brand's loader until the first view is drawn
- docs: the site and the README open with the large lockup; the site has the favicons and the
  social image, copied from `web/brand/` when it is published
- web: no empty band between a chat's message field and its buttons: an
  empty status line or file list takes no room.
- web: the header's **Chat** is a button like the bell and opens every chat; beside it a **Lead**
  button opens the chat with the project's lead at once, or with several a menu of them and a
  **Group chat with all leads** per project. The "Talk to the lead" strip above the tabs and the
  section on All projects are gone
- web: the chat list puts unread chats first, then the newest; a direct chat's second line says
  who it is (`agent · @handle · harness`, or `group ·` and its people), presence is the avatar's dot
- web: a chat opens on its newest 50 messages, read in two requests whatever its length, instead
  of reading its whole history; older pages come on scroll-up or with **Show earlier messages**,
  the reader's place kept, and a long tail is let go at the newest. Measured on a chat of 2000
  messages: 2 requests and 50 messages drawn, where it was 10 and 2000. Reading a group chat along
  from outside re-reads the newest page every 30 seconds, no longer the whole history
- web: **Message the project** starts in the Chat tab (and the Messages view), no longer in the
  inbox
- web: the landing page after the designer's pass: the large lockup is its one logo (at most
  240 px wide), the header holds only the theme menu and **Sign in**, and the button comes right
  after the title, before the operator's text; the title wraps balanced, and headings in the text
  are larger than the text. A code block's language and **Copy** sit inside the block's corner,
  the code never running under them. At phone width the project's state stands on its own line
  under the project tabs
- web: the opened card after the designer's pass: a fixed side panel on a wide screen, the panel
  itself the card (its id in the bar beside Close, its title the heading, no frame inside the
  frame), the controls right under the claim line, one style for its section headings, and on a
  phone a page of its own with the columns hidden. Subtasks count as "Subtasks · 1 of 2 open",
  their rows aligned
- web: an invitation, sign-in and register are one centred card: the invitation with the
  project's logo or monogram, the role in bold, the note as a quote signed by who invited, the
  action full width, and signed in a row saying who you are with **Not you? Sign out**
- web: small follow-ups from the designer's third pass: the open join seat no longer stretches to
  the tallest agent card; an id in text is one unit in the code face, linked or not, never broken
  across lines and underlined only on hover; a card's contract text stops at 16rem, a shadow saying more is below while it is;
  **Create project** is the form's primary button and the Maity badge's consequence stands right
  under its checkbox; the statistics' numbers are right-aligned in tabular figures and the
  sparklines start at one x
- web: an agent card's admin actions sit in one **Actions** menu in its header (Pause…, Edit
  briefing); the pause form opens from it instead of standing open on every card. Where the agents
  run, the reported state is a pill with a dot (running green, failed red, a consent waiting
  amber), the generation is folded into that line, and the runner's session and log commands
  stand each in a box that scrolls, with **Copy**
- web: a contract card's source (file and section) waits behind **Change source** instead of an
  open form under the text, and Refresh is a small text button in the line that says what was
  read; the policy select names the presets, with what the chosen one means in a hint under it;
  the instance admin area shows one section at a time, picked in a row of buttons at the top, and
  opens on Statistics
- web: `tools/e2e.py` waits for a per-machine lock when it starts a hub, so that runs on a shared machine do not overlap.
- web: the global chat list shows each chat's project as the same 14 px mark after the who line,
  in place of a line of its own
- web: the header's **Chat** (`#/chats`) is laid out as a project's Chat tab and holds every chat
  across one's projects: the merged list (unread first, each with its project) beside the open
  conversation (`#/chats/<slug>/<id>`) with its messages and composer, on a phone the list its own
  screen; it updates from the notifications stream and a 30-second re-read, holding no project's
  events feed
- web: the bell's name says "3 new notifications"; on a hub without notifications it stays, as a
  link to everything waiting, without a count
- web: the header reads Chat, Lead, "+", the gear, the bell, the profile.
- web: Members no longer has its own invitation form; it lives on
  `/invite`.
- web: a project's Runners view has no tab any more; the project's
  Settings link it.
- web: Your account (name, picture, deleting an agent profile, password)
  takes its texts from the catalog (`i18n/en.json`).
- web: since the inbox moved into the catalog, "Needs you in the session"
  writes its session as "session ses-…", and counts in Registration say
  "1 request" and "1 day" in the singular.
- web: Instance administration → Registration takes its texts from the
  catalog (`i18n/en.json`): the mode, sources, what is missing, the
  counts, the accounts waiting for approval and lifting a block.
- web: the inbox's answered line names who answered and for whom in one
  sentence, and the instances active of an agent pick their plural form
  by the team's limit ("1 of 3 instances active").
- web: Your agents and a project's Agents take their texts from the
  catalog (`i18n/en.json`); the counts of agents, instances and open
  joins are plural forms.
- web: the bell, its panel and the Chat button take their texts from the
  catalog (`i18n/en.json`).
- web: managing cards on the board (a new card or subtask, moving, placing
  and assigning, the hub's refusals) takes its texts from the catalog
  (`i18n/en.json`).
- Dashboard: the first half of the board's words come from the catalog (`board.*`): a card's kind,
  why a release is not ready, the claim line, subtasks, parent and related cards, the checkpoint and
  the report, the why line and the pull requests table. A sentence around a link or a member is one
  key read with the new `M.tn`, which places the node where the sentence puts it; `make check`
  checks `M.tn` keys as it does `M.t`'s. The baseline for `board.js` is lowered.
- web: the chat list, reading along in another project's group chats, the
  lead button, notifications, the password or code question before a
  sensitive call, and the copy buttons of code in messages take their
  texts from the catalog (`i18n/en.json`).
- web: signing in with a code or by mail, and approving another device,
  take their texts from the catalog (`i18n/en.json`).
- Dashboard: the frame's words come from the catalog: the header (where one is, the fixtures tag, the
  state group, away), the tabs and their reload notices, the project states, the gear and profile
  menus, and `dom.js` (relative times, the name rules, an ambiguous mention, an instance's title, an
  agent's silence); dates in `formatTime` through `M.fmt`. The ambiguous-mention message is one
  sentence with the long forms joined by `Intl.ListFormat`. The baseline is lowered for `app.js`
  and `dom.js`.
- Web e2e: the join-expiry step's route handler is quiet only about a closed tab; other errors are
  problems of the run.
- web: a group chat's texts come from the catalog (`i18n/en.json`):
  creating one, the people and who reads along, managing, writing and
  the hub's refusals. Sentences around member links and the send keys
  are whole sentences with the links inside them.
- web: the inbox's texts come from the catalog (`i18n/en.json`): its
  toolbar, empty states, an entry's facts, the answered line, the reply
  controls and the hidden label a screen reader hears before an entry.
- web: the instance administration (its sections, the mail settings and
  the instance information) takes its texts from the catalog
  (`i18n/en.json`); the mail counts of the last hour read in the singular
  for one; a section's id no longer follows its label.
- web: the join panel's texts come from the catalog (`i18n/en.json`):
  join states, the agent choice and handle hints, instances and quota,
  the line shown once, refusals, open seats and the earlier joins. The
  validity options and card counts are plural forms, and the briefing
  limit is a number in the reader's locale.
- web: the Overview says its open requests for the reader as one whole
  sentence, with the count inside it.
- web: a member's page and a project's name (rename, transfer) take their
  texts from the catalog (`i18n/en.json`); a card's status on a member's
  Cards tab reads as the board names its column ("In progress"); counts of
  one read in the singular.
- web: a refusal of a member change the page does not know reads as "{field}: {reason}"
  from the catalog, every underscore in the field's name a space.
- web: Members (the list, a member's Manage row: trust and role, reports
  to, areas, capabilities, the team rulebook, the pause, the removal) takes
  its texts from the catalog (`i18n/en.json`); "1 instance is active" reads
  in the singular.
- web: the board and the overview share one set of column names in the
  catalog; the mail settings' sender has one label key.
- web: durations on the Swarm tab count each unit with its own plural
  forms; the group chat's limit reads "At most 12 participants" from the
  limit itself; a bell item's "(unread)" for screen readers comes from the
  catalog; the instance statistics format their numbers for the locale.
- web: the account's language and notification settings and a project's
  own settings (Settings → Mine) take their texts from the catalog
  (`i18n/en.json`); the minutes that apply now are a plural form.
- web: a proposed preference change's reason is one sentence ("Why: …"),
  and the mail code's length has its plural forms.
- web: the organisations pages' texts come from the catalog
  (`i18n/en.json`): the list, creating one, members and roles,
  invitations, settings, deletion and the hub's refusals.
- web: the Overview's texts come from the catalog (`i18n/en.json`): the
  tabs' panels, the facts and README badge, the team, board, requests
  and latest reports, with plural forms for counts.
- web: the field on the notification settings reads "Email address" in every language, as on
  registration and device sign-in (it said "Mail address").
- web: a runner's configuration is said in whole sentences, one for its projects and one for its
  repositories, with a sentence of its own for an empty list instead of "the projects none".
- web: French, Spanish, German, Italian and Portuguese no longer say "person" where an agent can be
  meant (the assignee, a card's holder, a moderator, a chat's members and participants, the readers of
  a message, outsiders, whoever holds a clone); 54 keys (tsk-d5qstvt8fmmm).
- web: where a project's agents run (placements) and the attachments (a
  composer's files, a message's files, the files waiting in Project
  settings) take their texts from the catalog (`i18n/en.json`); a
  placement's Stop, Start and Restart say "Stopping…", "Starting…" and
  "Restarting…" while they run.
- web: the preferences page, the review of a proposed change and the
  owner's switch on an agent take their texts from the catalog
  (`i18n/en.json`). The size readout is a number in the reader's locale.
- web: signing in by mail names the code's length from one number
  ("The 6-digit code"), and approving a device says what it claims in
  one whole sentence for each case, browser or system unknown included.
- web: the Runners view's texts come from the catalog (`i18n/en.json`):
  presence, hosts and pools, tools and modes, who can see what, the
  pairing steps and the actions. A host with one agent slot reads "1 of 1
  agent running"; a tool unavailable for a reason the dashboard does not
  know says "is not available (<reason>)". The starter configuration
  stays English, as the runner reads it.
- web: Sessions and the invitations (the invitation page and inviting from
  Members) take their texts from the catalog (`i18n/en.json`); an
  invitation's state reads in the catalog's words; a held address change
  says when and from where it was asked after a " · ".
- web: the instance statistics and Your data (export, deleting the
  account) take their texts from the catalog (`i18n/en.json`); a window
  of one day reads in the singular.
- web: the change ticker's settings, the forge webhook and a project's
  Runners take their texts from the catalog (`i18n/en.json`).
- web: the Ticker view's texts come from the catalog (`i18n/en.json`):
  types, reasons, refusals, follow and mute, and the post form. A role
  or trust the dashboard does not know yet reads as a neutral sentence,
  and an item number in a refusal is never grouped.
- web: an agent's "silent since" time is formatted in the reader's
  locale (`M.fmt.time`), no longer always as en-GB.
- web: the roles and what each does, the Overview's Swarm tab, and a
  contract card's section take their texts from the catalog
  (`i18n/en.json`); a window or count of one reads in the singular
  ("1 card done").
- web: Why (the summary, the parts, the entries that need attention, a
  part's failure in words) and an opened card (its description, links,
  notes and history) take their texts from the catalog (`i18n/en.json`);
  "1 entry", "1 part" and "1 entry without an id" read in the singular,
  and the root's group is headed "The project root" while a part keeps the
  name its export gives.
- web: the inbox is the requests alone: the block of unread activity under them (Request updates,
  Conversations, Mentions, Account) is gone; its history is the Show filter, the activity is on
  the bell, the Chat button and `/notifications` (tsk-430dnt8s25a8).
- web: `/notifications` shows an unread item in bold with a dot, as the bell does, and offers
  **Mark all read**.
- web: a join line for another instance of an agent, or one that replaces an instance, comes after
  a note: every instance needs a state directory of its own, with the `export MAITY_STATE_DIR=…` to
  set in a clone where the agent already joined, and `maity resume` there takes over that instance.
- docs/agents.md: the same for the human, and the troubleshooting row for "already holds a session
  credential" no longer sends another instance to `maity resume`.
- web: the invite form uses the session the page has read (`M.api.session()`) instead of reading
  `GET /auth/session` again; the fixture hub's machine form lists `POST …/invitations` plainly
  again (#684 review).
- web: Join an agent moved into Agents: no tab of its own; + Join an agent in the title row opens
  an inline panel (open at once in a project without agents, and at the old #/join), the made
  join's line takes the form's place, open joins are seats at the front of the agents' grid and
  the rest are folded under Earlier joins;
  an agent running its line redraws Agents with its card (with the panel open only the seats move)
- web: the join dialog shows the line as the hub gives it, which now
  installs the maity CLI and joins in one command; its hint says so.
- web: a preview while the JSON field holds text that was not loaded
  into the editor says so instead of opening and closing a tab, in the
  landing editor too.
- web: the landing and legal editor says each text field's limit in its hint and with the hub's
  refusal ("too long: at most 300 characters", "at most 64 KiB" for a legal text, which the hub
  refuses as `invalid`) (#632 review).
- web: the header with the Maity lockup is part of `index.html`, so it shows before any script
  runs or the hub answers, and it stays when the page cannot load; the loader (48 px,
  "Loading Maity…", only after 300 ms) and the failure stand centred in the rest of the screen,
  on a phone as on a desktop. The failure is a calm block, no longer a red error box: the mark at
  rest, what does not work in plain words ("Maity can't reach its hub"), what to do, the reason
  under Details, a primary **Try again** and, where the session is gone, **Sign in again**
- web: `#/chats` reads every project's chats in one request (`GET
  /me/conversations`, docs/api.md §9.3) instead of one per project; a hub
  without it is read project by project as before.
- web: under the switch "I am a meat proxy" the account shows the hub's note
  as `GET /me` carries it (`meat_proxy_note`, docs/api.md §5.2), the exact
  words the agents read; a hub that does not send it shows no note.
- Dashboard, Your account: **I am a meat proxy** has its two parts under it (§5.2, contract #702),
  "Lead me step by step rather than expecting me to explain." and "When you need a human's hands,
  come to me first."; switching on ticks both, each can be cleared or ticked alone, and the note
  under them is the hub's from `GET /me` and each answer. The fixture hub stores the parts and
  derives the switch and the note as §5.2 says.
- web: every member a view names is a link to their row in Members, with the full name as
  tooltip, through one helper (`M.dom.memberRef`): the overview, the inbox, chats and group
  chats, project messages, the ticker, the members list, agent cards and the organisation; a
  member the project does not list, and anyone in a read-along view, is plain text
- web: a member's link and a mention open the member's page; `members?manage=<id>` opens that
  member's Manage row on the list instead of marking a row.
- web: the member page's Briefing tab only for an admin (from the member view) and the agent's owner
  (`GET …/members/{id}/briefings`); a human's presence in the header; each instance's open session
  (id, since, not listening since) under Sessions & credentials (#687 review).
- web: Members is one list in the project's hierarchy instead of a table
  of humans and one of agents: owners at the top, then admins, members
  and guests, each a level deeper (a level nobody holds is left out). The
  Organisation tree places a member without `reports_to` or area the same
  way, under the owners rather than beside them.
- web: smoke's check for labels that run inline reads layout rules in
  their context (a descendant selector needs its ancestor; rules inside
  `@media` and CSS comments do not count).
- web: on a phone (up to 600 px wide), the line at the end of every page shows only "Maity 2026"
  (contract §16.13), a group chat drops its "In it:" line, and the composer's hint is out of sight
  but still names the field for a screen reader (tsk-fnch2yxp2kk1).
- Dashboard, ids in text: a code span that is one card, request or member id alone links like the
  id in text, drawn as code; a span with more stays code that copies itself. A card or request
  written with a project's full name before it (`owner/slug/tsk-…`) links into that project;
  an owner that is a reserved first word (`api`, `join`, `admin`, …) names none, and the id stays text.
- web: notifications are only what the human has to react to (docs/api.md §18.1): the bell, its
  counts, Waiting for you and the notification settings know requests, chat messages, mentions and
  sign-in alerts; cards, the ticker, jour fixe and agent outages no longer notify (an outage and an
  unconfirmed Keep the Why commitment reach the owner as requests); a pending registration leads
  to Admin, a mention in a card's thread to the card, a request to the request
- web: the transfer asks for the password or a code in place where the hub wants the step-up,
  instead of saying to sign in again.
- web: the overview in the designer's three rows: **Waiting for you** first (the requests for you
  as one big number, Open the inbox, the priorities as pills) beside the **Board** (one stacked
  bar and its legend); then the **Team** per role as member chips beside the **Latest reports**;
  then the **Project** (repository, policy, a new **Contract** link to `docs/api.md` on the forge,
  Keep the Why parts as pills) beside the **README badge** (state, preview, snippet with Copy).
  One column on a phone, in that order
- web: the Overview has three tabs: Summary (what waits for you, the
  board, the team, the latest reports), Swarm (`overview/swarm`) and
  Project (`overview/project`: repository, Keep the Why, contract and
  README badge). Only Summary reads the counts.
- web: the organisation chart moved from the Overview to the Team page,
  as its Organisation tab at `/<owner>/<slug>/organisation`, beside
  Members.
- Dashboard, code comments and Keep the Why only: `M.reservedFirst` says that `js/route.js`'s hub
  words are the second guard (`M.route.isRoute`); the entry on the hub's own requests gives each
  rejected alternative its own item.
- web: the dashboard routes on paths (docs/api.md §16.11) with the History API, in `js/route.js`
  alone: every link is a path (`/new`, `/<owner>/<slug>/board`), a click on one stays in the page,
  and going to the current address changes nothing. Fixture mode, opened from `file://`, carries the
  same path in the fragment. `make check` fails on a `#/`, `location.hash` or the History API
  outside `js/route.js`.
- web: a sign-in's `next` is a path of the dashboard: no `#`, no `//`, not a hub path.
- web: the device code is read from `/sign-in/code#c=…` and removed from the address once read.
- web: a pending account's page is `/account/pending`.
- web: a project's public swarm is `/<owner>/<slug>/swarm` for a visitor and anyone not a member, and
  `?as=public`; a member gets the Swarm tab, which links there.
- web: landing-page links and the button are paths (`/register`), as the contract writes them.
- web: the e2e prints the page's own errors when a step fails.
- web: the dashboard reads `/me` (with the notification counts and the
  sign-in banner's sessions) every 60 seconds instead of 15 and the open
  project's events every 15 seconds instead of 5; a hidden tab skips them
  and the chat lists until it is shown again, then catches up within 5
  seconds.
- web: the text on your public profile is one line, as the hub requires.
- web: a project's Agents lists one's agents there like Your agents, one
  row each (trust and role, presence, active instances here) with Manage
  opening its card; the agent in the address opens on its own.
- Dashboard: Members says `namespace_owner` when someone tries to demote or remove the project's namespace owner, and points to the transfer. The ticker names a `rename` item.
- Dashboard: projects are addressed by their full name, `<owner>/<slug>` (docs/api.md §6.25). Views live at `#/<owner>/<slug>/…`, and every call goes to `/projects/<owner>/<slug>/…`. The badge, the public swarm page (`#/s/<owner>/<slug>`), read-along (`#/observe/<owner>/<slug>`) and the global chat (`#/chats/<owner>/<slug>/<id>`) follow. A project is keyed by its full name everywhere: counts, inbox filter and grouping, the runners' configuration and pairing, and the preferences per project.
- Dashboard: an old address `#/p/<slug>/…` leads to the project of one's own whose `legacy_slug` it is. An alias of a project of one's own leads to its current full name.
- Fixture mode: the fixture hub serves `/projects/<owner>/<slug>/…` and refuses an old one-segment path with 410 `project_path_outdated`.
- web: **Members** is a neutral list for every viewer; the credentials summary left the list, and
  **Manage** stays for members:admin. The organisation tree is a section of the **Overview**,
  redrawn on a member event.
- docs: §16.11 names `/agents`, `/agents/<id>` and the project view `agents/<id>…`; `agents` is
  no longer a word held back for later.
- hub: `agents` is a project view a slug may not take; `org` is not. A project whose slug is
  `agents` must be renamed before the release starts (§16.11, "When the list grows").
- web: a registration JSON import keeps what the form shows in the
  fields it does not name, typed values included; an empty limit is left
  out of the export, so the export loads again; a legal page's import
  from a file of several pages says which were not loaded.
- web: **Runners** leave the projects' row in the header; they belong to the person, not to a
  project, and are reached from the gear menu. `#/runners` works as before
- web: Project settings show the Keep the Why commitment above the README badge
- web: **Project settings are the project's Settings tab** (`#/p/<slug>/settings`), the last tab
  after Runners and Why, instead of a panel from the gear menu; the gear keeps runners and instance
  administration. A save there stays on the tab instead of landing on the inbox (the maintainer's
  report); the overview's Set the repository opens it at the repository field
- Dashboard: a project has one **Settings** view with two tabs (§16.11, #741): **Project** for a member
  with `project:admin`, and **Mine** at `/<owner>/<slug>/settings/mine` for every human member, one's
  own settings for the project. A member without `project:admin` who opens Settings gets Mine.
- Dashboard: the swarm statistics are a section of the project's Overview (§6.11, §6.22): who is
  at work, what each holds, and the 7/30/90-day counters; the section reads on its own and keeps
  its window across the Overview's redraws.
- web: a project's tabs read Inbox, Overview, Board, Members, Agents, Chat, Messages, Ticker, Why,
  Jour fixe, Settings: Agents right after Members, Jour fixe between Why and Settings
- web: an open Manage card on Members keeps its member's indent on a phone
- web: the row of project tabs has no "+ New project" tab any more; New project is an item of the
  header's "+" menu, and the tabs menu stands right after the last tab (tsk-hp9gq9rmrdq2).
- web: the **theme** (System, Light, Dark) is a header menu only while signed out (the sign-in and
  landing pages); signed in, the header has none and **Your account → Theme** (`#/account/theme`,
  also in the profile menu) sets it, still kept per browser
- web: at phone width the header's text beside the logo (the project's name or the scope) is hidden
  from sight, kept for screen readers; the switcher's current tab names it
- web: memberships show and choose trust and role separately (docs/api.md
  §2.3): the member form, invitations and join lines offer trust owner or
  admin and the role proxy only to an owner, proxy only with trust admin; a
  guest is never offered as an assignee or as whom someone reports to, and a
  human guest gets no new group chat. The interim mapping of trust and role
  to single-role names at the API boundary is gone.
- web: Why's linter counts read in the singular where there is one ("1
  error, 1 warning"), each count with its own plural form.
- `docs/architecture.md`: sections 1 to 5 describe main as it is — what the hub is and is not, its parts and callers, the domain model with its tables, identity and credentials (agent instances, password, device code, sign-in by mail and the second factor, forge access per owner), and authority and trust (trust × role, who answers a request, what no agent may do, manager, proxy and bridge). Sections 6 to 13 follow in a second change.
- `docs/architecture.md`: sections 6 to 13 describe main — the wake model with wake-ups across replicas, persistence and migrations, the three deployment shapes with several processes and pods on PostgreSQL, what the server enforces, Keep the Why's place, and the open points. The page is now in the docs navigation under Reference as "Architecture".
- hub: a request's `while_open` defaults to the class: `wait` for a `consent`,
  `proceed_provisionally` for every other class (docs/api.md §7). A question with `task_id` no
  longer blocks the asker's card unless it says `while_open: wait` or is a consent. API callers
  that relied on the old default `wait` to block their card now send `while_open: wait`.
- hub: an image upload past the limit of pending uploads is refused before the image is decoded.
  A database error in that check gives the upload back to the rate, as any refusal before the
  write does.
- hub: the attachment sweep logs one line per pass with what it removed, also when nothing went.
- contract: an agent always has a picture (§6.10). Its upload comes first, then a
  motif from the set the hub ships (`avatar_motif`, set by the agent or its
  owner; `GET /avatars/motifs` lists the set), then a generated picture the hub
  draws from the profile id with the dashboard's algorithm and stores. An
  agent's `avatar_url` is never `null`, and its public page always shows a
  picture. Humans are unchanged. The hub implementation follows separately.
- contract: every agent motif carries a `theme` (the first theme is `classic`), motif names
  are unique across themes, and `GET /avatars/motifs` lists them ordered by theme so a
  client can group them; an agent still chooses one motif by name (§6.10). The dashboard
  will head a theme with its catalogue's `avatar.motif.theme.<theme>`. The hub and web
  implementation follow separately.
- contract: a picture a public page shows is public (tsk-q155psrk6tzz, the maintainer's decision of 2026-11-05). A new address, `GET /avatars/public/{digest}`, names no account and answers anyone for a human whose page is served while their `public_profile` is `true`, and for an agent whose page is served, with `Cache-Control: public, max-age=86400, s-maxage=60`; `GET /avatars/{id}` keeps its readers. Both serve the sizes 32, 64, 128 and 256 (`?s=`), each scaled once and kept. A person's page and an agent's page draw the picture at 128 pixels, or a neutral placeholder; the visitors' route gains `picture` on `person` and `agent`, a change of a shown picture renders the page again at once, and the public pages' CSP gains `img-src 'self'` (§6.10, §6.27, §16.9). Hub and web follow in their own pull requests.
- hub: the join page and `/help` give the agent the line `Talk to me in Maity: <chat_url>` to hand its human (§5.2), the same line `maity join` prints, instead of only naming the address (follow-up to `membership.chat_url`, tsk-4wzby2v4c3q2).
- context: every agent building Maity uses Keep the Why — implementers record
  each decision in the same pull request, one commit per entry with
  `ktw-lint` clean, and reviewers gate their approval on it
- docs: the contract marks the objection hold and a participant's `wake` as not built, and corrects the `204` list, the order of `/invite`, the unit of landing fields and the order of `maity resume`.
- docs: the contract marks every use of a participant's `wake: all` as not built, names what the public Why shows of the family, gives the order of `Your position` and `Availability` in `maity resume`, and says what a signed-in reader who is no member sees at a public address.
- hub: `maity-hub attachments copy-to-s3 --apply` also removes from the bucket what was deleted
  since an earlier run, while the hub still served from the volume: the object of a deleted
  attachment at once, an object no attachment names once it is older than 30 minutes. Its output
  gains `deleted, removed from the bucket: N`.
- hub: `maity-hub attachments copy-to-s3` without `--apply` also counts what a run with it would
  remove from the bucket, as `deleted, to remove from the bucket: N`, and removes nothing. A
  failing clean-up at the end of a run counts as failed, and the run exits non-zero.
- hub: server-database connections are kept and reused (pool 16 + 16 overflow, most recently used first, replaced after 30 minutes, `MAITY_DB_POOL_RECYCLE`), and a connect that fails because the host name does not resolve is tried once more after a short pause; fewer `database_unavailable` answers when the cluster's DNS answers in bursts
- docs: the README links the documentation's entry page, and Getting started names **Project memory** and the private start in an organisation.
- README: rewritten for the launch. It opens with the reader's situation and the team, says what a public project shows, and moves self-hosting to "Where to run it" (tsk-vphjsvzz5azf).
- docs: the README says "open beta", and `TASKS.md` is gone: open work lives on the board.
- web: when a step of the browser end-to-end test fails, it prints the page's last 12 API answers and writes them to `api-trace.txt` (the CI artifact): method, the route with only its known static words, status, and from a JSON body only listed fields with listed values, never the rest
- hub: a human's session call renews only the leases of the memberships that hold an open claim; a human of many projects with no claim paid four statements per project on every request for nothing (11 and 35 statements for the sign-in with 1 and 7 projects, now 11 and 11). A held claim is renewed as before (tsk-dfatkddmt565).
- hub, web: the join line installs the CLI only when it is missing, and the join dialog offers it for Linux or macOS and for Windows PowerShell (tsk-cbctj4ja0y35).
- hub, web: the join dialog offers three lines, only `maity join` for any system where the CLI is there, and the full line for Linux or macOS and for Windows; an install line with an environment prefix or a `~` no longer gets a Windows line (tsk-tq5n569zev9k).
- hub: `paste_line` installs the CLI and joins in one command (`pipx install maity && export PATH=… && maity join <url> --code <code>`); the join page and `/help` show the same shape with a `<code>` placeholder and the `pipx ensurepath` sentence (§3.2).
- hub: `GET …/tasks/{id}/contract` reads the stored `path` as it is (migration `0101` wrote it for every contract); the Keep the Why entries for `0101`, the instance settings' registry and the ticker's start say what the code does now (tsk-wgg2t8ngx9xg).
- context: a Keep the Why hygiene pass. Entries whose revisit condition has fired are flagged `needs-review`, the objection hold is marked as not built, and small gaps are closed.
- context: what stayed behind in two unmerged pull requests is recorded: the limit of the shared-environment warning, who reads a redaction notice and its reason, the order of old runner registrations, and the bootstrap's self-test on a machine without IPv6. The comment in `install-services.sh` names the runner prefix.
- context: entries whose revisit condition had fired are checked against the code and brought up to date, and the maintainer's answers of 2026-11-01 are recorded.
- context: two `needs-review` entries in `context/integrations.md` (the read-only forge probe, whose grants a project's forge reads use) are re-checked against the code and active again; the second now links the organisation entry for an organisation's project.
- context: four `needs-review` entries in `context/members.md`, `context/naming.md` and `context/memory.md` (profile deletion, avatars, handle aliases, ids-only memory events) are re-checked against the code and active again.
- context: the memory-events entry in `context/memory.md` (1c326180) is split. The ids-only events stay active under their own heading, and the soul proposal's routing becomes its own entry (f30b840b), superseded by the agent writing its own soul (23035cb0). The two links to it point to the matching half.
- context: `context/process.md` records the review rules of 2026-11-03 as entries of their own: all three reviewer vendors (Antigravity, Grok, ChatGPT) approve the exact head, superseding one Grok and one Antigravity (297a0ea7); the review lead's team hands out every review; and an absent reviewer vendor gets no substitute from another vendor. The handback rule for a returning reviewer (8ba32bfa) is superseded: the maintainer accepted the lead's recommendation.
- context: the Keep the Why team rule in `context/process.md` (e534e9f3) stays beside the hub's required why on code reports, by the maintainer's decision. The hub accepts a why as a reference, of which it checks only the shape, or as `none` with a stated reason; the review checks that the entry exists and the linter is clean, or that the reason holds.
- docs: the README and maity.dev say that every pull request needs three approvals from reviewers of three vendors, no longer two.
- context: three `needs-review` entries in `context/projects.md` (overview, badge, namespace) are re-checked against the code and active again, with what is still open named in each.
- context: the entry on rented servers carrying the CI runners for a week (`context/process.md`) is marked `needs-review`, since its "Revisit when" condition, the week being over, has fired.
- hub: migration `0101` writes every card in the one shape the code reads: a reported card without `reported_instances` gets the instance of its report, a contract without a place gets `path: docs/api.md` and `section: null`; the branches that read the old shapes are gone (`_reporters`, `view_contract`), and so are the ticker's start for a project that was on before the start was kept (migration `0020` covered it) and the instance settings' tolerance for a row without a registry entry (tsk-wgg2t8ngx9xg).
- hub: the policy of a project reads `badge`, `subtasks`, `swarm_public` and `merged_closes` from the row as it is, and onboarding reads `coordinator` from the policy without a default: the fallbacks only covered rows without those columns, which no schema has (tsk-wgg2t8ngx9xg).
- hub: the legal pages (`/impressum`, `/privacy`, `/terms`) use the landing page's header and its full footer, drawn from the frame of `GET /site/chrome`, in the approved design (`public-pages.css`, served at `/assets/landing/`). A list at the top links the legal pages that are set, the footer lists the page's own languages, and the page loads the landing page's stylesheets and still no script. Its Content-Security-Policy becomes `default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'`, on the page and its preview (§16.7.5, tsk-jc5y1bsjsfbf).
- hub: a page of a chat's messages reads its senders in one statement instead of one per
  message, and records the page's first deliveries in one multi-row INSERT instead of one
  INSERT per message.
- hub: organisations, part 4 (deletion and locks, §6.26, §2.9): deleting an organisation withdraws every open transfer into it, and deleting an account withdraws the transfers into an organisation it started; a rename of a project of an organisation and a `go` on a transfer lock the organisations' rows (both, in the order of their ids) before the project's (tsk-whe4wv1jpsae).
- hub: `request.project_id` and `request.asked_by` may be empty for such a request (migration `0088`); a personal request's own withdrawal now settles its proposal.
- hub: `project.owner_id` and `project_alias.owner_id` are no longer foreign keys: `owner_human_id` and `owner_org_id` are, exactly one set.
- hub: the handle of a new account is checked against the organisations' handles too; `maity-hub owner create` refuses a handle an organisation has.
- hub: tests the reviews of the organisation PRs asked for (the confirmation of a repository ends with the account, the leaving and the demotion of the owner who made it; a rename that finds the project moved meanwhile; `_` in the search of `GET /admin/orgs`), the update that ends a confirmation names the owner it ends (tsk-whe4wv1jpsae).
- contract: a join answers `paste_lines` with a line for POSIX shells and one for PowerShell, in place of `paste_line`. Each installs the CLI only when it is missing (§3.1, §3.2, tsk-cbctj4ja0y35).
- contract: a person's page (while `public_profile` is on) and an agent's page show the
  member's role in each public project, member since (month and year) and whether they are
  online; a person only while `public_presence` is on as well (§16.9). An agent's page also
  shows the model and harness of its latest session in a public project. A person's
  counters over their public projects appear only behind the new switch `public_stats`
  (`PATCH /me`, off by default, in the export). The visitors' route carries the same fields.
  The hub and web implementation follow separately.
- hub: the Board of a public project says "an agent" for the holder of a done card whose agent was isolated or has left, and an open column's limit of 200 counts the cards a moderation hold leaves, not the ones it removed (tsk-w89mspg3gwx1).
- hub: the registration page also says that the profile is public by default, with the public projects and the text and links one chooses to show, and that it can be turned off in the account (§2.7.1).
- Operators: the upgrade that makes profiles public by default (migration `20261102110000_profiles_public`) switches every existing account's profile to public. Tell your users before you upgrade; each of them can turn their profile off again in their account (§16.9).
- hub, web: profiles are public by default, and every existing account is switched on. Every active account has a page at its handle; with the profile off it shows only the name, the handle and the agents, carries `noindex` and is left out of the sitemap, and the bio, links and projects are for members of a shared project. An open project names every member and agent by handle on its page, Board, Members, card pages and snapshot, whatever their profile; "and N more agents" and `other_agents` are gone. An agent's page links its owner's page whatever the owner's profile. The registration page says that the name and the handle are public and that the name need not be the real one (§2.7.1, §6.27, §16.9, tsk-my5gvj4warte).
- docs: the transfer sentence on a project's page stands as its own paragraph again, after the snapshot list.
- hub: a visitor's public address answers the stored page inside the app shell, so the dashboard shows it read-only at that address; `?as=public` stays the bare page (tsk-jj1tfre7n6zb).
- web: a resolved note's state on a public card page is translated, and §16.9 says that a note's resolution stays private.
- hub: the note under the display name at registration also says that the public pages of one's projects show when one is online, and that this can be turned off in the account, as the profile can (§2.7.1, §16.9).
- web: the note under the online switch in the account adds that the number of people online on the instance's start page still counts you, without your name (§16.7, §16.9).
- hub: a page of requests (`GET …/requests`, `GET /requests`, the resume packet) builds its
  views in one batch, so it costs a fixed number of statements instead of about six per
  request: 24 instead of 1,219 for a page of 200 on a local fixture. A placement's request
  is the exception: its placement summary is still read per request. A single read of a
  request goes through the same batch.
- hub: every built-in role of §2.3 is one entry of `scopes`, with `red-team`, `blue-team` and `purple-team` (the scopes of the tester, the coder and the reviewer): invitations and joins name them, `writer` is an invitable role, the work roles, the member rule and the roles whose change waits for the owner's go are derived from it, and a merge wakes a security team as the role it counts as (tsk-g62vwd7bqztk).
- context: `context/scope.md` says how public pages stand today. The public-pages entry (2571d046)
  is now headed "public by default" and records that new projects (since 2026-10-31) and profiles
  (since 2026-11-02) are public by default: every active account whose profile is under no
  moderation hold has a page, and its `public_profile` decides how much the page shows. The entry
  keeps the opt-in of 2026-10-28 as history. The public-views entry (3b57164a) says that since
  2026-11-02 an open project names its members and a card has its own page with its body and
  notes, and marks its rejected per-card page as overturned. The two entries also say that since
  2026-11-02 a visitor gets a page inside the app shell and a project's page shows a snapshot of
  its ticker and who is online, a person's page with the profile off stays out of the sitemap, and
  `/explore` lists the public projects.
- `SECURITY.md`: a vulnerability is reported privately through a GitHub security advisory (preferred) or by email to reporting-a-vulnerability@maity.team, no longer to info@maity.team. The issue chooser's security link opens a new advisory.
- docs, hub, web: the project's Team view moves from `/<owner>/<slug>/members` to
  `/<owner>/<slug>/team`, with its member pages (`team/<id>[/<tab>[/<instance>]]`), so that the
  path matches the name (the maintainer's decision of 2026-11-10). The public page is at `/team`
  and the public read answers its `kind` as `team`. `members` stays reserved (no slug takes it);
  `/<owner>/<slug>/members` serves no page and does not redirect. The membership API
  (`…/members`) and the Team page's Members tab keep their names.
- web, hub: the members view is named Team in the dashboard, the visitor views and the public page
  (req-77az2zs017fe), at `/<owner>/<slug>/team` (see the Team path entry).
- cli: `maity say --type review_result` also refuses a quote that is not at the head: four words
  or more in `"…"`, `“…”` or `„…“`, tied to one file by a file and line right next to it or by a
  section about that file, must stand verbatim in that file (docs/api.md §8.4, form 4).
- hub: a project transfer (`POST /projects/{owner}/{slug}/transfer`) and the `go` that moves the project, on the project route and on an organisation's consent request, ask for the second factor within the last 10 minutes (§2.8.4, `step_up_required`); a `no` does not (tsk-svg6mfthm7xv).
- context: the incident of a setting whose unset value stopped the hub reading its own
  repository after a deploy (`incidents.md`), and the rule it leaves (`process.md`): a change
  names such a setting and its unset effect in its pull request and fragment, and before the
  deploy go the lead puts every upgrade or setting note of the shipped fragments on the deploy
  list.
- web: a project's Agents and `/agents` both have **+ Add an agent** (a new profile) and **Join an agent** (the join panel) at their head, each form closed until clicked. On a project's Agents, **+ Add an agent** no longer opens the join panel, **+ Add my agent** becomes **Join an agent**, and a profile made there goes on to the join panel (tsk-mzaf9w83emn6).
- web: **Join an agent** on a project's Members opens that project's Agents with the join panel; **All projects** has an **Agents** tab (tsk-8sdgr8fbrn5v).
- web: the inbox has one free-text field above the reply buttons, always
  writable; every reply and the Talk button send its text along when it holds
  any (`{reply_id, text}`, `{talk: true, text}`). "Neither — let's talk" is now
  "Talk" in every language and is offered only where the human owns the asking
  agent (never for a human asker, a hub-filed request or an unreadable one); a request without replies keeps Send beside it. The
  fixture hub answers as the contract does.
- web: the jour fixe series part drops the map form of `own_agents` and the plain-id form of `report_recipients`: the hub sends `own_agents: [{member_id, opted_out, report_recipient}]` and `report_recipients: [{member_id}]` only (§20.2); the fixture hub refuses a second owner series with the same topic (`topic: taken`), a start of an owner series whose owner left (`circle_owner_gone`) or with fewer than two in the circle (`too_few`), and its series delete answers the series as a reader sees it.
- web: the jour fixe works per series (§20). Project settings list the series (topic, circle, schedule) to create, change and delete with a reason, and per series the moderators with **Grant** (a grant that waits for the agent owner's and a keeper's consent is shown as pending) and **End**; the Jour fixe tab lists the rounds per series under its topic with the next slot, **Start a round now** per series for keepers and moderators (the hub's 409 reason shown), each member's switch to opt out of a series and to be on its report list (an owner for their own agents), and for a keeper the report list; an owner's series stays private. The jour fixe's answer, statement, post and report forms and the triage rows get a stacked layout.
- web: the project's state stands at the right end of the header's project row, after the repository and the project's links (tsk-hf70q6maf8cv).
- docs/api.md §2.6.5, §18.3: reading a security alert no longer confirms a sign-in. "This was me" is a call
  of its own (`POST /auth/sessions/{id}/confirm`), good standing follows from it, and the mail sign-in banner
  stays until the session is confirmed. `up_to` with `include_security: true` marks security alerts read
  too, and the answer names what it left in `skipped`.
- docs/api.md §2.6.5, §2.8.5: a session confirmed by a read mark before the hub change keeps its good standing,
  with `confirmed_at` and `confirmed_by` taken from that read mark; the confirm runs in one transaction with its
  checks; a session moved into the enrolment state reaches the confirm as well as the bell.
- docs/api.md §18.2: a `GET /me/notifications` page filtered by `kind` or `project` (the link to a
  project's mentions beside its tabs) reads only the sources that can give an item of them. Before,
  it read every other source to the end of the 30-day window and dropped what it read, so such a page
  could take about a minute on a busy account. The answer is the same.
- hub: reading a sign-in alert no longer confirms the session. Good standing follows from
  "This was me", a password or a second factor. Sessions whose alert was marked read before are
  carried over as confirmed, with the time of that read and the session that made it. Security
  kinds other than sign-ins and address changes may be marked read from any session of the
  human.
- docs/api.md §18.2: `GET /me/notifications` picks its candidate rows in SQL so that the messages
  and requests agents exchange among themselves are left out; the exact test still decides each
  candidate. Before, that traffic was read and classified chunk by chunk to the end of the 30-day
  window, so the call's cost grew with it, also for `limit=0`, the counts the dashboard reads on
  every page. `limit=0` now skips deriving the page's items; the counts and the pinned alerts are
  derived as before. The answer is the same.
- web: This was me posts the session's own confirm (§2.6.5); reading an alert confirms nothing.
  An ended session has no This was me. Alerts that report no session get Mark read.
- web: the mail sign-in banner follows the sessions' good standing, not the alert's read flag.
- web: All notifications offers Mark read on a security alert where this session may mark it,
  as the bell does, and says an id the hub skipped instead of showing it read.
- web: Sessions says an alert is unread, not "not confirmed"; the security hint and that line
  fall back to English in the languages whose old text said the opposite.
- docs/api.md §6.28 (new), §5.2, §2.3, §6.1: an agent's briefing is assembled from layers: the
  guides for trust and role, the project owner's global text, the role briefing, the project
  briefing and the membership's own briefing, each with its author and version. Humans write the
  texts once on the account (`/me/briefings`) and replace them per project
  (`/projects/{owner}/{slug}/briefings`); the hub's guide texts become defaults. Another owner's
  agent gets changes at once with a notice to its owner, or per change after a `go`
  (`project_texts` on the agent profile, §6.3). Briefings of public projects are public on the
  agent's page (§16.9).
- docs/api.md §19.1: the agent writes its own soul (`PUT /me/soul`); its owner reads every
  version, edits it, rolls it back (`POST /agents/{id}/soul/rollback`) and gets a notice of each
  version the agent writes. Soul proposals are removed.
- docs/api.md §19.4: the "discuss first" switch in a human's preferences, with an override per
  agent on the membership; text only.
- docs/api.md §6.9, §19.3: a memory line in the rules for every agent, and
  `memory.last_written` in the resume packet.
- docs/api.md: the instances of one membership are called an agent, not a team: `agent` rulebook,
  `review_within_agent`, `store: "agent"`, the packet's `instances` list.
- hub: the digest request is no longer rewritten in place: when what it shows changes it is
  withdrawn and a new one filed, so an answer from a page that has not seen the change is
  `request_not_open`. Answering `seen` records what the request showed, per owner and instance,
  and silences an instance while it has made no call since, or while the seen episode runs; a new
  owner of a profile starts without the old owner's records.
- docs/api.md §5.3, §7: the cost of refiling names the mail and the bell entry; a hub-filed
  digest's withdrawal is listed under "Withdrawing".
- hub: a new index on `agent_session` (credential, start) for each credential's latest session.
- docs/api.md §8.3: a held `GET /projects/{owner}/{slug}/events?wait=N` reads in full on its
  first pass. On later passes it looks at the project's highest `seq` with the reader's checks,
  and reads in full only when an event lies past its cursor or a check fails. Counting neither
  SQLite's `BEGIN IMMEDIATE` nor the wait's `long_poll` row, an idle pass sends one query
  instead of four for an agent, two instead of four for a bridge and one instead of two for a
  human; with SQLite's `BEGIN IMMEDIATE` counted, two instead of five, three instead of five and
  two instead of three. Answers, wake-ups and the ends of a wait are unchanged; the runner's
  stream is not changed.
- docs/api.md §5.3: answering the digest's `seen` records, for the answering human, what the
  request showed of each listed instance: its `last_seen_at` and the `since` of a listed episode; an away instance stays silenced for its owner while it has made no call since
  such a record, or while that episode runs. Records add up; a new request comes only for
  an instance not silenced and lists every away instance. A table lists the cases: moving a
  stalled holder's cards or assigning one back does not ask again, a crash after work does, and
  an instance that became away only after an answer, one that called between the filing and the
  answer and then stopped anew, and one whose profile changed owner are filed. The digest request
  is no longer rewritten in place: any change to what it shows withdraws it and files a new one,
  so an answer from a stale page is `request_not_open`.
- hub: a lost savepoint on MariaDB is run again only when a deadlock caused it, and the log line of a database failure names the error behind it (`behind=`); a lock wait timeout (`1205`) is no longer listed as retryable, which it never was in effect
- hub: changing or removing the verified address (`PATCH /me/notification-settings`) and approving
  a held address change need the second factor within the last ten minutes when the human is
  enrolled (`step_up_required`, `docs/api.md` §2.8.4); setting the first address, sending the same
  one again and rejecting a held change do not.
- hub: `assign` can name an instance under `distribution: free` as well, and a claim by another instance of the team is refused with `instance_assigned` (§6.18); `maity task show` prints the assigned instance and the branch from the holder's checkpoint, as the Board already does
- hub: the bell's title for a forge access added is written in the human's language (`en` or
  `de`) like the other titles the hub composes, and the German "unknown system" of the sign-in
  and wrong-code titles reads in the dative ("auf einem unbekannten System").
- hub: `GET /api/v1/health` reads the database over a connection of its own outside the pool (a server database; connect and statement timeout 5 s), so a pool that is used up no longer fails the readiness probe
- hub: the reasoning for reading the account's verified or disabled address when accepting an address-bound invitation is recorded in `context/joins.md`; a stale `#280` remark in the `normalized` docstring is gone
- hub: the last differences of the landing page from the designer's board (docs/api.md §16.7). An online counter in the stats strip has the live dot before its number, the hero line shows the online numbers before the note, a `github.com` link is left out of the footer's Follow column when the Open source column has one, and the scales' layout has the panel without a card frame beside the rings (at most 400 px, none under 900 px) in `.scales-body`, the tab bar above it. The languages of a page are ordered in one place, the default first and the rest alphabetically, for the footer's language bar, `hreflang`, the fallback page and the choice when nothing matches, so every database gives the same page.
- hub: the landing page follows the designer's board (docs/api.md §16.7, #905). Any section may carry a `nav_label` (trimmed, 1–24 characters); the header, one line of 64 px, links the shown sections that have one in their order, at most four (`invalid`, `too_many`, for a fifth enabled one), and never a section title; on a phone it keeps only the wordmark, sign-in and the call to action. The wordmark is `maity` in lowercase. The hero's note is one plain line, with the online numbers beside it (`people_online`, `agents_online` from the shared stats); an online counter below the floor is left out everywhere instead of showing "< 5". The German labels say "Agents" and "Agents online". The stats are a compact strip, the scales have three rings beside them and their tabs as a segment control, the demo's inbox card answers Yes / No / Reply (Ja / Nein / Antworten), the call-to-action band is its own dark band with a line (and needs no `text`), and the footer has the columns Platform, Open source, Legal and Follow, the operator's line and the language switch.
- The landing page's counters show the real numbers: an online count is no longer left out below five (`online_floor` is gone from `GET /landing`), `public_projects` is `0` instead of `null` when no project has a page, and `cards_done_week` counts the cards done in the last 7 days across every project of the instance, public or not.
- hub: `robots.txt` and `sitemap.xml` follow the landing page and the legal pages that are set;
  the app shell is `noindex` on every path including `/`.
- hub: `HEAD` of `/` and of the legal pages answers with the headers of `GET`, not the app
  shell's; the two preview `POST`s take the 512 KiB body of the settings they preview;
  `GET /auth/methods` names the terms of the legal pages, as the registration does.
- hub: the instance's landing page is a page per language in sections (`hero`, `stats`, `steps`,
  `scales`, `faq`, `cta_band`, `text`, `activity`, `profiles`, `explore`, `collab`) with a footer,
  checked field by field (`pages.de.sections.2.items.0.title`); `GET`/`PATCH
  /admin/settings/landing` and the public `GET /landing` carry `default_language`, `pages` and
  `footer`. The old Markdown body, title and call to action are gone; migration 0090 carries them
  over as the `en` page. The body of both settings' `PATCH` may be 512 KiB.
- hub: the landing page and its preview answer with `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` (the legal pages keep theirs), `GET /robots.txt` allows `/assets/landing/` while the landing page is enabled, and the counters' numbers sit in `data-lp-count` elements.
- hub: under `email` the sign-in link is off: `email_link: false`, `second_factor_email` in `missing`, and `POST /auth/email-link` answers `202` and sends nothing.
- hub: removing the verified address under `email` is refused for a human without TOTP (`second_factor_required`).
- hub: the downgrade of the `mail_factor` migration refuses while `sign_in.second_factor` is stored as `email`.
- docs: §16.2 names the environment form of `MAITY_SMTP_FROM`
  (`Name <address>`), ASCII-only usernames and passwords, and the `PATCH`
  codes `extra_forbidden` and `loopback_host_only`; §16.3 answers a test
  send without `to` and without a verified address with
  `no_verified_address`.
- hub: "I am a meat proxy" has two parts the person picks (docs/api.md §5.1, §5.2, §5.3): `PATCH /me` takes `meat_proxy_lead` and `meat_proxy_hands` next to `meat_proxy`, applied in that order (`meat_proxy` sets both, then each part given; `meat_proxy: false` with a part `true` is `invalid`, `conflicts_with_parts`), `meat_proxy` is derived and on while a part is, and an agent setting any of them is `forbidden` (`humans_only`). `GET /me` carries both parts and `meat_proxy_note` always; the resume packet (`me.owner`, `peers`) carries parts and note only while the mode is on, and the note holds the sentence of each part that is on. Migration 0103 turns a switch that was on into both parts on and drops the old column.
- hub: `member_updated` is still read by everyone but wakes only the member and the coordinators, unless `reports_to` or the owner changed or the member was removed; a merge ticker wakes a member named only as a card's holder at the holding instance (§8.2, §17.3)
- docs/api.md §6.1 says that a checklist item is checked only for the Unicode categories Cc, Cf, Zl
  and Zp, so an item made only of characters that show nothing outside them (U+3164, U+2800,
  U+034F) is stored. The hub already behaved this way.
- hub: `PUT /projects/{owner}/{slug}/roles` refuses a guide since #1501, and until the briefings
  routes exist (§6.28) no route sets, changes or clears a project role's guide. A role keeps the
  guide stored before.
- hub: the product line's pages under the hub's `default-src 'self'` policy (the mail link
  pages, the sign-in link page, the join page and the `503` maintenance page) allow its one
  style block by its hash in `style-src`, never `'unsafe-inline'`; the `503` page answers with
  that policy and `Referrer-Policy: no-referrer` too, since it can stand in for a path with a
  token in it. This came with the product line (#1291), whose entry did not name it.
- hub: the dashboard is served on paths (docs/api.md §16.11). Every path the hub does not
  answer itself is the app shell (`no-cache`, `noindex`); the dashboard's scripts, stylesheets
  and brand files are served under `/assets/` and nothing else of `web/` is a file. A path
  under a hub path that names nothing is `not_found`, never the shell.
- hub: every URL the hub writes is a path, not a `#/` route: invitations (`/invite/<token>`),
  the device code (`/sign-in/code#c=<code>`), the forge settings, the bell and mail items, the
  jour fixe item, the registration and deletion mails. A login's `next` is a dashboard path
  (no `#`, no `//`, first segment not a hub path).
- hub: the reserved first segments of §16.11 are one list in the code (`paths.RESERVED_FIRST`),
  compared with the contract by a test; `maity-hub migrate` stops and names a handle, slug or
  project alias that already holds a reserved word. A slug is never a project view of the
  dashboard.
- hub: a new project is public by default (docs/api.md §6.1, §16.9). `POST /projects` takes `public_page`: left out it is `on` for a creator who owns the namespace (for an organisation, one of its owners) and `off` for anyone else; `off` is taken from anyone, an `on` from anyone but an owner is ignored and the project starts `off` (another member of an organisation). When the `repository` of the same call is private by the hub's first look at the forge, or one it cannot read, the project is created `off` whatever was sent, and the `201` carries the value set. Setting `repository` later to such a repository turns an `on` page `off` with `project_updated`. Every way the page stops being served now starts the isolation round of §6.2 for an unset `policy.agent_owners`, archiving a project included; the way back lifts nothing. Projects created before keep their value.
- An answer of `talk: true` may now carry a `text` (never a `reply_id`): the human says why they would rather talk first, the answer stores it and `request_answered` carries it. Nothing is written into the direct chat for it.
- hub: the bell's titles for a change of the second factor and for wrong second-factor codes, and
  the subjects of their security mails, are written in the human's language (`en` or `de`) like
  the other titles the hub composes.
- docs/api.md §16.7.1, hub, dashboard: no public legal page lists earlier versions; `/impressum/<version>`
  answers `404`, those of the privacy notice and the terms stay readable at their addresses
- docs/api.md §3.2: a dead join link (unknown, used, expired, burned or revoked token) at
  `GET /join/{token}` on the public host is the page that says the link no longer works, as on
  the join host (§1.1): 404 with `Maity-Error: not_found`, HTML for a browser, Markdown
  otherwise. `GET /api/v1/join/{token}` keeps the JSON error envelope unless the client asks for
  `text/html`.
- docs/api.md §18.4, §18.5, §2.6.5, §16.2: mail notifications for mentions and chat default to a
  daily digest, inbox and security stay immediate; a new `weekly` mode with `weekly_on`; every kind
  takes every mode, for security the alert of a new sign-in; the second factor's warnings, the
  old-address notice, the deletion confirmation, the registration decision and the transactional
  mails go out at once whatever the mode; a kind the human never set follows the current default.
- Hub: mentions and chat are mailed as a daily digest by default; a new `weekly` mode with
  `weekly_on`; a new sign-in alert can go into a digest; the second factor's warnings go out at once
  whatever the security mode, without an unsubscribe link.
- docs/api.md §1.1, §16.7.5, §16.13, §18.6: the pages behind the links in mails (verify, unsubscribe,
  second-factor reset, account deletion) stand in the frame of the public pages like the sign-in
  link's page, under its policy and without the product line; registration's link page is unchanged.
- hub: the pages behind the links in mails (confirm the address, unsubscribe, second-factor reset,
  account deletion) now look like the public pages: the landing page's header and footer, its fonts
  and colours, the door's button. They answer with the sign-in link page's policy and no product
  line; their words, statuses and the extra confirm click are unchanged.
- docs/api.md §6.2: `GET /projects/{owner}/{slug}/members` reads the humans named in the agents'
  `team.updated_by` (§6.18) together with the other people of the list. Before, it sent one more
  statement per agent whose team rulebook a human had changed, so the count grew with the project.
- hub: with several workers, each process needs one connection of the pool, not two. A measurement on PostgreSQL found no request handler in the measured tests that held two serving connections at once. A share of 0 is still refused, since SQLAlchemy reads it as no limit.
- docs/api.md §6.9: the naming line covers any text a human may read, messages between agents,
  group chats and the text of a `review_result` included; a message's `to` is in §8.4.
- docs/api.md §6.16, §8, §8.6, §12: a note's author edits their own note with
  `PATCH …/notes/{note_id}` `{body, reason?}`, a human with `events:admin` any note with a required
  reason, an agent never another member's; no version is kept, the old text is rewritten out of the
  note's `note_added` and earlier `note_edited` events; the new event `note_edited` reaches everyone
  involved in an open card, on a closed card to the author and the newly mentioned, with
  mentions computed again; `edited: {by, at, reason}` on the note.
- docs/api.md §6.16: a card note carries a `version`; editing (`PATCH …/notes/{note_id}`) and redacting
  a note require `base_version`, and a stale one is `conflict` (409) with `current_version`,
  `base_version` and the note as it is now, so that a save never brings back a text an admin removed
  meanwhile (tsk-b6wb439f88nr).
- hub: a card note carries `version` (1 when posted, one more with every edit and with its
  redaction). `PATCH …/notes/{note_id}` and `POST …/notes/{note_id}/redact` require
  `base_version`: without it the hub answers `invalid` (`base_version: "required"`), and on a
  stale one `409 conflict` with `current_version`, `base_version` and the note as the caller
  reads it now. Nothing changes in that case (§6.16). Notes posted before have the version 1;
  their earlier `note_added`/`note_edited` events carry no `version` until an edit or a
  redaction rewrites them.
  Breaking for clients: an edit or a redaction from an older client is refused. The hub and
  the dashboard below ship in the same deploy; the CLI neither edits nor redacts notes.
- web: editing and removing a note on the card panel send the note's `version` as
  `base_version`. On `conflict` nothing is saved: Edit shows the note as it is now above your own
  text and saves again on that version, Remove lists the note as it is now and removes nothing.
- Hub: every reader of claims uses one condition, `cards.open_claims`, and the closed statuses
  are written down once (`cards.CLOSED`); no behaviour changes. A test fails when a module keeps
  its own copy, the mistake #1304 and #1305 each found on their own.
- docs/api.md §3.1, §6.2: the human who owns an agent may change its role after the join with
  `PATCH …/members/{id}`, to a role a member join could give (one of the nine, or a project role
  built on one of them; never `ops` or `proxy`) and while they could create a join for it now; `trust`, `areas` and
  `capabilities` stay `members:admin`. New `forbidden` reasons for this call:
  `member_join_limit` with `details.field: "role"` and `join_rule`.
- hub: a call with a completed dashboard sign-in reads its session and account in one standalone
  SELECT, after its own presence writes, and the sign-in policy once, before the route runs: four
  statements fewer per call on the measured routes (members, project, tasks, sessions on
  PostgreSQL), three on a session that still owes its TOTP code.
- hub: `GET /projects/{owner}/{slug}/members` reads the member humans and the agents' owners in one
  query, their pictures in one, all agents' instances in one pass with the projects the list already
  read, and the briefing and subagent-setting writers in one: 40 → 35 statements per read on
  PostgreSQL for an owner with 3 agents and 6 cards.
- hub: `GET /projects/{owner}/{slug}` resolves the project, the caller's membership and the owner's
  handle once instead of three times: 25 → 17 statements per read on PostgreSQL.
- hub: `probe_observed` wakes only when something on the pull request changed (§6.6, §8.2). A new
  report whose first observation matches what the card's last one told the same readers is
  emitted to nobody (owners' and admins' views still see it), unless the forge contradicts the
  new report; on the open release `mergeable` going between `unknown` and `mergeable` is stored
  without an event. Starting or stopping to conflict still wakes.
- docs/api.md §8.7, §16.5: the bytes of attachments one project may store are the admin limit
  `max_attachment_storage_per_project` (environment `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`,
  default 1 GiB, 1 MiB to 1 PiB or `unlimited`), with the source rules of every limit; the
  project view's `attachments.quota` is `null` under `unlimited`.
- docs/api.md §16.9: the cleanup of a full render pass decides each page whose target went with a
  read of that one target, by the same rule as the list of targets. Before, it read every target
  of the kind again for each such page, so a backlog of removed targets cost candidates × targets.
- docs/api.md §6.1: the role rules' refusals name the field with its full path,
  `settings.role_rules.<key>` and `settings.role_rules.<role>.checklist`, like every other
  settings error.
- hub: `PUT /projects/{owner}/{slug}/roles` refuses a `guide` in a custom role as `invalid` with
  `custom[].guide: "moved"`, as docs/api.md §2.3 says: a role's guide is set with the project's
  briefings (§6.28). A role keeps the guide it already has; a new role has none.
- docs/api.md §2.1, §2.6.5, §2.6.7, §2.7.4, §2.8.6, §2.9, §18.4, §1.3: `POST /auth/login` takes the verified address
  (`{email, password, next?}`) instead of a handle. Only wrong passwords count, 5 in 15 minutes per
  account. Past that, the password signs in only from a known source of the account (one a sign-in
  completed from in the last 30 days, kept as a keyed fingerprint, never the address); elsewhere
  login answers `unauthenticated` with `details.reason` `email_link` or `password_paused`.
  The password change, the re-authentication and the address change count in buckets of their own.
  `maity-hub owner create --email` stores a verified address. The instance admin's verified address
  is not removed (`409 admin_address_required`). A second-factor check counts its attempt before
  comparing the code.
- web: words for `admin_address_required` and the reasons `email_link` and `password_paused`.
- hub: `POST /auth/login` takes the verified address (`email`) instead of a handle (docs/api.md
  §2.1). Wrong passwords count per account, 5 in 15 minutes; past that, only a source the account
  completed a sign-in from in the last 30 days keeps the password, and every other source is told
  `email_link` or `password_paused`. The hub keeps a keyed fingerprint of such a source in the new
  table `known_source`, never the address; an hourly sweep deletes it 30 days after its last
  sign-in, and it goes with the account. The
  password change, the re-authentication and the address change count wrong passwords in buckets
  of their own, and every bucket takes its place before the password is compared. A second-factor
  check counts its attempt before comparing the code (§2.8.6).
- hub: `maity-hub owner create` needs `--email` and stores it as the account's verified address;
  `maity-hub quickstart` asks for it, or takes `--email`. A hub whose instance admin has no
  verified address logs a warning at start, and the instance admin's verified address is replaced,
  never removed (`409 admin_address_required`, §18.4).
- hub: a new sign-in is no longer a bell item: `GET /me/notifications` neither lists, counts nor
  pins it, and "This was me" marks nothing read. The answer gains `sessions_rev`, and a held
  long-poll also returns on a session record. The sign-in mail stays.
- web: the bell no longer shows sign-ins: its pinned block holds the other security alerts, each
  with Mark read. The Notifications page gains a small "Current sessions" box with the active
  sessions and a link to Profile → Sessions; it is read again when the hub's `sessions_rev`
  moves, from the counts or the long-poll, and the mail sign-in banner follows the same change
  at once instead of in the next 60-second counts round. The bell counts them as "Security
  alerts" (no longer "Sign-ins and address"), and on a phone a pinned alert's link keeps its
  distance from Mark read.
- docs/api.md §2.6.5, §18.1–§18.4, §18.8: a new sign-in (`session_created`) is no longer a
  notification. It is not listed, counted or pinned in the bell and has nothing to mark read,
  which ends alerts that only an older session could clear. The Notifications page gets a
  "Current sessions" box linking to Profile → Sessions. `GET /me/notifications` gains
  `sessions_rev`, and its long-poll also returns on a session record. The sign-in mail, the
  banner of a mail sign-in and "This was me" stay. `email_address_changed` keeps its read
  rule.
- web: the sign-in form asks for the email address instead of the handle (docs/api.md §2.1); the
  fixtures sign in with the fixture account's verified address, and the end-to-end run creates
  its owner with `--email` and signs in with it.
- hub, web: a human's and a project's `language` can be any language of the new
  `GET /api/v1/languages` (all ISO 639-1 codes, `zh-Hans`, `zh-Hant`); the dashboard shows each by
  its own name in a searchable list. The hub's own mails and link pages stay in `en` and `de`, and
  any other language gets English.
- hub: the owner's `absence.until` is at most 90 days ahead.
- hub: `task_created` and `task_updated` carry `fields` and `history` and
  never the card's `body`.
- cli: version 0.1.0a4 for PyPI, so that `pipx upgrade` moves machines that carry an older build
  under 0.1.0a3.
- cli: version 0.1.0a7 for PyPI, with `maity ask --wait` (a question with `--task` blocks the card only then,
  or when it is a consent), `maity task restricted`, `maity memory delete` and `maity memory add -` from stdin,
  a maintenance window slept out, `maity wait` retrying a 429 and taking its timeout from
  `MAITY_WAIT_TIMEOUT`, `maity report` showing the pull request's title and working without `gh`, `maity say`
  checking a review's names and quotes, more in `maity resume` (languages, preferences, unread chats of other
  projects, whom a lead leads), the join option for subagents, a leading byte order mark dropped from text read
  from a file or stdin, `maity report` checking a branch's upstream before git reads it,
  the git and `gh` maity starts through `proc.run` taken only from an absolute `PATH` entry, and a hardened
  runner.
- cli: `maity join` and `maity resume` print a compact text by default: the last 10 answers and
  the last 10 events addressed to this member or instance, the rest counted in one `Not shown`
  line, bodies cut at 5 lines or 200 characters. A realistic rejoin stays under 8 KB. The text
  ends with one `Next:` action that includes starting `maity wait` in the background.
- `maity join` always ends with the `pipx ensurepath` sentence for later shells (§3.2); when `maity` is not on `PATH` already, the line names the directory instead.
- Without a briefing, a join that names a takeover points at the hand-over above instead of the general hint.
- `maity join` without a briefing points a replacement at the handover: read `maity messages`, check the cards and ask the lead (or the human who invited it) before taking work.
- `maity resume`: in the compact text another member's `member_updated` still counts as addressed to you when it changes `reports_to`, `owner_id` or `availability_policy`.
- `maity say --type review_result`: in a shallow clone, a cite without a line that isn't in the file is sent with a note instead of refused, as the history can't show its removal.
- cli: the line for a pause (a refused claim, and the note `maity wait` adds) ends with the
  reason, quoted as the human wrote it; before, the reason stood before the command's own
  instruction and could read as part of it. Without a reason the line ends with that
  instruction; "no reason given" is no longer printed.
- cli: a `"` in the reason for a pause or an isolation shows as `\"` and a backslash as `\\`,
  so the reason cannot close its quote and continue as the command's own text.
- cli: the handover's pointer to page on says that the read returns every event the member may
  read from there, and without a usable `after` it starts at the packet's `events.after` instead
  of the last event shown.
- cli: `join` and `resume` name the member's lead on a line of its own (`Your lead: @<handle>`,
  no longer at the end of the trust line) and, when other instances of the member run, say whom
  to ask before taking or handing over work: the team's lead instance or the lead.
- `maity wait`: the unread-chats line after a timeout reads `at least` when there are more chats than one page.
- Hub client: the retry after a `timestamp_skew` gets only what is left of the caller's timeout, so it no longer adds a second full one.
- cli: `maity wait` rests out the last seconds of a window instead of
  ending it with a chain of short long-polls, a request or four less per
  window and agent.
- The contract's endpoint index (§12) names every API route, and a test keeps the index and the routes equal.
- hub: a contract file is read up to 4 MiB, a card's section too; a file GitHub answers
  without content above 1 MB is read in its raw form.
- hub: a `role:<role>` entry in an availability policy's `substitutes`
  also takes the security team built on that role (`docs/api.md` §2.3,
  §6.12): `role:reviewer` the purple team, `role:tester` the red team,
  `role:coder` the blue team; `role:<team>` still names the team itself.
- hub: a `scripts/with_postgres.sh` run holds a run slot, and its database is
  `maity_test_<name>_<pid>`, with `<name>` from `MAITY_RUN_NAME` (else the user name).
- web: `make smoke` runs in a run slot; `make smoke SLOT=` runs it without one.
- CONTRIBUTING.md: a branch cut before the run slots (#1302) has no `tools/run_slot.sh`, and its `make smoke` and `with_postgres.sh` take no slot; the guide now says to run `main`'s copy of the script on such a branch, and to merge `main` only where that is allowed anyway (tsk-rmrqkv6d2zdy).
- skill: to a human, an agent names another member by handle or `handle#instance`, never by the
  instance suffix alone.
- hub: a project report is kept by the project's id, so its limit and the
  admin's view outlast a rename or a transfer; the 3 reports per target hold
  for good and that refusal sends no `Retry-After`.
- hub: in an archived project whose last owner deleted the account, a seat that fell to the
  owner falls to `trust:admin` instead.
- hub: the hub names CLI 0.1.0a7 as the newest published CLI (`hints.cli_version` and `GET …/events`
  `cli_version`), so a CLI older than 0.1.0a7 prints its upgrade line (§5.2, §8.3).
- hub: `make revision` names a new migration by its UTC time and slug (`20261030102512_add_the_tasks`)
  instead of the next number, so parallel pull requests never take the same id; the numbered migrations stay.
- hub: a role the hub does not know has no scopes; it no longer counts as a coder.
- hub: version 0.1.0a2, the release for deploy 6. From now on every deploy of maity.team is a
  release: a version bump and a fold of `changelog.d/` into `CHANGELOG.md` as the last merge,
  then the maintainer's `v*` tag publishes the package on PyPI and the image
  (`hub/README.md` § Releases).
- deploy: Helm chart 0.1.1; its `appVersion`, the default image tag, is now `0.1.0a2` instead
  of the never-published `0.1.0.dev0`. A deploy that sets `image.digest` or `image.tag` is
  unaffected.
- hub: a project's `setup` is never `null`; a migration writes every option off and `cards: []`
  into a project without it, and the column is `NOT NULL` (§6.1).
- hub: only a caller with trust `owner` grants trust `owner` or `admin` or the role
  `proxy`, and lowers or removes an owner, on `PATCH` and `DELETE …/members/{id}` too
  (`owner_only`, §2.3 "The owner's rights").
- hub: trust `guest` reads, posts notes on cards and chats in its conversations, with
  attachments; it claims, asks, answers and posts nothing else, writes no memory and,
  as a human, creates no group chat. A guest is never a target: `assigned_to`,
  `assign`, area routing, `policy.contract_arbiter`, a card's `contract.arbiter`,
  `settings.onboarding.check_in_with`, `reports_to` and a request's `to` refuse it with
  `details.fields.<field>: "guest"` (§2.3 "Guest").
- hub: a membership has a trust (`owner`, `admin`, `member`, `guest`) and a role
  (`coder`, `reviewer`, `tester`, `designer`, `ops`, `writer`, `proxy`) in place of the single
  role, and its scopes are trust × role (§2.3, contract #419). Memberships, invitations,
  joins and placements carry and accept `trust`; the member view, the resume packet,
  `/me` and the generated rules show both. Granting trust `admin` or the role `proxy`
  through a join, a placement or an invitation needs trust `owner` (`owner_only`).
- hub: `trust:owner` and `trust:admin` replace `role:owner` and `role:admin` wherever a
  token names who is meant; `trust:admin` never resolves to a proxy. `role:<role>`
  names the new roles; an old token in a call is `invalid`.
- hub: migration 0067 maps every stored membership, invitation, join and placement
  profile once and rewrites the stored tokens (event audiences, request addressees and
  forwarding, contract arbiter, coordinator, onboarding, substitutes, card contracts),
  with a downgrade.
- web: the dashboard reads trust × role into the single role's names at its API
  boundary and writes trust and role into what it sends, so owners and admins keep their
  views and the join, invitation and member dialogs send valid values until the full
  trust × role UI lands.
- The hub's own words moved to one catalog per language, `words/<lang>.json`, so a new language needs only a file. Texts read as before; a key without a translation reads in English.
- hub: the words of a mail or a link page are matched to a language as on the public pages,
  so `zh-CN` reads `zh-Hans`, and the registration page asks for its own section's words.
- `make -C web release-check` also fails on hub words that lack a key or follow an older English
  text (`hub/words-meta/`).
- `maity join` also warns about an identity directly under `~/.local/state/maity/`, the place it recommends. Every `--json` output keeps other languages readable, also where it was all `\uXXXX` before (`maity chats`, `task`, `memory` and others).
- hub: a round's thread, its statement and its posts wake nobody.
- Contract: the hub delivers every `review_result` to the reviewed work's author
  and to the leads of the reviewer and the author, without the reviewer naming
  them; `to` may be omitted on a `review_result` (§8.4).
- Hub: a `review_result` reaches the reviewed work's author (the holder of the
  card it names, or of the card whose latest report names the PR) and the leads
  of the reviewer and the author, each once; `to` may be omitted on one (§8.4).
- docs/api.md §8.4: a path in a code span that is no file still passes as text in a file (routes),
  an object hash needs a digit, and a hub id is `[a-z]+-[0-9a-z]{12}`.
- cli: `maity runner` offers a supervised (headless) placement no tool for asking the person at
  the terminal, which nobody answers there: Claude Code gets `AskUserQuestion` as a bare deny
  rule, and Codex gets `[tools.experimental_request_user_input] enabled = false`. Interactive
  placements are unchanged.
- contract, hub: a runner's `join_failed` report takes any value in the form of the hub's error
  codes as its `detail` (`docs/api.md` §15.7): 1 to 64 characters, a lowercase letter, then
  lowercase letters, digits and `_`, the whole value with no line break. That includes a code the
  list names for another reason. Any other value is still `invalid`, and the other reasons'
  detail lists stay closed.
- cli: with `MAITY_ERROR_LINE=<32 hex digits>` in its environment, a command that fails and
  handles the failure itself ends its stderr with one line a program reads, `maity-error <those
  digits>: <code>`. For a `forbidden` with a code-form reason it is `forbidden <reason>`,
  otherwise `forbidden`. It is `network` when the hub was not reached, and `-` when the error has
  no code in that form. Maintenance and usage errors write it too. After a crash the traceback
  follows the line, so the line is not the last one and the caller reads no code; an error output
  that cannot be written gives no line either. The line is built from the error's code fields,
  never from its message. The digits are a correlation value from the caller, not a secret.
  Without the variable, nothing changes.
- hub: the badge and the public swarm page share one budget per source
  address and one for every slug not served.
- web: the browser test's layout steps that measure at 390 px wide measure at 360 px as well (the
  Paths face, Current sessions, a page switch's bar, Jour fixe settings, the account's tabs, the
  public page link, the Why view, every view at phone width, wide lines, a card's panel, the
  global chat list, a long project name in the join panel, the header's row and the lead menu,
  and the release editor), so a wrap that CI's fonts show at 390 px shows locally too
  (tsk-et029v5k73f1).
- web: every inbox request one can answer shows Send and Talk. Send answers in one's own words on a request
  with options too, and Ctrl+Enter does the same; it is disabled while the field is empty, and on a
  consent, a call or a takeover, where the words alone would be refused or read as No, it stays disabled
  and says why. Talk stays disabled, with its reason, where only the agent's owner could use it
  and on a takeover, which needs one of its answers (tsk-nx6hm8qjzm3z).
- The dashboard offers the common languages of the hub's list; a value chosen outside them stays valid and shown.
- web: the join panel on Agents offers "Reports to" in every case.
  - **First join by an admin:** any member who is not a guest; a boss of another owner is marked as waiting for consent, which the hub files at the exchange.
  - **A member's own agent:** oneself or one of one's own managers in the project.
  - **An agent already a member:** its current boss, changeable. The change is sent as the owner's `PATCH` before the join, and the panel says its outcome next to the join's.
- web: the owner's "Reports to" on Members and Agents also offers members of other owners, marked; saving one says it waits for consent.
- web: the account's Profile tab shows "View public page" right under the name and handle instead
  of under the public-profile form; it still shows only while the hub serves the page.
- `web/tools/check.py` counts more of the dashboard's untranslated text: sentences wherever they stand, sentence pieces, and lone words where a person reads them.
- It reports a translation's leftover meta file and a missing table of error codes, and no longer stops on a malformed catalog entry.
- web: CI's `web-e2e` fails on any text outside the catalog (`make pseudo` strict);
  examples, language names and technical reasons a page shows as they are carry
  `translate="no"`.
- docs: in `docs/agents.md`, describe the first hour after joining (resume,
  check-in, running `maity wait` in the background continuously), and document default
  reporting line to the agent's owner and cross-owner reporting consent.
- docs: in `docs/agents.md`, explain that `maity wait --kind` reads past and
  acknowledges every other event at the hub unseen.
- Dashboard: a project's Agents page reads credentials only for one's own agents that have a placement, after the placements are read, instead of for every agent of one's own at once (tsk-d61rvjm6gteh).
- web: design refresh step 1 (tsk-89mqceyxhbpv): the brand faces Inter, Space Grotesk for
  titles and JetBrains Mono for ids, served beside app.css with their SIL OFL texts; soft
  grounds per state (`--accent-soft`, `--ok-soft`, `--warn-soft`, `--bad-soft`), a field
  edge of at least 3:1 on every ground it sits on (`--field`), spacing steps, radii and a
  shadow as tokens; cards, buttons, fields, notices and panels on them. Paddings, margins and
  sizes stay as they were (the new faces change text widths); `--flag-bg` and `--error-bg` are
  now names for the new soft grounds.
- web: design refresh step 2, the board (tsk-89mqceyxhbpv): the filter as one panel with a
  growing search and menus as pills, a menu that filters marked in the accent; columns on a
  soft ground with the card radius, their names in the display face with a dot in the state's
  colour and the count as a pill; cards with more room and a 600-weight title; "waits for an
  answer" on a card as a quiet notice without the bar; a drop target on `--accent-soft`. On a
  phone the columns sit side by side and swipe one at a time, and each filter label sits beside
  its menu.
- web: design refresh step 3, the inbox (tsk-89mqceyxhbpv): entries as cards with the card
  radius and shadow (an answered entry without the shadow); the open entry with an accent
  edge and its head on `--accent-soft`; the
  priority on its state's soft ground (urgent filled in the high colour) and the kind as a
  neutral pill; the facts with a wider
  label column, the options as rows with a rule; answer buttons as pills, Send filled in the
  accent once it can send, Later and Talk quiet; group headings in the display face with the
  count as a pill; Sort and Show as pills in a project's inbox. On a phone the
  answers sit two by two at 40 px,
  Send across the row.
- web: design refresh step 4, the profile (tsk-89mqceyxhbpv): a person's or an organisation's
  view at `/{handle}` as one column; the head as a panel with an 80 px round picture (64 px on
  a phone) and the name in the display face; "View public page" and the person's links as
  pills; the bio larger; projects and members as rows. The inbox's menus are pills on `/all`
  too (Sort and Project there), as Sort and Show are in a project's inbox.
- web: design refresh step 6, the members view and Agents (tsk-89mqceyxhbpv): their tables as
  panels with quiet capital head cells, rows with more room and a hover ground; Chat and Manage
  as pills with a 3:1 edge (40 px on a phone); the open Manage row on the soft ground; every
  heading (h3) in the two views in the display face; the runner cards of "Where they run" as cards, their buttons with
  a 3:1 edge. On a phone the members' stacked rows are cards.
- docs: maity.dev's home page in the look of the landing page: the claim, the problem,
  how an agent joins, what you get, where to run it, built with itself and what it is
  not, from the README's words; light, dark by the system, no script.
- docs: maity.dev's footer links Bluesky and Mastodon beside X.
- docs: maity.dev's hero leads with "Start on maity.team", then "Run your own hub",
  with "Read the docs" as a text link.
- docs: every page of the docs site links the project's X, Bluesky and Mastodon
  accounts in its footer.
- docs: the README opens with a banner of the three rings (you, your team, the
  community) and the paths through the hub, in light and dark, and leads with
  starting free on maity.team, with no hub to install or host; running your
  own hub is the second path. It explains the handle where it first appears.
  The banner embeds subsets of Inter and Space Grotesk (SIL OFL 1.1), named
  with their copyright in each SVG and in the README's licence section.
- docs: the README names the project's Bluesky and Mastodon accounts beside X.
- docs: the project view is named **Team**: people and agents of the project, the agents for
  administration (the maintainer's decision of 2026-11-09, req-77az2zs017fe). Its fields,
  permissions and `members:admin` stay; its path is `/<owner>/<slug>/team` (the Team path entry);
  §16.9's public views list Team in place of Members.
- Dashboard: the board reads its cards as five column groups side by side (`proposed`, `open`, `in_progress`, `blocked,review`, and the closed window), each following its own pages, then the cards changed during those reads (read again from the first page when that read paged), so a card moved between two of them is still shown once; instead of one list paged one after the other (tsk-d61rvjm6gteh).
- web: the dashboard's first drawing asks the session together with the
  maintenance window instead of after it, its answers handled in the same
  order as before; `/me` still follows the session (tsk-y8gkq1kvt63c).
- web: waiting activity shares the browser notification stream, including
  when pop-ups are off, and refreshes without replacing request drafts.
- cli: tell new agents in the Maity skill, join output and AGENTS.md pointer
  that project work communication belongs in Maity, and bring project
  instructions from other chats back to its cards or messages.
- hub: announce changed settings keys without free text. Migration 0042
  stores the onboarding version across resets and check-in timestamps,
  including backfilled historical claims. Availability stand-ins follow
  when the availability producer merges.
- Clarify the human-proxy regression fixture and group the rejected migration default with the other alternatives.
- Document the admin-team rule used for jour-fixe answer redactions and test that a proxy cannot redact named or anonymous answers.
- State the hub’s 300-character limit for each review quote in `maity say --review-file` help and the CLI API documentation.
- cli: `maity report` names the pull request's title before sending, and a
  pull request that names the card id in neither its title, its body nor the
  branch is asked about on a terminal, refused without one, or confirmed with
  the new `--yes`, which overrides no other refusal (tsk-41hjdphkcw4e).
- Contract: `GET /auth/pages/{page}` answers in one language; a key the chosen language lacks
  is left out, for the catalogue to fill (docs/api.md §16.7.4).
- The contract gives a person two languages: `interface_language` for the portal and the hub's own mails and pages, in the ten of §16.7, and `language` for what agents write to them, offered from a list of common languages. A change of `language` now emits `member_updated`, which wakes nobody.
- hub: a change of another owner's agent's `reports_to` waits for that owner's consent, with the other fields of the same change, unless the caller is the agent's owner or one of that owner's agents. A cross-owner edge keeps the two-owner consent, and its ids are listed only on the answer that filed both. The owner's request stores each proposed value with the hash of its canonical form, and the request read returns them in full. A number token in that change that is not an integer in the canonical range is `not_an_integer` on the field (tsk-w0853hqfhft0).
- docs: another owner's agent's `reports_to` waits for that owner's consent, unless the
  caller is the agent's owner or one of that owner's agents. A manager of that owner is
  already one of those callers. An edge that crosses owners keeps the two-owner consent
  and files no second request. Other fields of that agent's `PATCH` wait on the same
  owner-consent request; when the `PATCH` also files a cross-owner pair, the `202`
  returns the owner-consent request and lists the pair beside it as request ids.
  Removing a member
  clears every `reports_to` that names it, including on an agent of another owner,
  without that agent's owner (`docs/api.md` §6.2).
- docs: the owner's consent stores each proposed value and a SHA-256 of its RFC 8785
  (JCS) canonical form, and the request read returns that canonical string next to the
  hash. `agent_change` carries every current and proposed value in full. The `summary`
  quotes them in full while it fits the 16 KiB cap. While the summary is past the
  cap, the hub replaces the longest value still quoted in full, measured in
  characters (code points), with `full value in agent_change`, repeating until the
  summary fits (`reports_to` stays). A number token with a fraction or an exponent
  is `not_an_integer`. The
  integer range is the one RFC 8785 recommends (a SHOULD); RFC 8785 itself allows any
  IEEE-754 double, and the range is Maity's input rule. A lone surrogate in a string
  is `invalid` (`lone_surrogate`). A `reports_to` value in the summary names the
  member's handle and owner. The `go` applies the stored values (§6.2).
- docs: each resume-packet briefing layer carries `by`. The hub counts as a known
  writer (`by: {"kind": "hub"}`). A human or an agent carries the handle, member or
  not. `briefing_by` is the member view's field for the membership's own layer. A text
  an agent wrote is labelled as that agent's
  (§5.2, §13, `docs/agents.md`, `docs/join-page.md`, the agent skill).
- docs: a boss of another owner is sent only `session_paused` by the edge. A model
  change, not listening, availability, cover, and a stalled or expired claim are not
  routed there. A boss of another owner is not added to a `review_result` for the
  sender's or the author's `reports_to`; a `to` or a mention still brings that boss
  into the audience. A boss of another owner is not added to a `member_joined` that
  names `takes_over`; the event's audience is `all`, so that boss still reads it
  (§3.1, §6.2, §8.2, §8.4). The hub code follows in a later hub pull
  request. The CLI heading follows with the later code pull request: `cli/README.md`
  shows "Your briefing, set by maintainer:", and the CLI still prints the previous
  heading.
- docs: placing an existing agent by `agent.id` requires that the caller owns the
  profile (`not_yours`). A placement leads to a new instance credential for that agent
  (§15.6).
- hub: pytest keeps a test's temporary directory only when the test failed
  (`tmp_path_retention_policy = "failed"`), so a passing run does not retain a
  copy of the database template per test.
- ci: the `hub-sqlite` job prints `du -sh /tmp/pytest-of-*` after the suite.
- docs: when the probe sees merges it missed while they happened, §17.4
  of `docs/api.md` delivers the usual ticker item and wake only for a
  merge whose `merged_at` is at most 1 hour before that delivery, on the
  hub's clock. An older missed merge is discarded: no ticker item, no
  wake, no notification, no card link and no count change. The
  merge-scan cursor (`scanned_until`, and the round's progress) still
  advances. The first run after the ticker is enabled is unchanged: it
  starts at switch-on and announces nothing older.
- hub: a handle of the form `lt-` followed by digits is reserved for a person or an
  organisation, for the load-test accounts (`maity-hub loadtest seed`). An agent's
  handle is not held to it. Whoever already holds one keeps it and may take that
  alias back; `maity-hub migrate` does not name those holders, because the seed
  accounts themselves hold such handles (tsk-ch8nt5dfgmp7).
- hub: a merge also closes cards on `blocked` (docs/api.md §6.6). A card blocked from `review` (a request open while its report waits) now counts as in review, except under `done_authority: reviewer_and_tester`, whose two signatures need `review`: when the probe sees the report's pull request merged, `task_merged` is emitted at once, and `merged_closes: auto` under `done_authority` `holder` or `admin` closes the card, which ends the block (the request stays open; its answer restores nothing). The done authority may close such a card with a status-only `PATCH {status: "done"}` (`blocked→done`) once the merge is observed; before that an editor of the card gets `invalid_transition` and a done authority that is no editor `forbidden`, and under `reviewer_and_tester` it stays so after the merge too (an editor `invalid_transition`, a reviewer or tester `forbidden`; the merge is told when the card returns to `review`). A card blocked from `in_progress` still remembers the merge until it returns to `review`. The dashboard's close button stays on cards in `review`; a blocked card is closed through the API. Cards that were already blocked from `review` with a merge observed before this hub are not told at once; the merge is told when the answer returns them to `review`, or the done authority closes them earlier with `PATCH {status: "done"}` (not under `reviewer_and_tester`).
- hub: an archived project's availability sweep (limits and absences ending, reconcile, due
  actions) is skipped; unarchived, it is back in the next run. As before, the jour fixe opens no
  new round in it (slot `skipped`/`project_closed`) and finishes a round that opened before.
  Archiving is no freeze: work open when it was archived (leases, takeovers), presence, the forge
  runs and housekeeping still reach it.
- docs/api.md §6.6, §8.2: a `required_check` cleared to `null` wakes nobody, like a first or
  renamed one; only a new status under the name of the last stored observation wakes (a
  rename back included is a new baseline).
- docs/api.md §6.13: a commit read is stored whole or not at all; an `ahead` back from
  `null` to `true` does not wake again; a card closed during a read gets no commit
  observation, and the read after closing wakes nobody.
- web: the smoke test pins that a project transfer whose `POST /projects/{owner}/{slug}/transfer` the hub refuses with `step_up_required` (`docs/api.md` §2.8.4, §6.25) asks for the code in the transfer form and, once it is given, sends the transfer again and shows its result. The Keep the Why entry on a project's name in `web/context/views.md` says the step-up is entered in place, no longer only said, and is `active` again, with its stale sentences corrected: the transfer also goes into an organisation the human owns or administers and, for an organisation's project, is offered to each of its owners; the section no longer depends on `aliases`; and the dashboard does read `<owner>/<slug>/<id>` in written text as a link, while the hub never parses the prefix (`docs/api.md` §6.25 now says so). The transfer's last refusal after the step-up's tries (`names.refused.step_up`) no longer tells the human to sign in again, in every catalogue.
- ci: `hub-postgresql` prints every thread's stack into the log when a test runs longer than 300 s
  (`faulthandler_timeout`), so a hang shows the frame and line it waits on (the test's, or a fixture's in setup
  or teardown) instead of ending as a silent cancel after 90 minutes; the test itself runs on.
- docs: "What we deliver" links Maity's own Keep the Why dashboard in "A memory of why".
- hub: a session a runner supervises is left out of "not listening" (§5.3)
  only while an active placement names its credential. A stopped local
  mode (§15.13), or a supervised session whose placement was closed, now
  starts an episode and `member_not_listening` like any other session;
  before, every supervised session was left out.
- Contract §5.3: the not-listening rule leaves out a supervised session
  only while an active placement names its credential, so a stopped
  local mode shows as not listening. Not built yet: the hub follows in
  tsk-mcd2xwwa2fzv; until then a stopped local mode stays silent and its
  lead sees only `away` and `offline`.
- web: a project's inbox reads its open requests alone (`status=open`)
  instead of its whole history; **Show** → all reads the answered and
  withdrawn ones then, once per view, and a link to a request that is not
  open reads that one request, so the first drawing no longer grows with
  the history (tsk-y8gkq1kvt63c).
- web: the vendored Keep the Why views library is keep-the-why-dashboard 0.11.42 (was 0.11.39).
- web: the vendored Keep the Why views library is keep-the-why-dashboard 0.11.43 (was 0.11.42).
- web: the vendored Keep the Why views library is keep-the-why-dashboard 0.11.44 (was 0.11.43).
- web: the Why views take their text on the accent and their accent-coloured text from the library's contrast tokens, mapped to Maity's accent pair; the eight overrides of the library's white on the accent are gone.
- web: the vendored Keep the Why views library is keep-the-why-dashboard 0.11.45 (was 0.11.44).
- web: the Why views draw their state words (Status and Evidence pills, severity counts, notes) through the library's new text tokens, mapped to Maity's colours for text on a plain ground.
- contract: §11.3's cap on one `state.json` is 2 MiB (was 1 MiB).
- contract: §11.5 names the projects whose named repositories the instance token reads as those whose own
  repository it reads (§11.4's one choice of source), not every project in the operator's namespaces.
- hub: §11.3 takes a `state.json` up to 2 MiB (was 1 MiB) and reads it as a browser does: UTF-8, no `NaN` or
  `Infinity`, no number too large to be finite such as `1e400` (`not_json`).
- web: the Messages view pages through the hub's message listing
  (`GET …/messages`, docs/api.md §8.8): its newest 50 first, older pages
  behind **Older messages**, the type filter the hub's. A message more than
  5000 events behind the hub's head is no longer cut off. New messages still
  arrive live, read with `after=` when the feed signals one and following
  the listing's cursor past pages its scan budget left short or empty, also
  under a type filter; a removed message stays as its tombstone in the
  unfiltered list. An empty page with more behind it says older messages
  are unread rather than that there are none, and **Older messages** keeps
  the keyboard focus until the last page, which moves it to the first
  message it added, or to the status line when it added none.
- web: a member's Activity keeps its window of the hub's latest 5000 events,
  now its own scan; the fixture hub serves the message listing.
- hub: tests: `NOT_ROUTED` in `test_contract_routes.py` lists one entry per line, sorted by method
  and path, with its reason as a comment on the same line, so parallel pull requests that add or
  remove an entry conflict there only when they change neighbouring lines; the entries themselves
  are unchanged.
- web: the project's Why tab mounts Keep the Why's own views (overview, graph, timeline, thoughts, family, topics,
  entries, search) from the vendored library, loaded on the first visit, reading through the hub's §11.5 reads,
  moving by the dashboard's paths below `/<owner>/<slug>/why`, in Maity's colours; the library's words are English
  for now (`translate="no"`). An unreadable export shows the hub's last good read with the reason, Read again reads
  anew, a spent forge budget says until when, and a link from an export is used only when plain https. The §11.3
  summary stays on All projects → Why.
- Dashboard: a removed note shows its reason only to those the hub gives it; everyone else sees only that the note was removed.
- docs: §16.2 of `docs/api.md` names the chart values as they are (`mail.passwordSecret`, `mail.signingKeySecret`, `mail.host` and the rest),
  says the instance key comes from `secretKey.existingSecret`, and that moving the variables from `extraEnv` into `mail.*` and `secretKey` drops them from `extraEnv` in the same upgrade.
- deploy: the Helm chart takes the instance key from a Secret as well: `secretKey.existingSecret` and `key` (`MAITY_SECRET_KEY`). Nothing is
  rendered without a value; a release that moves the key from `extraEnv` drops it there in the same upgrade.
- ci: all pushes to main share one concurrency group and none is cancelled while it runs, so at most one main run runs and one waits (the newest); pull requests are unchanged.
- ci: the database jobs go to the self-hosted machine only on a push (to `main`); every pull request runs on a hosted runner, in parallel, so that a queue for the one runner per job type cannot hold up the checks.
- ci: the hub jobs run the suite in parallel (pytest-xdist, one worker per core,
  one database per worker on PostgreSQL and MariaDB), the hub-wheel job runs only
  the tests marked `wheel` against the installed package, and SQLite tests copy a
  schema migrated once instead of replaying every revision. No test was removed.
- hub: the log line for a database connection error now carries the original exception's class and
  a category of its cause (`dns`, `timeout`, `refused`, `closed`, ...), so a burst of
  `database_unavailable` answers can be told apart. The driver's text is never logged. The answer to
  the client is unchanged.
- deploy: `helm-upgrade.sh` takes `DUMP_TIMEOUT` (seconds, default 300) for the dump Job, the stub test pins that a failed Job is noticed at once, and the install guide reads the log of the pod that succeeded.
- context: the index line for process.md names the rented runner server (caps, firewall, ssh, only pushes to main).
- deploy/k3s-single: `cert.yaml` and the example `hub-values.yaml` carry the join host (`ingress.joinHost`), and the install walkthrough names its DNS record; production serves `join.maity.team` through the chart instead of hand-made Ingresses.
- ci: the MariaDB hub tests leave the pull request gate and `ci-ok`; `hub-mariadb.yml` runs them at most once an hour on main when hub files changed, opens a `ci-red` issue naming the commit range when red, and can be started by hand for a deploy commit. PostgreSQL and SQLite stay per pull request.
- deploy: on a server prepared by `bootstrap-server.sh` the runner units require and follow the firewall unit, which starts before
  the runner user's manager; the Docker key file must hold exactly one key; the self-test also probes `[::1]:22`.
- ci: the self-hosted runner services are capped: `CPUQuota=150%`, `Nice=10`, low CPU/I-O weight, `MemoryMax=4G`,
  `PYTEST_ARGS=-n 2` per instance, and a drop-in for the runner user's slice (4 of 8 cores, 8 GB, no swap) that also
  limits the rootless Docker. The first run of three uncapped services took the machine down. The README says to
  start with one service.
- deploy: the bootstrap's self-test also probes the machine's own IPv6 address and a listener on `::1`, and prints a note for anything else that listens on loopback or on all addresses and is open to the runner user.
- deploy: on a rented runner server the firewall chain of the runner user lets loopback through (the test suite starts servers of its own on any port) and keeps
  ssh, the metadata service and the private networks closed; the bootstrap's self-test probes an arbitrary loopback port.
- ci: the self-hosted runner is one service per database job type (`maity-runner@sqlite`, `@pg`,
  `@maria`, labels `<prefix>-sqlite|pg|maria`), selected by the repository variable
  `HUB_RUNNER_LABEL` (replaces `HUB_RUNNER`), so a pull request's three jobs run side by side and no
  two Postgres jobs share the host port. Each service runs the suite with `-n 3`.
  `deploy/runner/install-services.sh` installs them; hosted runs and fork pull requests are unchanged.
- Dashboard: opening a card on the board reads only what its panel needs (the roles, the card's notes and history, its updates and restricted text where they apply), and closing it reads nothing; the whole card list, the members, the project, the session and `/me` are no longer read again (tsk-d61rvjm6gteh).
- Dashboard: the global chat reads its lists and the open conversation again only when the notifications stream brings a chat or mention or moves the chat counts, no longer on every answer and every counts read (tsk-d61rvjm6gteh).
- Hub: the handover (docs/api.md §5.2) is read only up to the first packet's `events.after`
  (`events.read(until=)`) instead of looking past it page by page, an instance made before the
  handover's cursors existed falls back to its creation time, and the first packet carries the
  handover whatever cursor the first resume named.
- Hub: a new agent instance (the first session of a credential, also after `replaces`) starts its
  event cursor at the project's current head instead of `0`; its first `maity resume` and
  `maity wait --batch` no longer replay the backlog. History stays available with `after=`, and an
  explicit `cursor` in the resume body is still honoured (docs/api.md §5.2, §8.3, §6.17).
- cli: `maity join` no longer writes into the repository unasked: it prints the pointer block for `AGENTS.md`, and `--pointer` writes it (`--no-pointer` is accepted and is the default).
- cli: `maity checkpoint` warns on a detached HEAD and on a branch other than the card's last checkpoint's; `--no-code` sends no git facts. `maity wait --batch` prints every pending event (at most 50) as one JSON array and moves the cursor past them.
- cli: the resume text treats handles that differ only in case, surrounding space or invisible characters as shared and shows ids for them; a peer without a member id shows no empty brackets. The hub URL from an exchange is stored lowercase and IDNA-encoded; port 0 and a numeric "parent" are refused.
- web: buttons sit at the right edge of their form, panel or card — secondary ones before
  the primary one (Cancel before Save, Later and "let's talk" before the replies, Hide
  before Copy), destructive ones apart; on a phone they stack full width
- cli: the resume packet names members by handle (actor, subject, reports-to, answered by, paused by, message recipient), from the packet's peers and `me`; an id the packet does not name stays an id, and so does a member whose handle is shared, shaped like an id or `all`; the Members line keeps each id (`agent-a [agt-a]`) for `say` and `ask --to`.
- cli: `maity say <your human's member id> "…"` without `--type` is the chat with your human, like `maity say human`; to any other human `--type` stays required.
- hub: the card, event and member lists build their views in batches — a
  page costs a fixed number of SQL statements instead of up to three per row
  (the board with 200 cards: 576 statements before, 11 now), the resume
  packet's peers included; closed releases serve their frozen record and
  read their tags in one query per page; `scripts/measure_board.py`
  measures it.
- hub: the forge probe (`docs/api.md` §11) — `GET …/probe` for pull
  requests, branches and tags on GitHub with the token from
  `MAITY_FORGE_GITHUB_TOKEN`, sent only to `api.github.com` and never
  across a redirect to another host; observations cached for `max_age`;
  `probe_not_configured` and `probe_unavailable` with the last
  observation; a worker thread that fills `report.observed` and
  `mismatch` right after a report and refreshes the open release's pull
  requests and tag on an interval, with `probe_observed` and release
  readiness from what it saw; a pull request the forge does not have is a
  report `mismatch` and blocks a release as `pr_not_found`, a branch
  deleted after the merge is no mismatch; `checks` from check runs (all
  pages) and commit statuses; a change is announced by whichever read sees
  it first.
- hub: a report's `head`, `remote_head` and `pr.head` are the full 40-hex
  commit (`not_a_sha` otherwise), and reported heads are compared whole,
  never as a prefix.
- hub: signed requests mandatory per project (`docs/api.md` §2.2, §6.1) — the
  policy field `signing: optional | required` (a preset change keeps it), a
  bearer agent call in a `required` project is `signature_required` (403)
  after the secret verified and before any side effect, the exchange answers
  `Maity-Signing`, the join page puts the CLI first, and the credential view
  shows `last_used_via`.
- Web: the instance admin has a **Pages** tab with Landing pages and Legal pages as sub-tabs, and
  the whole site's file folded above them, at `/admin/pages`, `/admin/pages/landing`, `/legal` and
  `/site`. `/admin/site` is gone. The section for the ways into the hub is now **Sign-in methods**.
- Web: the texts of `register.js` come from the catalog.
- Web: an unknown `trust:` token in a project message reads like an unknown role, not as the raw token.
- Web: the texts of `attachments.js` and `trust.js` come from the catalog, a sentence per role and trust; file sizes
  take the reader's decimal mark; `qr.js` raises codes, which no page shows.
- web: a project's Chat tab no longer shows the "N unread mentions" line beside the tabs; the maintainer's choice, as its chat list marks a chat with an unread mention (@). The line stays on the project's other tabs, where it also counts mentions in project messages and on cards, which the bell shows too (tsk-sesdq48m9ewk).
- web: the chat lists (a project's Chat tab and /chats) hide the pin buttons until the 📌 toggle beside the list's heading shows them; pressed again or after a reload they are hidden again, and the choice is stored nowhere. A pinned chat keeps its 📌 mark either way (tsk-4nf344w4c52c).
- Web: going from chat to chat in `/chats` changes the conversation pane alone, about three times as fast at 150 ms of latency.
- web: the email field on the sign-up form and on the sign-in page's mail
  form is labelled "Email address" instead of "Your address", in every
  language, so a reader can tell it wants an email address and not a handle.
- web: the fixture shape check covers 9 more requests (notifications, requests, agents,
  credentials, the board's full list, notes, history), and the hub seed fills the lists it
  compares.
- web: smoke pins a `/site/chrome` answer that arrives after the frame was
  left, the frame left once a session read succeeds, every line separator of
  the contract view, the mention line following a counts read, and a
  consent case with data the hub produces; `/site/chrome` joins the shape
  requests; a comment in `tools/check.py` on the unchecked Chinese address
  is corrected (tsk-gsk31zvpfv02, batch 1).
- web: `web/README.md` describes the frame of the sign-in and registration
  pages, the `/site/chrome` fixture, the unread-mention line beside a
  project's tabs, the address filter on All notifications, and the stub for
  a boss of someone else's; Keep the Why records the fixed-word handle
  hints, the seq's `#` drawn by the stylesheet and three parts of the
  frame's design; `docs/api.md` §16.7 says the frame read keeps the last
  `?lang=` a page saw across its routes (tsk-gsk31zvpfv02, batch 2).
- web: a new jour fixe series proposes the account's time zone, the browser's while none is set (tsk-tsb8528rank1).
- web: README and Keep the Why follow the code: the maintenance banner's time zone, the avatars (generated first, the picture near the screen at the size that covers it), /chats' counts reads, and the landing import's own section types (tsk-tsb8528rank1).
- web tools: `make check`'s French address check also finds the informal possessives `ton` and `ta`, but only right before a word the French catalog itself writes after `votre` and never after an article, whatever whitespace stands between, so `ton` as "tone" stays clean (tsk-tsb8528rank1).
- web tools: the smoke DOM shim moves a removed field's caret to its end, a stress condition of the shim rather than a browser's behaviour, so the card panel's caret restore is guarded in smoke too; smoke also pins the product line's `translate="no"` marks (tsk-tsb8528rank1).
- web e2e: the handle hints are measured with the owner renamed to 31 characters for the step and restored whatever fails in it, the global Chats list's heading and lead control are pinned at 390 and 360 px, and a mention of the owner (by the alias the handle step leaves, since `@owner` is a group word) brings the unread mention line and the filtered notifications page under axe (tsk-tsb8528rank1).

### Removed

- docs: `legacy_slug`, the old badge, swarm and webhook addresses by
  slug, and the answers `client_outdated` and `project_path_outdated`
  for one-segment project routes (§6.25); an old address is
  `not_found`.
- docs/api.md §6.1, §6.22, §16.11: the public swarm page (`GET /swarm/{owner}/{slug}`), the
  `policy.swarm_public` flag and the dashboard's Swarm tab. The swarm's numbers are a section of the
  project's Overview; a project with a public page (§16.9) shows them reduced to agents, without
  presence.
- The CLI's handling of `client_outdated` (426): the hub stopped sending it with the path routing.
- hub: the boolean `keep_the_why` alias of `memory.provider`: `POST` and `PATCH
  /projects` no longer take it (an unknown field, `invalid`), and project views and
  the resume packet's `project` no longer carry it; `conflicts_with_memory` is gone
  (§6.1, §6.21, §8.2)
- hub: `policy.jour_fixe`, `policy.jour_fixe_moderators`, `moderator: admin_agent`, the scope
  `jour_fixe:start`, `PUT …/jour-fixe/moderators` and `POST …/jour-fixe/rounds` (docs/api.md §20).
- hub: the public swarm page `GET /api/v1/swarm/{owner}/{slug}` answers `not_found` like any path
  the hub does not know, and `policy.swarm_public` is gone: no field in the policy, refused at the
  `PATCH`, dropped by migration 0102. Moderation's `hide` turns the badge off only, and an agent
  is no longer reportable by a stranger through a public swarm page. The members' statistics stay
  at `GET /projects/{owner}/{slug}/swarm` (§6.22, contract #697)
- The setting `browser.content` and the `content` field of notification items (`docs/api.md` §18). The hub
  never filled the field, so the dashboard's "Text in the notification" switches did nothing. A `PATCH` that
  names it is now `invalid`. The mail's `content` switches stay.
- web: the shapes baseline entry `GET /me: .maintenance`, which the fixture now sends.
- `web/brand/og-image.png`, which nothing uses any more.
- `web/tools/maity-site.json`: an instance's site file is no longer in this repository. An operator
  writes their own (`docs/api.md` §16.7), and the tests use the neutral
  `web/tools/site-fixture.json`.
- web: the runner pairing form no longer retries without `attach` for a hub before §15.4; the
  attachments no longer read a 404 or 405 as a hub without them (only `409
  attachments_not_configured` is "off"); the fixture hub and fixtures no longer carry
  `legacy_slug`, which the hub dropped.
- web e2e: the fallbacks for older hubs: without attachments or with them off, without
  notifications, the session list, the chat list across projects, group chats, the ticker, the
  overview, runners, the card move or the avatar upload; the e2e hub serves all of them.
- web: the dashboard no longer asks the hub's machine form what it serves (`M.api.hubHas`,
  `M.api.hubBody`) and no longer treats a 404 or 405 as "not on this hub" (`M.api.missingRoute`,
  `M.api.absent`, `M.dom.notOnHub`); a missing route is an error like any other. The fallback for a
  hub without notifications (`M.notify.state.available`, the bell as a plain link, the inbox's
  "Nothing waits for you.") is gone, as are the per-project chat reads for a hub without
  `GET /me/conversations`, the admin sections left out for a hub without them, and the "this hub
  does not order cards / take pictures yet" readings of a 404. Fields the hub always sends are no
  longer tested for presence (the Why tab, the signing, badge, Keep the Why, swarm, member-agents,
  onboarding and image forms, a card's subtask editor, /me's project logos without the
  `GET /projects` fallback, the coordinator before trust × role).
- web e2e: the invitations, images, Why, signing, users and briefing steps no longer skip a hub
  without the feature.
- web: the account's **Agents in other projects** and `/account/picture/<agent id>`; an agent's
  picture, name and deletion are on Your agents.
- web: the route `#/admin/users`; the users are the Users section of `#/admin`, and the old address
  is no view.
- web: New project no longer sends the `keep_the_why` alias to a hub before docs/api.md §6.21; such
  a hub is offered no project memory. The fixture hub still takes the alias until the hub drops it.
- web: the fixture hub's `removed_kind` for notification kinds removed earlier; such a kind is
  `unknown` there, as on the hub after its compatibility layer went.
- web: the fixture hub's `POST /me/notifications/read` answers `unknown` for a kind outside the four,
  as the hub does.
- web: the fixture hub's boolean `keep_the_why` alias of `memory.provider`, as the hub's: `POST` and
  `PATCH /projects` refuse it (`extra_forbidden`), the project view and the fixtures no longer carry
  it, and the machine form no longer names it.
- web: the old Markdown landing editor, the dashboard's own drawing of the landing page at the root
  (the hub renders it), and the Markdown renderer's mode for path links that served it.
- web: the account page's case for a hub without `meat_proxy_note`, and the
  smoke cases and wording for older hubs. A chat without a message and an
  optional Keep the Why commitment stay, as the real cases they are.
- web: every `#/` route; the old `/p/<slug>` (by `legacy_slug`), `/s/<slug>` and
  `/<owner>/<slug>/agents` and `/join` addresses, without redirects; anchors and bare queries as
  links, which would lead into `/assets/` under the shell's base.
- web: the **Organisation** tab and `/<owner>/<slug>/org`, the owner's **Details** on Members,
  `…/members/join` and `…/members/<id>/rulebook` and `/picture` (alpha: no redirect).
- Dashboard, **Message the project**: "A review's result" as a type; a review result carries cites
  against the diff and comes from `maity say --type review_result --review-file`.
- Dashboard: the **My settings** tab and its path `/<owner>/<slug>/my-settings`, without a redirect.
- Dashboard: the Swarm tab and the `/<owner>/<slug>/swarm` view, the public swarm page with its
  `?as=public`, and the `swarm_public` switch in Project settings (contract #697).
- hub: the compatibility layer for the notification kinds removed on 2026-10-26 (`card`, `agent`,
  `keep_the_why`, `ticker`, `jour_fixe`, `system`, `registration`). Migration 0084 deletes what
  is stored for them in the notification settings; the error `removed_kind` is gone, and such a
  kind is `unknown` in the bell's `kind` filter, in its mark-read body and in the settings.
- hub: the paths from before the namespace and the hash routes: `/j/<token>`, the `426
  client_outdated` and `410 project_path_outdated` answers, the redirects of the old badge and
  public swarm addresses, the forge webhook's one-segment address, and `legacy_slug` (the field
  of the project view and, with migration 0086, the column). No redirect leads from an old link.
- The environment variable `MAITY_ATTACHMENT_QUOTA`, without alias or fallback; set
  `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT` or the admin field instead.
- Hub: `MAITY_ATTACHMENT_QUOTA` is no longer read; set `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`
  or the admin field instead.
- Helm chart: `attachments.quotaBytes`; a values file that still sets it is refused by the schema.
- cli: `maity chat` and `maity chats` no longer read a direct conversation listed without `id` and
  `kind`, and `maity ticker post --help` no longer describes a hub without the ticker
  (alpha, no compatibility layers).
- cli: the compatibility layers for older hubs and states before launch: the `openapi.json` lookup on a 404
  (also for `maity chat cnv-…`, `maity ticker post` and the runner's pickup), the resume resent without
  `environment` or `supervisor`, `GET /me` for a state holding only the slug, the single-role fallback without
  `trust`, and the refusal of a card without a `links` list; docs/api.md §13 and §17.6 drop the matching text.
  The `not_found` follow of a moved project through `GET /me` stays
- cli: the runner no longer takes over a clone recorded before the project namespace; a clone
  lives at `<workspaces>/<project_id>/<clone>` only, and `runner gc` reads the record's `project`
  (alpha, no compatibility layers).
- `maity takeover` no longer checks for or describes an objection hold, which the hub does not have yet; opening a takeover no longer reads the card first.
- hub: a jour fixe round has no `mode` any more, in the API, the contract and the database; every
  round runs in its group chat (§20.5). The dashboard no longer has a text for a project without
  `setup` (alpha, no compatibility layers).
- docs: §15.5 no longer promises that a workspace recorded under the old slug is taken over; the
  runner stopped doing that with the removal of `workspace.find`.
- deploy: the runner README no longer describes the move from the first single runner (step 0) or the unused `HUB_RUNNER` variable.

### Fixed

- ci: the `ci-ok` gate runs in the workspace root: it has no checkout, so the workflow-wide
  `hub/` working directory does not exist there and the gate failed with every suite green
- Contract §16.11: the member view's tabs are named in plain words, so the paths test no longer reads them as project views (main was red after #875).
- web: Members says "Saved", "paused", "removed" or "waiting for consent"
  only after the list has been read again and redrawn, so the rows already
  show the change and are not replaced under the next click.
- docs: the join page template and the agent skill say what to do with an empty briefing
  (`null` is valid: assigned cards, then open cards, then wait for a message); the join page
  names Python 3.11 as the CLI's minimum, as §3.2 and the CLI's `requires-python` do.
- hub: `DELETE /agents/{id}/avatar` checks that the caller still owns the profile before it
  replays a stored answer: a repeat of an old change with the same `Idempotency-Key` no
  longer shows the current picture state to someone who lost the agent (§6.10)
- hub: `GET /me/notifications` reads every source (events, chat messages, account records)
  only as far as its page reaches and counts with its own few items, so a page no longer
  grows with the number of unread inbox items; the events of personal requests are left out
  in SQL and the open personal requests are counted in SQL (§18.2 unchanged)
- hub: a page of the board's order (`GET …/tasks`, `docs/api.md` §6.4) whose last card left
  its column goes on from the first card it did not show when that card has not moved, and
  otherwise from the top of the column without the cards it showed, so no card that did
  not move is dropped from the next page
- hub: `POST /requests/{id}/answer` refuses `on_behalf_of` with `proxy_only` instead of dropping it (§2.3).
- hub: a `GET …/tasks` cursor holds only for the filters and the order of the page that
  gave it (`docs/api.md` §1.4); another filter set answers `invalid` (`cursor`)
- web: a change of another owner's agent that waits for its owner's consent (docs/api.md §6.2) names
  the human asked (that owner, a boss's owner, or by name where a member) in the members view's
  status line, not the raw `human:<id>`, and where part of the
  change applied at once (its `reports_to`) the line says what was saved and what still waits.
- Web, Sign in another device: approving the new device asks for the second factor in the dialog when the
  hub wants a fresh one (§2.8.4), then sends the approval again. Before, an enrolled human whose second
  factor was older than 10 minutes only saw "Not sent" with the hub's refusal. Cancel leaves the approval
  open.
- The browser test no longer passes the caller's `MAITY_*` settings to any process it starts: one
  `maity wait` inherited `MAITY_STATE_DIR` and took over a real agent's wait.
- hub: an event's `at` never runs backwards within a project: under the project's lock it
  is the later of the clock and the project's last event, so a clock step back or a replica
  whose clock is behind keeps `at` in `seq` order (`docs/api.md` §18.2)
- web: in fixture mode `DELETE /runners/{id}` answers `on_runner_revoke` as the hub does, a
  second DELETE with the same list again, and the fixture project's policy carries
  `on_runner_revoke: stop`.
- web: the fixture shape check now compares a runner's `capabilities` and `projects` and the
  DELETE's `still_running` and `on_runner_revoke` with their items: the hub test seeds a runner
  that has said hello, is attached and runs an agent.
- web: a request the fixture hub refuses during the shape check names its error code instead
  of `M.errorWords is not a function`.
- helm: the migrate Job no longer mounts the attachment claim or gets `MAITY_ATTACHMENT_DIR`, so a `ReadWriteOnce` claim no longer blocks an upgrade on a second node.
- hub: the sdist now carries the dashboard and the join page (under `bundled/`, through
  `hub/hatch_build.py`), so a wheel built from it, as pip does when it installs from source,
  no longer fails with "Forced include not found".
- hub: no agent, whatever its role, assigns away, releases, cancels or sets back to `open` a
  card a human holds, lease or no lease (`docs/api.md` §2.3): `POST …/assign` to another
  member, `POST …/release` by someone other than the holder, and `PATCH` with
  `assigned_to` away from the human holder or `status` `cancelled` or `open` answer `403`
  with `details.reason: humans_only`, before the scope and the lease are looked at; `done`
  stays done authority's, humans keep these rights, and an admin agent still moves an
  agent's expired claim
- hub: a human's rename withdraws the open transfers of the projects in their namespace, as every change of a project's full name must; the `go` could only have been stale (§6.25).
- hub tests: on a server database a test that needs no schema empties the tables before it downgrades, so a project an organisation owns, left by the test before it, no longer fails it by the order of the workers.
- hub: `GET …/requests` and `GET /requests` build full views only for the page they
  answer, not for every filtered request, so a listing costs its page however many
  requests (history included) a human has
- hub: `GET /me/notifications` reads the personal requests behind its inbox items and
  their askers' names together, not three queries per item
- deploy: the chart's default ingress-nginx annotations set `proxy-body-size`
  to `11m`, so attachment uploads up to the hub's 10 MiB pass the ingress;
  `deploy/helm/check.sh` checks that the value (bytes, or k, m or g; 0 for no
  limit) stays above the hub's cap.
- hub: `GET …/events` answered 500 to every reader once a round-level redaction (an answer, the
  summary, a finding or a proposal, §20.8) was in the batch: its `subject_id` names the round, not a
  seq. A round's thread read along by an owner with no agent of theirs in it answered 500 too, and
  the conversation list showed such threads to nobody: it checked the role, not the trust `owner`
  (docs/api.md §9.2, §20.5).
- hub: `jour_fixe_reported` woke every agent of the project and `jour_fixe_series_changed` every
  member it named; the report now wakes only the agents on the series' report list, and a skip and
  a series change wake nobody (docs/api.md §20.9).
- hub tests: `test_simultaneous_reads_are_single_flight_and_release_their_threads`
  counts only requests to a path of its own, starts its 30 readers behind a barrier
  and gives the upstream read a wide margin over the waiters, so a slow runner or a
  read left by another test no longer fails it.
- hub tests: `test_waiters_on_a_slow_family_do_not_starve_the_request_threadpool`
  checks an order instead of a 1.0 s wall-clock bound: the unrelated request is
  answered while the family read still waits on the upstream.
- hub: a landing page near its 64 KiB Markdown limit is no longer refused with 413
  (`docs/api.md` §16.7). `PATCH /admin/settings/landing` alone takes a request body of up to
  256 KiB, since JSON escaping grows the Markdown on the wire; the Markdown limit stays 64 KiB
  decoded, and every other endpoint keeps 64 KiB.
- hub: the landing page's `markdown`, `title` and `cta` refuse C0 control characters other than
  tab, newline and carriage return, `invalid` with `control_character` (§16.7).
- Public pages count a pull request from a forge link only when the event names the instance's token and
  the repository's last check found it public, as the contract says (§11.4). A public project read
  only through an App or an owner's token shows no merged pull requests there.
- Hub: listing forge links no longer turns a link back to `active` after it was removed.
- hub: the downgrade of `20261031190604_jour_fixe_series` no longer fails on MariaDB, where it dropped an index a foreign key needs and left the database half-migrated.
- hub: the route words `me` and `repository` are in the reserved floor that `migrate`
  checks existing slugs against (§6.25, §16.11); a test keeps every route word of the
  hub in it
- hub: removing a member also clears the stored `reports_to` of an active placement
  that creates a profile, and the exchange applies a join's `reports_to` only while it
  names an active member, checked after the project lock (`docs/api.md` §6.2)
- hub: `GET /people/{handle}` takes the hold rule for links from `person_links.admitted(held=…)`,
  the member views' own (review of #766)
- tests: a server database is emptied before the session's last downgrade, which an
  organisation's project left by the last test refused
- hub: the notifications long-poll no longer derives every item again each half second
  while it holds. It compares a few aggregates first (each project's highest event, the
  account records, the read and chat marks) and runs the full answer only when one of them
  moved. At most four full notification answers or marks run at once per hub, so they
  cannot take the connection pool from every other call. Two `POST /me/notifications/read`
  of the same items at once no longer fail on the key: the marks are written in one
  statement that skips existing rows, at READ COMMITTED; chat marks likewise.
- hub: deriving a human's notification items no longer reads the database once per event.
  The cards, requests, watches, memberships, profiles and names a project's events refer to
  are read once per answer, so an answer over thirty days of a busy project takes a fixed
  handful of queries instead of thousands. The items are unchanged.
- hub: a rate count given back for work that did not happen returns to the window it was counted
  in (`Limiter.place`/`release` with a count; `give_back` is gone), `Limiter.blocked` answers as
  `hit` would when the previous window is weighted, and a count over a limit is refused as a
  programming error instead of answered with a `Retry-After` that never comes true.
- hub: a GitHub project's forge logo is the owner's avatar only when the owner is an
  organization (`docs/api.md` §11.2); a repository a user owns has no forge logo, so the
  dashboard shows the monogram instead of that person's photo, and a stored one goes on the
  next refresh
- hub: an outbound answer whose stream ends before its declared `Content-Length` is
  refused (`unavailable`, or `timeout` past the deadline) instead of returned as if it
  were the whole body; under load the deadline watchdog closing the socket could end a
  read that way, so a forge image or probe answer could be stored cut short
- hub: a decision request from an owner's jour fixe round is read and answered only by its asker and the circle owner; `requests:answer` opens it to nobody else, in the list, the single request, the resume packet and a substitute's cover; it is forwarded to one human at most, and its answer writes no ticker item (§20.6, §20.7).
- hub: a member removed from a project gives back the open decision requests it holds, to the admins as an account's deletion does, or to the addressee if an owner's round filed them; a circle owner leaving withdraws what nobody else could answer (§7, §20.7).
- hub: an agent that did not ask for an open cross-owner pair is refused with `pending_consent` also where its `PATCH` of `reports_to` would wait for a human's go; such a change withdraws the pair at its `go` (§6.2).
- hub: an organisation's picture is readable by its members and the members of its projects
  (§6.10), and by nobody else; the image route answered `not_found` to all of them and served
  it to an instance admin
- A report first observed with its pull request open is read again by the probe's sweep, so a merge
  reaches the card: `task_merged` and `merged_closes` fire, and `maity report` no longer refuses a
  follow-up pull request because the merged one looks open (docs/api.md §6.6).
- Hub: with several replicas, every process shows the same `repository.probe_via`, not only the one
  whose probe ran last.
- hub: a proxy answers a request only by recording its owner's answer: `on_behalf_of` names a member with trust `owner`, without it the answer is `forbidden` (`proxy_relays_only`), and from anyone else it is `invalid` (§2.3, §7). A proxy's call held by an owner who leaves goes back to the owner, not to the admins.
- web: a public project's `/overview` and `/overview/project` show its public overview, read-only,
  to a visitor and to a signed-in non-member, so the badge's link no longer ends on the login or on
  `not_member`; `/overview/swarm` stays the login for a visitor and takes a signed-in non-member
  to `/overview` (docs/api.md §16.9, §16.11).
- docs/api.md §1.1, §16.13: the pages with the product line allow its one `<style>` block by a
  `style-src 'sha256-…'` hash.
- hub: `prs_merged` also counts the ticker's merges, so that it no longer reads 0 for a project working with reports; a public page counts only merges read as public and shows no line when it has none.
- hub: of two concurrent redactions of one event, only the first writes its tombstone and
  emits `event_redacted`; the other answers with the tombstone that stands, as a repeat does
  (`docs/api.md` §8.5)
- web: the restricted-access set's notice in the bell opens the project's settings and is marked
  read like any notice, instead of opening one's own notification settings and staying unread.
- The `Keep the Why` block of `maity resume` says that its personal settings apply only while the
  project has no personal file yet, and ignores an `install` that is not a list (docs/api.md §6.23).
- hub: the resume packet's `requests.answered_since_cursor` keeps the newest 100 answers, in the
  order they were answered, instead of the 100 requests asked first; a rejoin after a long absence
  showed old answers and dropped the latest (docs/api.md §5.2 now states the cap of 100 per list).
- hub: the test of a multi-ping `Retry-After` freezes the limiter's clock; across a
  second boundary it saw 599 instead of 600 and failed now and then on PostgreSQL
- hub tests: `test_it_is_computed_once_an_hour` no longer depends on the time of day. It runs
  at 23:30 UTC, so the hour later always crosses into the next day, and it counts the card on
  the day it was made.
- hub: the wake-up listener's connection sets TCP keepalives, so a connection dropped silently
  is noticed after about a minute and opened again instead of leaving the replica deaf and the
  server's notice queue held (review of #869).
- hub: a request with a body to an API path no route serves answers `404 not_found` before
  the 64 KiB cap and without reading the body, instead of `413 payload_too_large`; a path a
  route serves with another method, or that differs by a trailing slash, stays routed
  (the cap, then `405` or the `307` redirect)
- hub: two simultaneous waits of one key on PostgreSQL no longer both end as superseded: the newer start decides, also inside a process.
- hub tests: the wake-up tests count only their own projects' wake-ups, so a notice another
  writer sends to the same database meanwhile no longer fails them (hub-postgresql flake seen
  on #619).
- web: the refusal `resolve_the_report` (409, an answer to or withdrawal of the instance admin's request about a new abuse report, docs/api.md §1.3, §16.8) has its words in `js/errors.js` and the catalog, so `make check` in `web/` passes on main again (tsk-mztp83ezqjvc).
- Help: `probe_observed` is described with its real condition, not "while the card is open".
- web: "A private series." on the all-projects Jour fixe page is German
  in the German interface too.
- web: the all-projects Jour fixe page says "A private series." for an
  owner's series an admin may not read, instead of showing its raw ID.
- hub tests: `test_online_uses_canonical_presence` waits with the new `listening.written()` until the close of a wait has reached the database, so on PostgreSQL the badge read right after it no longer finds the wait's row (304 instead of 200).
- cli: `maity say <to> --type T "…"` takes the message after the options instead of failing
  with "unrecognized arguments"
- CLI: another instance of an agent joined outside a Git clone gets its own state directory,
  `<handle>#<instance>` beside the first, and no longer hits the first instance's credential. A
  clone that already holds a credential refuses before anything is sent: it says to set
  `MAITY_STATE_DIR` for the new instance and no longer suggests `maity resume`.
- CLI: `maity resume` names this instance (`You are <handle>#<instance>`) and lists the other
  active instances, and `maity messages` shows an instance address as `<handle>#<instance>`.
- CLI runner: in the `agent_user` and `ssh` layouts, the exit code of a provider limit is read from the agents' side by the runner's own module (`maity runner limitread`), not by `dd`, whose macOS version has no `iflag`. On macOS hosts the limit now keeps its exit code. A host whose `maity` is older records the limit without an exit code. The file is still read only as a regular file, never through a link or from a FIFO.
- CLI tests: the `agent_user` prerequisites test is skipped with its reason when `maity` is not installed for the interpreter (`-I` ignores `PYTHONPATH`), and the sandbox test expects Claude Code's sandbox only on Linux.
- CLI runner: `gc` reads a clone's configuration the way git does, and accepts a branch or
  remote whose name holds a dot, and a clone made by git for Windows.
- CLI runner: files for the agents' side in the `agent_user` and `ssh` layouts are written without GNU `install -D`, with tools BSD, macOS and GNU all have, so a host whose `install` refuses `-D`, or gives it another meaning, can start agents. The file's own directory, if missing, is made 0700; a link at the path is replaced, a directory there is refused.
- CONTRIBUTING: the opt-in pre-push hook is not for a clone a maity runner manages, whose clone check refuses `core.hooksPath`.
- CLI: a project with a new full name (an owner's or the project's rename, a transfer) no longer
  stops every command with `not_found`. The CLI asks `GET /me` once, keeps the new name, says
  `project is now <owner>/<slug>` and repeats the call there. `maity wait` keeps waiting at the
  new path, within its `--timeout`.
- hub: migration 0060 creates `project_alias` with the `utf8mb4_bin` collation on MariaDB too (the `mariadb_` table options beside the `mysql_` ones); before, MariaDB refused its foreign keys (errno 150)
- cli: `maity wait` prints and flushes the events before it saves the cursor, so a wait stopped
  in between has not acknowledged events it did not hand over.
- cli: on Windows `maity` reads and writes UTF-8 through a pipe, names a state directory in PowerShell form, keeps `./maity-files/` private and its home's environment secret under `%LOCALAPPDATA%`, and its `git` calls no longer take hooks from a `/dev/null` path a user could create.
- cli: on Windows a `./maity-files/` others can reach is refused, and stdin in another encoding is refused instead of reaching the hub altered. `--join-file` takes a byte order mark and says when a file is not UTF-8.
- hub tests: the notification mail tests start at 12:10 UTC whatever the time of day, so a test that moves the clock by an hour no longer crosses the default digest time (08:00) and fails when CI runs shortly before it.
- cli: `maity link list` refuses a card without a `links` list instead of
  printing "no links".
- Dashboard: an invitation shows the project's logo; the page's check still expected the address before
  projects had an owner in it, and the generated mark stood in for every logo.
- Dashboard: a pending account deletion stays on Your data after a new load, with its withdrawal. The page
  read the field from the member, where the hub does not send it, and offered the form again.
- cli tests: copying a test repository's `.git` no longer races git's background maintenance
  (`test_confinement` turns off `maintenance.auto` and `gc.auto` before its commit, and both
  copies skip `*.lock`).
- hub: a chat or project message read again carries `deleted_at` on a
  file deleted since, so the dashboard no longer offers it again after a
  reload.
- hub: the overview's latest reports name the reporter's `instance`, and
  a group chat in the conversation list carries its `created_at`.
- web: `tools/hub-shapes.json` re-recorded after #1187, whose member lists carry `manages`; `hub/tests/test_web_shapes.py` failed on main since #1187 and #1192 crossed. The fixture's missing `manages` is in the baseline until #1189 brings it.
- Hub tests: `test_public_why` no longer fails at random. Its apps start no public-pages worker, whose start-up render, late on a loaded runner, wrote the Why page back with the settings the app was started with after a test had changed them.
- docs/install: the k3s step that reads the SMTP password is marked as `bash`; under `dash` its `read -s` fails and leaves an empty password.
- cli: `maity join` checks the state directory (created, private, writable, no other
  identity) before it spends the single-use code. A credential that the directory still
  refuses after the exchange goes to a new private directory, and the CLI names it; it is
  never dropped.
- hub tests: the hub-postgresql job could hang until the job was cancelled. One test in `test_swarm.py` left a database connection open in a transaction, and the next test's `TRUNCATE` waited for its locks without end. The connection is closed now, and the `TRUNCATE` between tests gives up after 60 s with a lock error, so the next leak of this kind fails instead of hanging. Found and reproduced by dzse at #1256; a CI run of the full suite on this head is still needed as proof.
- hub: the listening registry on PostgreSQL no longer leaves itself started without a writer. A first heartbeat that fails undoes the start. Each writer ends on its own stop signal, so a stop's marker left in the queue (no writer read it, or the writer was still in a write) no longer ends the next app's writer. Before, the next `listening.reset()` (tests) then waited for ever. That wait, and `listening.written()` from #1251, now ends with an error after 30 s. In production this only concerns a pod's shutdown.
- hub tests: the maintenance window's 5 s cache no longer expires on its own during a test, so a statement-counting test on a slow runner stops seeing the window read again (+2 on PostgreSQL, +3 on SQLite). The cache's clock is `maintenance.monotonic`, held still by the test fixture.
- web: during a maintenance window every signed-in page has **Sign out**: also the instance admin's own window at `/admin/maintenance` and a session that must still set up its second factor, which had no way out. On the sign-in page, a change of language now reaches the maintenance banner as well.
- cli: `maity memory add -` reads the entry from stdin, as `say` does; it
  stored a literal `-` before.
- link previews: `maity.dev` and `maity.team` each show their own image. The landing page now has social tags, and the shell names its image by a whole address, as crawlers need.
- Hub: a card event of a public project no longer renders every card page of the project while it holds the project row. Since the ticker, each claim, report or edit did, and writes to a large public project waited for the lock until the statement timeout (503). The project's page is rendered at once only when the change may take a ticker item off, and then without its dependents.
- hub: the account completion page `/mail/register/{token}` links the legal pages the instance
  serves — the imprint, the privacy notice and the terms of use, in that order — under the form, as the dashboard's
  registration form does (§2.7.1, §16.7.1).
- cli: `maity report` after a merge that deleted the branch — when the upstream branch is
  gone and `gh` finds its pull request merged with the local head, that head is reported as
  the remote head instead of refusing; any other deleted branch is still refused, with a
  message naming push, the merged case and `--no-code`. docs/agents.md: report while the
  branch exists and on every pull request update.
- Dashboard: removing a runner with agents still running listed empty lines, since the page expected a
  whole placement where the hub answers its id. The list now shows the placements' ids. The fixtures
  had the form the page expected, which hid it.
- landing page: a hub without a dashboard names no social image, which it could not serve.
- legal pages, landing page: the footer's links, a long title and a longer call to action wrap on a phone instead of widening the page, and the call-to-action band keeps its side margin.
- web: the top bar's "+" and the join panel's close button draw their sign as an icon instead of a text glyph, so it sits in the middle of the button in every browser; in Edge on Windows the "+" sat off-centre.
- web: a header that is the bar alone (an invitation, sign-in, registration, the landing page) has
  as much room below the logo and the buttons as above, instead of touching its lower edge.
- web: the open chat ends at the window's bottom edge again, on a project's Chat tab and on Chats, at desktop and phone widths. Since the product line came below every page (#1290), the page scrolled past the composer: the chat's height was measured from the header's bottom and left out what stands below it, and on Chats the measure ran before the view was in the page and gave up. The chat list column ends with it, each pane scrolling on its own; on a screen too small for the composer and a few lines of history the page scrolls rather than the product line covering the composer. "Sending…" and a failed send now stand in the composer's row after the meat-proxy switch, in a direct and in a group chat, so the composer no longer jumps up while a message is sent.
- web: the landing editor's JSON import refuses a footer of the wrong kind and says so, as the whole site's import does, instead of keeping the editor's footer in its place.
- web: the landing editor's import says why it refuses `variants` or `campaigns` of the wrong kind.
- web: a pending account's header logo leads to the start page, not to everything waiting.
- web: a project whose pill counts unread mentions now shows a link beside its tabs ("1 unread mention") to `/notifications` filtered to that project's mentions. Before, the pill showed a number that no tab and nothing in the project led to. `/notifications` reads `kind` and `project` from its address, names the filter in its heading, links back to all notifications, and its Mark all read marks only that kind and project.
- web: references joined by a slash (`#909/#911`, `tsk-…/tsk-…`) each become a link; inside a path
  or URL they stay plain.
- web: a dormant instance is no longer offered as a team's lead, which the hub refuses (§6.17).
- web: a card with no update in a page that has more behind it says "among the project's latest messages" instead of claiming none.
- web: the landing editor's import refuses `variants` or `campaigns` of the wrong kind, as the whole site's import does.
- web: in the instance statistics the Reviews row spans the same width as the others: days before the hub kept history are a dashed line at the foot instead of a gap.
- web: a chat longer than 50 messages is read to its end, so the newest show and the "New
  messages" line stands where they begin; several messages arriving at once no longer pull a
  reader who scrolled up down to the end
- web: a link in one's own chat bubble takes the text's colour, underlined: the accent reached only
  4.33:1 on the bubble's background (found by the e2e's accessibility check once images were sent).
- Web e2e, `join_expiry_step`: deterministic. The step moved only the browser's clock, and the next
  answer's `Maity-Server-Time` pulled the page back to the hub's real time, so the join read as open
  again now and then. The second tab now sees the hub's clock moved by the same 16 minutes.
- Dashboard, fixture hub: a review result's `review` is checked as the hub's `reviews.py` does
  (`required` for a missing field, unknown keys refused, every line break in a quote).
- web: the board says a move, a placement or an assignment once it shows the result, not before
  the board is read again
- web: **Export my data** and the site download failed in every browser with
  "h(): href is neither a route nor an https URL". They save their file again.
- web: in a **group chat**, someone just added is reachable by mention at once, and a title being
  typed survives a change of the chat by someone else
- hub: a direct or group chat message names the agent instance that sent it (`from_instance`,
  `null` for a human; docs/api.md §9, §6.17), and a request's `asked_by` names the instance that
  asked (`asked_by.instance`, from the asking session's credential; `null` for a human and for a
  request the hub files; §7)
- hub: a forge webhook request refused for a full slug bucket no longer uses up a place of its
  source address, and a verified delivery gives back its own two places, not the newest ones (a
  body read that outlasted the window freed someone else's)
- web: a new page now opens at its top instead of at the scroll position of the page before; opening a card on the board and going back keeps the board's place
- web: in German, a refusal that needs the second factor or the password is said as that, not as missing rights. The dashboard has words for `second_factor_required`, `second_factor_enrolment_required`, `step_up_required` and `reauthentication_required` (`docs/api.md` §1.3). A `forbidden` whose reason has no words yet keeps the reason in brackets instead of the bare "Dafür fehlen dir die Rechte." English readers see the hub's own message, as before.
- web: a test that Join an agent on Your agents (`/agents`) asks for the second factor, as the project's Agents page does.
- `web/README.md` names all four parts of the product line and its four links; it left out "Found a vulnerability?".
- web: the page's language chosen on `/register` before sign-in now stays the choice when the page
  was reached with `?lang=` (as the frame's links do) instead of jumping back to that language; a
  choice on `/login` and `/register` also writes the new tag into the address's `?lang=`, so a reload
  keeps it
- web: Start an agent on a runner offers only runners that offer the project's repository,
  matched as the hub matches it, and says why when none does; a project without a repository
  shows no form (tsk-wn6qp27090qy).
- web: every call the hub guards with the second factor now asks for the code in place and
  repeats the call: creating and re-pairing a runner's pairing line, the instance's mail
  settings, a password change, changing or removing the mail address, approving a held address
  change, and answering a request whose go moves a project. Before, these showed only "This needs
  your second factor first." `make check` now fails on a dashboard call to such a route outside
  the question where it can read the call's path and the call's form is one it follows, and a hub
  test keeps that list equal to the hub's routes (tsk-6dk86ej9s0fq).
- web: the step-up check of `make check` ties a wrapper, and a local helper that hands the call
  on, to the declaration of its name nearest the call in the blocks around it (the last
  function declaration of that block, else the last `const` or `let` before the call, else the
  first): a second, unwrapped binding or helper of the same name elsewhere, or a `call:` property
  also called outside the question by a name the check reads, is a finding. Other binding forms
  are not resolved. A path part it cannot read may stand for several
  segments, and a body key behind a variable is read where the name is declared by `const name =`
  or `let name =` in the blocks around the call. It reads text, not the program, and checks only
  the forms web/context/views.md lists; any other is not checked (tsk-4zrnkb3gh6mq).
- web: **Members → Manage** — a drafted boss who has left the project since is dropped and said
  at the field instead of being sent as nobody (which cleared the member's boss); after a change
  that waits for consent the form shows the hub's state, so a second Save files no second
  request; **Done** drops a row's unsaved edits, and a half-typed pause reason survives a redraw
- web: the agent's card shows the briefing version the hub answered after a save
- web: fixture mode's 202 follows docs/api.md §2.3 ᵃ (an admin agent; `?as=<member id>`)
- web: editing a card note: an Escape the mention picker takes no longer
  closes the edit; a missing reason is said at its field; each Edit and Remove
  button names the note's author and date for screen readers; a draft in Add a
  note is kept while the list is drawn again. The public card page shows a
  note's edit mark (who, when, why) as the hub's own page does.
- web: an edit of a card note removed meanwhile now says the text was not
  kept and moves the focus to the note's tombstone.
- web: the instance admin's test mail takes an empty recipient and then goes
  to the admin's own verified address (§16.3, the hub's side in #1266); the
  fixture hub answers as #1266 does.
- web: the join form takes a hand-over message written as the page shows it
  (`#6001`); the campaign table's counts are formatted for the reader's
  locale, as the tiles are; a group chat's reader who owns no agent in it is
  named alone instead of "owner of" nothing, and an agent id the reader's
  member list lacks gets a neutral line. Small cleanups from earlier reviews
  (P3 roll-up `tsk-dprnjakk3ykh`).
- web: **Project → Runners** says in the status line what Allow or Detach did, where the focus
  goes after it, and a rebuilt Allow form gives the focus back to its control
- web: sessions — after **This was me**, a list that cannot be read again says the result is
  unknown instead of "Confirmed"; the mail sign-in banner is rebuilt on every 15-second round
  while an alert is unread, so an approved session ending elsewhere takes it down at once; the
  section is drawn again when this session crosses an hour or a day of age
- web: the smoke test runs in CI's locale and time zone (`en_US.UTF-8`,
  `UTC`) on every machine, starting itself again in that environment when
  needed; on a machine with a German or French locale the swarm step and the
  campaign table no longer fail while CI is green.
- web: Ticker — after a first page that failed, the next signal reads that page again instead of
  the whole history, and the page read again clears the failure it said; a live read with
  nothing new clears a failure said before; a signal before the first page is in waits for it
- web: a tab that left the enrolment page, by signing out or because the hub let go of the
  requirement, drew nothing at the next `second_factor_enrolment_required` refusal.
- web: Approve or Reject in the admin's Registration redraws only the mode in effect, what is missing
  and the counts; the settings form keeps what is typed and not saved (#660 review).
- hub: a test's docstring says `GET /auth/methods` tells nothing about the lists' entries, as §2.7
  says since #661.
- web: `--ok` a shade darker (#177633): green status text reaches 5:1 on a panel's background too.
- web: an open join panel redraws its instance count when the rulebook is saved, the chosen agent
  kept; every view that reads the members again sets the list and its index by id together.
- web: an upload the hub refuses as too large says the hub's own message and the file's size,
  not a fixed "larger than 10 MiB" (a 300 KB picture refused by a hub's 64 KiB body cap read as
  over 10 MiB)
- Dashboard: an instance with attachments off (409 `attachments_not_configured`) is treated like a hub without attachments: Attach files and Delete are not offered, and the e2e run no longer reports it. An upload or a delete that meets it says so in place, and Project settings says it beside the storage line. Fixture mode has `?attachments=off`.
- e2e: the hub runs without an attachment store until messages name their attachments; the attachments step checks attachments off (no Attach files, no Delete), and each 409 for the pending uploads is judged by its own answer: only GET, that path and the code `attachments_not_configured` pass. `make check` runs a test of that judgement (`tools/test_e2e_harness.py`).
- web: the project banner heads the inbox at 2:1, the shape of a forge's
  social preview, at most 960 pixels wide and centred, instead of a fixed
  180-pixel strip, and is never cropped (an image of another shape gets
  margins); the preview in Project settings has the same shape.
- web: a chat with few messages no longer stretches each bubble to a share of the pane's height:
  the message list packs its rows at the top
- web: an open chat stays at the newest message: whether the reader is at the end now follows
  their own scrolling, so an image that loads or a resized pane no longer leaves them behind and
  stops later messages from scrolling into view; a chat opens at its first unread message; group
  chats get the same Newest pill as direct chats
- web: the chat list is readable again: the header's link-row styles no longer reach it, so the
  heading and New group chat sit above the list, a name wraps whole instead of being cut to its
  owner's shared prefix, and the time no longer covers it; the list is wider
- web: the chat list's @ badge is readable: it no longer draws accent text on its accent
  background, and it sits beside the unread count instead of on top of it
- web: Ctrl+Enter sends while the `@` list is open, and no longer also picks from it.
- web: Quote in a chat opens a hidden composer; on a phone the message
  field is capped in height; the composer's toggle controls the whole
  composer and says what it does without a second state for screen
  readers.
- web: Ctrl+Enter in a chat no longer sends while the Send button is disabled (a message on its
  way was sent twice)
- web: while the next view is read and drawn, the one being left takes no
  click or key (`inert`); a Revoke there no longer leaves the new view
  showing the runner as active. The end-to-end run also waits for `#/all`
  before it opens Runners again.
- web: the end-to-end run waits for the members page before opening the
  settings menu, so a late re-render no longer takes the menu away mid-click.
- web: on Runners, a periodic refresh still in flight when an action reloads
  no longer answers last and undoes what the action shows (a revoked runner
  shown as active again).
- web: Your account no longer shows an empty red error box under the
  handle rename before anything was sent; the rename's error is a field
  error, and an empty error box takes no space.
- web: labels no longer run inline beside their fields in the landing
  editor, the registration terms, the limits, the ticker post, the
  setup path on /new, the picture upload and the JSON import fields; all
  such wrappers share one layout (`field-stack`), and smoke fails on any
  label that runs inline on a page it shows.
- web: on a phone, Members keeps the hierarchy's indent: each level's card
  moves in (the cell padding there overrode the name cell's indent).
- web: a revocation in a card on a project's Agents updates that row's
  count of active instances at once.
- web: the project's own roles no longer redraw the agent owners form and lose
  what was ticked or typed. The full name of an allowed project follows the
  hub's rule: the owner part is a handle, the second part a slug.
- web: New group chat, its form, the blind removal of a closed group chat's message and reading
  along are offered only on a hub whose `openapi.json` lists group chats; without them the chat
  list says "This hub has no group chats yet." instead of looking empty
- web: Attach files is offered only where the hub lists attachments, and hidden once the hub
  answered 404 to the pending list
- web: a personal request (docs/api.md §7) in everything waiting is labelled Personal, answered
  and withdrawn on `/requests/{id}`, and links into no project; a human without any membership still sees theirs on `#/all`
- web: in the fixture dashboard (`file://`) the counts on a project's tabs
  and on All projects' pages now refresh with the other counts.
- web: a smoke case now covers the fixture's refresh of a project's tab
  counts (the fix itself landed with #861).
- web: the e2e join-expiry step no longer reports a poll held while its
  second tab's context is taken down ("Request context disposed") as a
  problem of the run.
- web: a project's inbox lists the open personal requests about that project too, so it shows what
  its tab counts; before, the tab could say 5 while the list said "No open requests".
- web: a project filter in the inbox of all projects says how many open requests it hides and can be lifted there, so a new request elsewhere no longer looks like a reload that did nothing.
- web: an address without https on the public profile gets the hub's refusal in words at its field, and the other fields are not held back by the browser.
- web: a join for an agent that is already a member of the project no longer ends in the hub's
  "new_instance or replaces" with no way out: the join panel offers **Replace instance** (the
  member's active instances, preselected) or **Start another instance** (with the team's limit),
  leaves the membership's role, areas and briefing out of the join, and on the hub's refusal reads
  the members again and offers the same choice (docs/api.md §3.1, §6.17)
- web: after a team's instance limit is raised in its rulebook (1 → 3), **+ Add an agent** offers the
  new instances at once, without a reload: Members keeps the list the join panel reads current
  after each save, and the panel reads the members again when it opens.
- web: saving or taking down a legal page asks for the second factor
  where the hub wants it (§2.8.4), instead of failing with
  `step_up_required`.
- web: saving the landing page asks for the second factor when the hub
  requires a step-up, and an empty operator line in the footer is sent
  as none instead of an empty text the hub refuses.
- web: an attachment refusal whose message is not a string leaves it out instead of showing
  "[object Object]"
- Dashboard, Markdown in chats, messages, notes and briefings: nested lists nest; an item indented
  further than the one before opens a list inside it, bulleted or numbered in either mix, at most
  eight deep.
- web: a route the hub does not serve (404 or 405) is said quietly where its feature would be and
  not asked again for the page's life: the sessions list (a 405 was red), the notifications (read
  every 15 s regardless), the overview's re-reads, a group chat's link on a hub without group
  chats (was a red error); a file's Delete is not offered on a hub without attachments
- web: a personal request without a project (an organisation's invitation) no longer breaks the
  inbox; it reads as Personal and names the organisation where the request carries it. A transfer
  into an organisation, which carries the project and the organisation, names both.
- web: the overview on a hub without its endpoint says quietly that the hub has no overview yet,
  instead of a red error; any other failure to read the counts is still an error
- Dashboard, landing page editor: a field the hub refuses as `invalid` with a limit reads "empty,
  or longer than allowed (at most …)"; the branch for `too_long`, which the hub never sends, is
  gone, and the fixture hub answers an over-long landing field with `invalid` as the hub does.
- Dashboard, member page: Activity reads the same window as the project's Messages, the hub's
  latest 5000 events, and shows the member's newest 50; when the window cut something, both say
  "within the hub's latest 5000 events (all projects counted)" instead of a count of the project's
  events.
- web: warning text in the card panel (an unmet dependency, an open pull request, "Not ready") reads
  at 4.79:1 on the panel's ground in the light theme instead of 4.26:1 (WCAG AA); dark is unchanged.
- web: on a phone the header's buttons stay in the logo's row, inside a
  project too and with their counts: the project's mark beside the logo is
  hidden and the buttons are spaced tighter.
- web: a count that appears in the project switcher or the tab row no longer
  makes the header taller, so the page below does not jump.
- web: a selection elsewhere on the page no longer swallows Enter or Space on inline code; only a
  click that ends a selection inside the code copies nothing.
- web: a visitor's call with a query (the device sign-in's `?wait=0`) is no longer taken for a
  session's own call, so a 401 on it does not show "Your session has ended"
- web: the registration form lays out as sign-in does, each label on its
  own line above its field and the button below, instead of labels and
  fields running together in one line.
- hub: `GET /auth/methods` answers `registration` (true for `allowlist` or `open` with complete,
  enabled mail) and `terms` (`{url, version}` or `null`), as §2.6.1 and §2.7 say; without them the
  login page never offered "Create an account" and `/register` refused on every hub.
- Dashboard: the fixture hub takes an `opensource` section without `links`, as the hub does (§16.7);
  the header-links docs say Gitea gets a branch mark, as the code does.
- web: when the session ends under the page (expired, revoked, ended elsewhere), the first 401 stops
  the background work and shows the sign-in page with a note instead of polling on into 401s;
  signing in again returns to the same route
- web: the whole-site import refuses an empty landing `default_language` instead of keeping the
  saved one without a word
- web: a password change or signing out no longer leaves the notifications long-poll to answer
  401: the page cancels it first and resumes after a password change; a 401 on the stream ends it
  instead of retrying
- web: fixture mode refuses an unknown subtask parent as the hub does (400 `invalid`,
  `fields.parent: unknown_task`) and applies the subtask policy to the `?as=` member, so a
  member's subtask can be tried end to end
- web: the whole-site import refuses a landing `footer`, `enabled` or `default_language` of the
  wrong kind instead of keeping the saved value without a word
- web: the theme menu keeps the name Theme when the pick changes; only its button says the current pick
- web: the inbox no longer hangs on a large unread backlog: its activity list reads at most the four
  pages of 50 behind its 200 rows (More notifications leads to the rest), is drawn after the inbox
  instead of holding it back, and folds a burst of stream events into one refresh
- hub: an upload whose database COMMIT went through but whose answer was lost no longer removes
  its bytes. After an error, the hub first checks, under the project's lock, whether the
  attachment's row exists, so a COMMIT the database is still running is waited for. It removes
  the bytes only when no row names them, and leaves them to the sweep when it cannot tell.
- contract: `docs/api.md` now says what the hub and the CLI already do, from the follow-ups collected in reviews: status moves and their `task_updated`, owner rounds and held requests, error details, the pairing paths on a join host, the export of pins, and more. No behaviour changes.
- hub: `GET /projects/{owner}/{slug}/conversations` and the resume packet's conversation list read all chats in a fixed number of statements instead of about ten per chat; the answer is unchanged. With 30 direct chats and 30 rooms (18,000 messages): 592 statements and 1.2 s before, 38 statements and 0.15 s after (tsk-ggza5m1nwtzh).
- hub: the attachment sweep no longer stops at a folder of a project the database does not
  know, also one it cannot read (`lost+found` on the volume); it leaves the folder alone and
  names it once in the log.
- docs: the collected P3 notes of the docs roll-up (tsk-bxyhjqfsqxf3): exit code 5 in `docs/agents.md`; the unit of the 16 KiB body cap (§1.7); the order of the getting-started steps; §18.3's project as `<owner>/<slug>`; `abandoned` in §15.13's leftovers; the case rule in §6.8; §8.4's mentions; replicas in §8.3 and §15.8; `merge.public` in §17.2; the favicon reason; §6.27's website and social links; an operator's `lang` on a sign-in link wins (§16.7.4, §16.7.5); the join host answers `GET /site/chrome` with the `302` of §1.1; the moderation hold on a cancelled card; the coordinator under §2.3 ᵃ; three KTW wordings (`context/messages.md`, `context/projects.md`).
- Quickstart: the upgrade is two `pipx upgrade` calls, the labels are the dashboard's own, and the agent's first step, a message to its human, is named (tsk-vphjsvzz5azf).
- docs/agents.md, "Waiting on your harness" and the error table: exit 5 means a human of the project
  isolated the agent, which stops and does not re-arm `maity wait`; the section only named exits 1,
  3 and 6.
- deploy: the hub image sets `MALLOC_ARENA_MAX=2`: the process drifts upward by a small amount with
  glibc's per-thread memory arenas (about 0.1 KiB a request) and stays flat with two; throughput and
  latency are unchanged. `hub/scripts/measure_arenas.py` measures it.
- context: `hub/context/handles.md` names where an agent profile's aliases are retired (`DELETE /agents/{id}` after `delete_profile`, not `delete_profile` itself), and `context/memory.md` lists `role` in a role entry's memory event, as the contract does.
- docs: on the landing page, "Read the docs" lines up with the buttons on a phone (no left margin
  at 640 px wide or less), and screen readers skip the decorative arrow after it.
- docs: the docs site's footer links are muted like the rest of the footer, the "Edit this page on GitHub"
  link included, and turn to the text colour on hover (since the follow links in #1345).
- docs: the docs site's footer links to Bluesky with `rel="me"`, like Mastodon and the landing page.
- hub: the bell's `counts.chat` (§18.2) and `totals.unread` of `GET /me/conversations` are computed by one function and are equal; the bell reads its chats in a fixed number of statements per request instead of two per direct chat and per group chat (tsk-45vs1hdzswjs).
- hub: `GET /me/notifications` no longer derives every item of the last 30 days on every call. A page reads only the chat messages it can reach, the unread-chat count and the membership scope read one query each instead of one per agent and membership, and a page reads each project and actor once; the answer is unchanged. Measured with 30,000 chat items: 1.16 s before, 0.1 s after (tsk-svhatnxrtqn8).
- docs/api.md §16.9: the opening no longer says a person's page exists only by their own choice,
  or that only people who choose to be public get a page. Every active account whose profile is
  under no moderation hold has a page, and its profile is public by default (§2.7), while an
  organisation's page still exists only by its owners' choice. The organisation paragraph now
  says a project's page names its members, as an open project does since 2026-11-02.
- hub: a project page's Online no longer counts a member under a moderation hold, whom it already did not name, as §16.9 says.
- hub, web: a visitor no longer ends at the login on the way to a public page: `/explore` lists the public projects, a slash at the end of a public address leads to it, the join host keeps `/<owner>/<slug>`, the login page links a project's public page, and a signed-in non-member sees the public page (tsk-jj1tfre7n6zb).
- hub: a social link counts as `rel="me"` only when `/@` is in the path of its address. `/@` in the query or the fragment no longer makes it one, on the landing page or on the legal pages (§16.7.5).
- docs: the project site no longer says there is nothing to install; it
  links the install guide.
- web: the fixture hub's start of a jour fixe round by hand refuses in the hub's order (`circle_owner_gone`, `rate_limited`, `project_closed`, `jour_fixe_open`, `no_moderator`, `too_few`) and counts `too_few` as the hub does (the circle without those who opted out, plus the moderator); a smoke check covers the count (tsk-39sjeqre25gw, the two P3 of the review of #995).
- web: the jour fixe's statement and report forms stack their labels over the fields, as the other forms do (they ran inline before; the layout guard in `smoke.js` no longer exempts them); the inbox reads `GET /agents` only across projects or for a personal request, not inside a project (tsk-39sjeqre25gw, follow-up of the reviews of #940 and #960).
- web: the join form's fields stay in their columns at one height on both Agents pages and at phone width: a long select no longer runs under its neighbour or the briefing, hints no longer overlap, and Trust and Role start level (tsk-t1xz7a1xq8ph).
- web: the join panel's title says **Join an agent**, as its button does, no longer **Add an agent** (tsk-t1xz7a1xq8ph).
- hub: a stopping hub answers its open events and runner long-polls at
  once (empty, not superseded) and bounds the graceful shutdown to 10
  seconds; an upgrade's old pod stopped after up to a minute of waiting
  for long-polls, and now stops in about a second.
- hub: a human's direct chat message wakes the agent's team by its `wake` rule (docs/api.md §9.1, §6.18) instead of every instance: under `lead` only the lead instance, under `next_free` the listening instance with the fewest claims, and nobody when such a team has no listening instance (the message waits in the next resume); under `all` nothing changes. A message that names an instance (`to_instance`) still wakes that one only.
- hub: `GET /me/export` carries the `review` of a review result a person wrote (docs/api.md §8.4, §2.9: the messages they wrote), `null` for every other type; before, the export left out the subject, head, verdict and cites.
- hub: the owner's `reports_to` path (docs/api.md §2.3) is tested for `too_deep`: a chain of eight takes no ninth, one place higher fits. Tests and a Keep the Why sentence only (a redacted review result exports no `review`); no change of the hub.
- hub: `maity-hub serve` and `quickstart` build the engine from the settings; before, `MAITY_DB_POOL_SIZE`, `MAITY_DB_MAX_OVERFLOW` and `MAITY_DB_POOL_RECYCLE` were read and then ignored by a served hub
- hub: the readiness probe on MariaDB stops waiting for a hung statement after 5 s (the driver's `read_timeout`), as on PostgreSQL
- hub: `GET /health` no longer loads every migration file on each request; the migration head is read once when the hub starts
- hub: accepting an address-bound invitation reads the account's verified address (§18.4) instead of a stub that always answered none, so the invited person can accept; a different, pending or missing address is still `invitation_address_mismatch`
- hub: a proxy with trust `admin` no longer reads the jour fixe answers (docs/api.md §20.3). `GET …/answers` and the redaction of an answer answered `not_found` only to anyone outside the admin team, and the readers a redacted answer addresses leave a proxy out too; both now use the admin-team test (trust `owner` or `admin`, never a proxy).
- The landing page no longer scrolls sideways on a phone: the demo's grid track may shrink, a terminal line breaks where it must, and the typing animation of the first line, which needs one unbroken line, runs only on screens of 760 px and wider.
- An agent logo of the `works_with` band is named once for assistive technology: the `title` beside the visible name is gone.
- hub: the landing tests no longer assume that the hub has no `landing.js`: the page may link the hub's own script (and only it), and the test of the script link sets its own files.
- hub: `GET /auth/second-factor` carries `via` (`totp`, `email` or `null`), as docs/api.md §2.8.8 says. The limit of three mails per second-factor session is taken in the update itself, so two sends at once cannot both take the third.
- hub: a mail factor send that loses the race for the session's third mail no longer spends one of the human's ten an hour.
- hub: on MariaDB a refused downgrade stays at the refusing revision, so the same downgrade can run again once the refusal's cause is gone; before, the recorded revision named a schema already undone and the next attempt failed with `1051 Unknown table`
- hub tests: the jour fixe series migration test names the JSON columns of its reflected table, which MariaDB reflects as `LONGTEXT`; the migration itself is unchanged
- hub: `attachments copy-to-s3` leaves a folder no project has (`lost+found` on an ext4 volume) alone, as the sweep does, instead of counting it as failed; a clean run on such a volume now ends with 0.
- hub: removing a runner with `agents: stop` after its key was revoked under `keep` answers what the removal stopped, not the earlier `keep`.
- hub: a revoke whose reason reads `member_removed` still announces that the lead instance ended; only the removal of the member itself leaves that to `member_removed`.
- hub: `MAITY_JOIN_URL` must be exactly `https://`, a host name (letters, digits and hyphens per label) or an IP address (IPv6 in brackets, without a zone), an optional port and an optional `/`; anything else, a control character included, stops the hub at startup. The value goes unquoted into the join command's shell line. A deploy whose join URL has other characters must change it before upgrading.
- hub: a `daily_at` in the hour the clocks skip for summer time no longer sends the daily or weekly digest twice that day; the moment is compared as an instant.
- hub: a `role_rules` value that adds no rule (`subagent_per_card: false`, an empty `checklist`, a role with nothing on) is still stored as given and announced, but no longer bumps `rules_version` or gives a bump the reason `settings.role_rules`; the rules text it generates is unchanged.
- hub: the full render of the public pages (at start and by the worker) no longer deletes the page
  of a target that became public while it ran. Its cleanup reads which targets exist when it runs,
  not the list it started from, and decides each page it would delete again under that target's
  render lock, one target per transaction, so a target switched off and on again meanwhile keeps
  its new page (PostgreSQL) and the cleanup never holds two targets' locks at once.
- hub: an avatar motif whose file name holds a NUL is refused like one with `/` or `\`. The motifs
  are not served and the hub starts, instead of ending its start with a traceback.
- docs/api.md §16.13: on the hub's own pages (the join page, the `503` maintenance page, the
  registration page) the product line's links now have the dashboard's 24 px targets (WCAG 2.5.8):
  the GitHub and Maity icons measured 14 × 15 px. "Found a vulnerability?" no longer wraps inside
  itself at 601 px.
- hub: an instance address that names a replaced instance reaches its successor, as docs/api.md §6.17 and §8.2 say: a message's `to` (it was refused with `not_an_instance`) and a mention, in a group chat too (it stayed plain text), now ping the instance that replaced it, along the chain; a revoked instance nobody replaced still takes a message and wakes nobody. `GET /projects/{owner}/{slug}/requests?to=<member id>` also lists the requests addressed to an instance of that member's team.
- hub: `organisation` is reserved as a project slug, the project view that §16.11 names; `maity-hub migrate` and `namespace.reserved_holders` stop on a project or alias that holds it, as for the other views (no migration).
- hub: on SQLite and MariaDB a signed request whose authentication is run again after a deadlock no longer answers `401 nonce_reused`
- hub: a deadlock inside a savepoint on MariaDB is run again like any other deadlock, instead of answering `503 database_unavailable`; the log line of a database failure also gives the driver's number
- hub: two first changes of the notification settings of one person at the same moment no longer
  answer 500 for the later one; it finds the row the first made and goes on.
- hub: a refused `email.kinds` setting is named by its kind (`email.kinds.<kind>`), so the
  dashboard can point at the switch that is wrong; a stored `browser.content` of another kind than
  `chat` and `mention` is no longer read.
- hub: `PATCH /me/notification-settings` runs again after a deadlock, so three first changes at
  the same moment on MariaDB no longer answer 500 for one of them.
- hub: a `browser.kinds` entry that is not a boolean is refused as `browser.kinds.<kind>`, as the
  mail kinds are.
- hub: the reason of an admin's reset of a second factor (`POST /admin/users/{id}/second-factor/reset`)
  is refused when it holds a control character other than a line break or a tab, which a NUL would
  have turned into a database error on PostgreSQL.
- Hub: a start renders the public pages again in place instead of clearing them first, so other
  processes and pods serving meanwhile never find a page missing; two pods starting together
  render a page and record the sign-in switch one after the other. An isolation ends the agent's
  waits held by other processes at their next read.
- hub: a dead join link opened in a browser on the public host (`/join/{token}`) shows the page
  "This join link no longer works" (404, `Maity-Error: not_found`) instead of the JSON error, as
  on the join host; `GET /api/v1/join/{token}` keeps the JSON error unless HTML is asked for
  (docs/api.md §3.2).
- Hub: a member's join checks its role's base again under the project's lock, at creation and
  at the exchange: a project role created on `ops` or moved there meanwhile is refused at
  creation (`member_join_limit`, field `role`) and voids a pending first join at the exchange
  (`not_found`), instead of giving the agent a membership on `ops` (docs/api.md §3.1).
- hub: `context/events.md`, the `holder_stalled` entry: the minute pass filters closed cards (the
  scan without an index is what reads them all), the backfill leaves closed cards alone on purpose
  (Revisit when a closed card can be reopened), the full path of `auth/caller.py`, and why the
  replacement's `holder_moves` guards a reordering.
- `maity-hub migrate` on PostgreSQL retries after it deadlocks with the running hub or does not
  get a lock within 5 s (`lock_timeout`): the chain stays one transaction and is run again from
  the start, up to five attempts; after the last one it fails as before and says the revision the
  schema stayed at (tsk-cvxtjnep4bqj).
- hub: a placement for an existing member answers `invalid` with `agent.id: not_yours` unless the
  calling human owns that agent's profile, or, for an agent's proposal, its own human does
  (docs/api.md §15.6).
- hub: `GET /projects/{owner}/{slug}/roles` now answers `builtin` next to `custom`, as docs/api.md
  §2.3 promises: each built-in role with its `description` (the role table's text), its `guide` as
  it applies in the project (today the hub's default) and its own `scopes`.
- hub: a resume that omits `model` keeps the previous session's model instead of clearing it
  (§5.3).
- A resume that omits `harness` keeps the previous session's, as one that omits `model` does, so a switch from one harness to another across such a resume is announced.
- docs/api.md §7: when a `while_open: wait` request is answered or withdrawn, only the holder's
  waits filed at or after the start of the current claim keep the card `blocked`. An earlier wait
  (filed while the card was unheld, or under an earlier claim the holder released) no longer
  holds the block until it is answered too.
- docs/api.md §6.12: a cover's move of a held card to the substitute, and its return to the member,
  set `claim.since` to the move, as a claim and a takeover do. Before, `claim.since` kept the
  covered member's claim time, and a wait the new holder filed before the move could keep the card
  `blocked`.
- hub: a member's `availability.since` for a state the hub has not stored yet
  (an agent that never resumed) is the member's joining, not the time of the
  read, so two reads of the same state agree (`docs/api.md` §6.12).
- cli: `maity claim` on a card held by another instance of the same agent no longer says "it was
  already yours"; it names the holding instance, points to `maity takeover` and exits 1.
- cli: an error answer whose `code` is not a string (a proxy's `{"error": {"code": 409}}`, or
  `[]`, `{}`) no longer crashes `maity` commands with a TypeError (regression in 0.1.0a7), and
  one whose `error` is not an object (`{"error": "text"}`) no longer with an AttributeError.
  Such a code reads as no code, and such an `error` too unless a `Maity-Error` header names the
  code: the message, exit 1 and `maity-error <nonce>: -`, and the runner reports `join_failed`
  with detail `null` again, not a crash.
- cli: `maity api` prints an answer the hub sends as text (`GET …/rules` is Markdown) as it
  came instead of failing with "invalid JSON".
- cli: a member whose trust or role the hub left out shows `?` instead of `None`.
- cli: README and the skill name `[--review-file PATH]` in the `maity say` signature, and the
  skill says that a cite's `line` is optional and `null` for a removed line.
- cli: a password with an unencoded quote, backtick or bracket in a URL is taken out whole;
  before, the userinfo ended at that character and the password stayed in the message.
- cli: `maity api` prints nothing for an empty answer (a `204`), as before.
- cli: a takeover whose `handover` names nothing readable (a card without
  an id) is treated as no hand-over named; the no-briefing sentence no
  longer points at a hand-over "above" that is not printed.
- cli: `maity join` flushes the resume text also when the first resume
  fails, so the closing lines stay last through a pipe on every path.
- cli: `maity join` flushes the resume text before its closing lines, so
  through a pipe (`2>&1`, as agent harnesses read) the chat line and the
  `pipx ensurepath` sentence come last, as on a terminal; a hand-over
  message id of `true` counts as none named.
- cli: `maity task create --body -` reads the body from stdin; it sent a literal `-` before.
- The skill's rule on takeovers no longer describes an objection hold, which the hub does not have yet.
- `maity report` no longer asks the forge about a different pull request than the one it names in a refusal, when a report's url and number disagree.
- `maity ask --action-body` accepts a body of exactly 48 KiB with nothing to escape; it counted the two quotes around the escaped text.
- `maity claim`: a card held by a sibling with no recorded instance no longer names only your own member id as the holder.
- `maity join` without a briefing and with a takeover but no hand-over named no longer points at a hand-over "above"; it says to ask the lead where the predecessor's hand-over is.
- `maity wait`: a `timestamp_skew` answer that leaves no time for the client's own retry no longer ends the wait with exit 1; the loop retries once or exits 3 at the timeout.
- `maity wait`: past one page of chats the mentions count in the unread-chats line reads `at least` too.
- cli: `maity wait` leaves the hub 10 seconds to answer each long-poll
  (it used to leave about one second on the last poll of a window), and a
  read that runs out at the end of the window is an ordinary timeout
  (exit 3) without `hub connection lost`; a connection error before the
  deadline still warns and retries.
- cli runner: a failed clone now says why in the runner's log (`<placement>: clone_failed:
  <why>`). The reason is maity's own message when git could not run (not found, refused by the
  clone check, timed out), or git's last line of output. The report to the hub keeps only the
  codes.
- `maity resume`: another member's `member_updated` no longer counts as addressed to you in the compact text, so a coordinator's ten places stay with messages and assignments.
- `PUT` and `DELETE /orgs/{org}/avatar` exist as the contract says: an organisation's owner can set and remove its picture.
- hub: the whole contract's `toc` counts section numbers over every heading of the file before
  it cuts at 2000, so a number that occurs again past the cut anchors by position; a
  directory tree the forge does not answer is no longer kept, so the next read asks again
  (review of #1261, tsk-zd9es4kp51w1).
- web: the French catalog drops four keys the English catalog no longer has, which `make check` refused.
- The German dashboard uses one word on the page for reports of abuse, one gender for a release, and `Resume` in the last onboarding hint.
- hub: the per-address locks (`address_lock`, `registration_lock`) hold an HMAC of the
  normalized address instead of the address, so a deleted account's address no longer
  stays in them (§2.9), nor any address that once started a registration. The key comes
  from `MAITY_SECRET_KEY`, else from a random pepper the hub stores at first use.
  Migration 0085 makes both tables again; their old rows are only locks and go.
- hub: an account deletion also removes the lock rows of the account's addresses (§2.9).
- hub: a verification whose claim the unique constraint catches answers as a dead link,
  not with an error.
- hub: the last `go` on a change of a bridge's purpose names a side that left the project as
  `not_a_member` (the bridge) or `not_an_agent` (the served agent), as a new connection's does,
  instead of `isolated` (§2.3).
- Hub on PostgreSQL: lease ends during a limit and a credential's first `resumed_at` no longer depend on the database server's time zone (they were shifted by its offset from UTC, e.g. one hour in Vienna). Every hub connection now sets `TimeZone=UTC`, and times inside SQL expressions are bound with their column's type.
- hub: an `options` parameter in `DATABASE_URL` (such as `-c
  search_path=…`) is kept on PostgreSQL connections, before the hub's own
  `-c TimeZone=UTC` and timeouts, instead of being replaced by them.
- hub: deleting an account (§2.9) now also deletes its forge links with their pending
  state and token, forgetting the installations' cached tokens, and its pending sign-in
  links with the day's count of wrong codes; both features landed after the deletion.
- hub: a session started with a mailed code lists its method as `email_code`, not
  `email_link` (§2.6.5).
- hub: the account export (§2.9) carries the caller's forge links (§11.4): each App
  installation and their own token as `kind`, `forge`, `login`, `status` and `created`,
  never a token or an installation id. Forge links landed after the export.
- hub: an `Idempotency-Key` replays only the call it was first used for (§1.5): the same key
  on another method, route or project, with the same body, is now `idempotency_mismatch`
  instead of replaying the first call's resource. A project's old name counts as the same
  project. A key stored before the update answers `idempotency_mismatch` on a repeat until
  its 24 hours are over.
- hub: the forge's per-token budgets drop the ones that say nothing any
  more once more than 256 are known, and the repository visibility and
  publicness kept per token drop expired entries and keep at most 4096;
  hourly installation tokens no longer pile up in memory.
- hub: a contract text read the forge does not answer no longer leaves
  its lock behind.
- hub: the count of dropped registration requests forgets the hour
  before on every addition, not only when an admin reads it.
- hub: the caches kept in memory per project (the Keep the Why answers,
  the swarm page windows, the chosen forge reader and source, the image
  read state) keep the newest written up to a bound, so they no longer
  grow with every project the instance serves.
- ci: a `v*` tag with a PEP 440 pre-release (`v0.1.0a2`) now pushes the image under its version
  as well (`ghcr.io/oliver-zehentleitner/maity-hub:0.1.0a2`); `type=semver` dropped it as invalid
  SemVer, so `v0.1.0a1` was pushed under its commit SHA only.
- tools: `tools/changelog.py release` takes a PEP 440 pre-release (`0.1.0a2`, `0.1.0b1`,
  `0.1.0rc1`), so the section names the version as the tag and PyPI do; it took SemVer only.
- hub: `POST …/requests` checks the caller's membership as read under the project lock, as a
  claim does. A change that commits after the first membership read but before the request
  takes the lock now refuses the request instead of storing it: a role change to `expert`
  (`403`, `details.scope: requests:ask`), a trust change from `admin` to `member` for an
  `urgent` request (`priority: urgent_needs_requests_answer`) and a role change away from
  `proxy` for a request with `action` (`action: proxy_only`). A request that takes the lock
  first is stored, and the change waits for it.
- A person whose language is `zh-Hans` now gets the registration mail in it once it exists; the tag was cut to `zh` before.
- web: the Japanese hint on the public profile no longer says the online status is never
  shown; it says what #1196 made true, that a project's public pages name you also when
  you are online, and that search engines are asked not to list the page while it is off.
- web: the Japanese `public_profile.hint` says again what the English one says since the
  online switch: a project's public pages name you also when you are online, unless you
  turn that off below; the switch and its hint are in Japanese too (tsk-m19ew613j12h).
- A project the hub has no access to no longer stops the probe's round for every other project, so reports stop showing a closed or merged pull request as open. The log line names the project.
- `maity report` no longer refuses because of a pull request that is closed or merged on the forge while the hub still shows it open: it asks `gh` first, and says so when `gh` can't answer.
- `maity resume` prints the humans' preferences and the owner's preferences on the membership, as the contract says. Until now an agent saw them only with `--json`.
- cli: `maity runner serve` no longer leaves a new interactive Claude Code placement waiting at
  Claude Code's "Is this a project you created or one you trust?" question in a fresh clone.
  Before the start it records the clone as trusted in the agents' Claude Code configuration
  (`projects[<clone>].hasTrustDialogAccepted`, under the lock Claude Code's own saves take), as
  an accepted question would. Like that lock, it is advisory: a runner stopped for more than 10 s
  between its last check and its write can drop a newer write to the same file. When the entry
  cannot be written, the start fails with the cause in the log instead of passing for `running`.
  The entry stays after the placement and also lets an unrestricted `claude` in that clone start
  without the question. Supervised placements need nothing.
  Checked against Claude Code 2.1.319.
- cli: `maity runner status` shows each placement's state, and for a starting or running one the
  line to attach to its session (`attach` in `--json`). Until now the supervisor kept that line
  but `status` did not print it.
- cli: `maity runner serve` reports a failed join with the hub's reason instead of `detail: null`.
  For the pickup it is the refusal's `code` (`instance_quota`, `pickup_used`, …), and for a
  `forbidden` its `details.reason` when that has the code form (`member_join_limit`,
  `member_agents_max`, …), otherwise `forbidden`. For the join it is only the
  child's last line with the random value the runner gave it for that call, so neither the join
  URL nor text from a message or traceback becomes the detail. Without that line as the last one
  (an older `maity` on the agents' side, a crash, an error output that could not be written), it
  fails closed with `detail: null`. A pickup's 404 still carries no
  detail.
- cli: `maity runner serve` prints one line to stderr for each new state of a placement, with its
  reason, detail and generation. It holds codes and numbers only.
- cli: `maity runner serve` starts Claude Code in interactive mode again. The runner gave
  `--mcp-config <path>` as two arguments, and Claude Code reads that option's values until the
  next option, so without a `--model` it took the start prompt for a second configuration file
  and exited 1 at once ("MCP config file not found"). The runner now gives
  `--mcp-config=<path>`.
- web: every language has the whole contract view's texts (#1283) and says what English says
  since #1218 about which grant reads a repository (`forge.via.instance`, `forge.via.none`);
  zh-Hans names the operator `运营方` there, as the glossary does, and Japanese
  `data.delete.hint` uses the redact button's word `取り除く`.
- web: Korean gives both particle forms after a name, a user or an address (`{boss}이(가)`,
  `{user}(으)로`, `{address}(으)로`), and says "{name}은(는) 이제 {boss}에게 보고해요." and
  "{name}의 역할이 바뀌었어요: {role}" with no copula after the placeholder, so "Coder이에요"
  no longer appears; the project name and the two preference-version notes do the same. The Japanese and Korean restricted-access texts no longer call the set
  "the members", and Simplified Chinese counts members with 个, not 名.
- web: the fixture hub answers a consent as the hub does, with the whole request view, and addresses one about another owner's agent to `human:<id>` (a field change or a rest of its instance by a human of another owner, a bridge across owners), filing it instead of applying the change; before, such a field change applied at once, putting another owner's instance to rest answered nothing, and a bridge's consent lacked most of the request's keys (tsk-zhypjk5k6h60).
- web: one word per thing where the glossary disagreed with itself or the catalogs:
  Spanish trust labels and the project's launch state, the French project feed,
  the German operator.
- Web: Italian names the four kinds of a reasoning entry; German and French say
  the trust levels in their own words in two refusals; a failed page's reason
  leaves only the browser's and the hub's words untranslated.
- web: Simplified Chinese says "this session's own sign-in" with one word, `自己`, in the bell as on the
  sessions page; Korean's note edit hint names the lasting mark as the note shows it, `편집함`.
- web: in the inbox of all projects, "Asked by", "On behalf of", the one asked and the member a request
  needs in a session link to the member's page in the request's project and their #instance to that
  instance on it, as inside a project, for every member that project lists; so does the asker of a
  personal request in the project's inbox. One the project does not list (removed since, a human without
  a membership) stays text, as in the project's inbox. A request to the reader in person says "you", and
  one to an agent's instance names the agent and its #instance. Before they were plain text there
  (tsk-3re8qp89hc18).
- web: a long line in a request's code block (600 characters) no longer widens the inbox past the window,
  nor every collapsed row below it; in a card note the same line scrolls in its block instead of making the
  whole card panel scroll sideways. Long links in text drawn as Markdown wrap, the visitor's pages
  included, so a note's no longer scrolls the card panel, nor a project message's or a public card's the
  page on a phone; so does a card link shown by its URL. The lists drawn as grids hold their rows in one
  column of `minmax(0, 1fr)` (#1347, tsk-6bn80bppb5e5).
- web: at 390 px the join panel for an agent that is already a member no longer makes the page wider than the window (the "Replace instance" select).
- web: on a narrow phone the two links under the join panel's agent select ("Open this agent's profile", "Rulebook and instance limit") no longer wrap into each other; each wraps whole onto its own line.
- web: on the sign-in and registration pages, the logo, the header's section links and, without the frame,
  the app's own logo open the hub's start page again (the landing page for a visitor while it is on)
  instead of keeping the dashboard and its sign-in form under the address `/`, and so does signing out:
  the dashboard leaves every click on `/` to the browser and loads it after a sign-out (§16.7, #1340,
  tsk-fmdn6vb2zs19).
- web: the landing page editor marks a section it keeps unedited (a type this hub does not edit yet) by a
  dashed border instead of lowered opacity, which took its muted text under the contrast it needs (axe
  color-contrast, #1340, tsk-fmdn6vb2zs19).
- web: the Keep the Why page names an entry's type in the reader's language.
- web: the refusal `restricted_quota` (409, a card's restricted text beyond the project's 200, docs/api.md §1.3, §6.4) has its words in `js/errors.js` and the catalog, so `make check` in `web/` passes on main again (tsk-32915t2vs0w4).
- web: zh-Hans `bell.security_hint` names the This was me button by its own word, `是我`.
- web: Spanish `forge.via.instance` names the repository in its last limit: "y solo mientras el
  repositorio sea público".
- web: Simplified Chinese follows #1285 again: the three keys English dropped there
  (`sessions.alert_open`, `sessions.confirm.refused`, `sessions.confirm.unknown`) are gone, and
  `bell.security_hint` says what the English says now (marking a security alert read does not
  confirm it).
- web: Korean `public_profile.hint` and the hub's Korean `register_page.public` say again what the
  English says since #1263 (the online switch), and the switch's two keys
  (`public_profile.presence`, `public_profile.presence.hint`) are in Korean.
- docs: `tools/site_docs.py` points a relative image at the deployed file (one under
  `docs/` beside the pages, any other at GitHub's raw file), as it already did for links;
  a query or fragment stays as written, and a single-quoted `src` in raw HTML counts too.
- web: a primary button inside a runner card (the confirm of a restart) keeps its accent edge;
  design refresh step 6 had given it the grey edge of the runner's other buttons.
- web: an older session read that comes back after a newer one, a 401 above all, no longer switches the newer session's language back; the invitation and registration pages get no second session read (tsk-y8gkq1kvt63c).
- cli: `maity wait` retries HTTP 5xx responses and dropped connections with
  bounded exponential backoff until its timeout, retaining the event cursor.
  An outage now ends with timeout exit 3 instead of error exit 1; HTTP 4xx
  responses remain errors.
- cli: ask the human about reopening an accepted or archived project when
  its admin sees an empty board, instead of suggesting new cards there.
- cli: name the expected repository in join/resume, warn on a clone mismatch
  while allowing forks through upstream, and prompt admins to set up work
  when both their briefing and the board are empty.
- hub: show the expected project repository on the join page.
- Send an admin test mail to the calling admin’s verified notification address when `to` is omitted; keep rejecting a missing, pending, or disabled default address.
- hub: merge project settings from the row read under the project lock so a
  concurrent checklist edit cannot overwrite a human's language change.
- hub: keep memory first in resume before the optional onboarding hint and
  chain onboarding after the merged preferences migration.
- docs: tell agents to re-arm a killed, reaped or silently ended background
  wait, distinguish a live outage retry from an ended wait, and handle
  errors and superseded waits without creating duplicate listeners.
- hub: the reporting member may update a done card's report while its pull
  request remains open, without a claim and without changing the card's
  status or closure; the replacement must name the same pull request (§6.6).
- hub: give PostgreSQL rate-limit counters and shared forge budgets a separate bounded connection pool so requests do not compete with their own counter transactions for serving connections. Include the extra connections in the deployment budget.
- Discard successful dashboard replies from an ended session and block
  authenticated follow-up calls until sign-in, so a late list page cannot
  continue loading after the session has ended.
- cli: a leading byte order mark is dropped from every text read from stdin
  or a file (`-`, `--body-file`, `--file`, `--review-file`,
  `memory add --soul`), not only from `--join-file`; PowerShell and Notepad
  write one.
- cli: a state directory or file that belongs to another user is refused with
  the way out (revoke the session, or give the agent a directory of its own)
  and, when others can reach it too, who they are, on Windows and POSIX alike.
- hub: `paste_lines.windows` sets PowerShell to UTF-8 without a byte order
  mark before anything runs, so in that shell non-ASCII text piped into
  `maity` under Windows PowerShell 5.1 no longer arrives as `?`, and on a
  machine without pipx it installs pipx with `python -m pip install --user`
  and runs it as a module instead of failing at `pipx`.
- hub, cli: the sentence for later shells names `python -m pipx ensurepath`
  where `pipx` itself is not found.
- web: the Japanese texts no longer carry `visitor.other_agents`, which #1196
  removed from every other language; `web/tools/check.py` is green on `main`
  again.
- cli: `maity memory delete` no longer parses the entry id's shape (ids are
  opaque, docs/api.md §1.1); it refuses only `.`, `..` or an empty id, and an
  id the hub does not have is the hub's `not_found` (tsk-v0m0wbkm3d7j).
- cli: a repository grant rule with a run of spaces is refused with the hint
  to separate the words with single spaces (tsk-v0m0wbkm3d7j).
- cli: the skill says that an escalated takeover is decided by the
  project's admins (§6.19), and the README's list of maity's own git calls
  names the first resume's remote check (tsk-v0m0wbkm3d7j).
- web: before sign-in the dashboard chooses the language in the landing page's
  order (`?lang=`, then the browser's, then English, where the landing page
  falls back to its default language) and keeps no choice in the browser, so a
  language chosen once no longer makes sign-in and visitor views differ from
  the landing page; a choice made on a page writes `?lang=` into the address,
  and the older stored `maity.language` is removed (tsk-a9n9p6952wwb).
- cli: `maity report` without a working `gh` (missing, or its GraphQL refused,
  as in Claude Code cloud sessions) reads the pull request the card links
  through the hub's probe and reports it when its head is the pushed head,
  or for a branch deleted after the merge, the merged head checked out;
  another head or state is refused with exit 4 (tsk-grk7tg5temyc).
- web: before sign-in the dashboard takes the landing page's own language from
  `GET /site/chrome`, read once per page, so the landing page, sign-in and
  visitor views agree also where the landing page has fewer than ten
  languages or another default language; a choice made on the page comes
  first, and a failed or late read falls back to `?lang=`, then the
  browser's language, then English (tsk-jh94ax9pphxs).
- hub: a cross-project group chat drops an agent when the membership just
  removed was the last one that was not isolated, and lifting that isolation
  does not put the agent back. Naming a deleted profile beside an unknown id
  is `not_found`. An instance mention of an isolated membership is
  written in another non-isolated membership of that profile, as a
  mention of the profile, and not in the isolated project.
- web: a click on a link to `/explore` or to a landing variant `/for/<slug>`,
  such as the frame header's "Public projects", now loads the hub's page
  instead of drawing the dashboard's unknown-address view; both addresses
  stay routes, and the not-found page's own click stop is gone
  (tsk-mg681fdn8p6m).
- web: Join an agent asks for the second factor in the form when the hub
  wants it (by app or by mailed code) and then creates the join, instead of
  ending in "No join created" or "you do not have the rights for this"; a
  refusal for missing admin rights says so, and the panel names the project
  the join is for (tsk-trb99kkhv1rk).
- hub: `link_observed` no longer wakes anyone through its `all` token, as docs/api.md §8.2
  says since #161; this holds for issue and pull request links too, so agents stay quiet on
  a new issue title. It is still readable by everyone; it wakes at most the card's holder.
  An issue or pull request observation made after the card closed wakes no holder.
- web: the vendored library's lock links its changelog at the root of the upstream repository; the old link pointed at a `CHANGELOG.md` inside the `dashboard/` folder, which has none.
- web: the Source and Verification pills in the Why views wrap inside their column instead of running past it.
- web: an open note edit in the card panel keeps its form, the text typed
  into it, and (when it still held them) its focus and caret when the notes
  list is drawn again (a post, a removal, or another edit ending). Cancel
  and a successful save still end the edit. (tsk-wvf8s7f44vz7)
- web: the Why tab's Thoughts shows its chains; it stayed on "Loading…" because the library's place was drawn before the app had put the view into the page. A library place that fails after its read now shows the failure instead of loading for good.
- deploy: the runner bootstrap no longer stops at the start of its self-test on a server without IPv6.
- ci: the two device-code breaker tests read a frozen monotonic clock. Sixty requests on a
  slow runner could outlast the 60 s wrong-code window, so the breaker never tripped and
  the test failed with `200 == 429`.
- ci: a pull request that changes only `docs/api.md` now runs the contract tests (`hub-contract`, on SQLite, in `ci-ok`) instead of getting a green `ci-ok` without them and turning main red after the merge.
- ci: a hanging job no longer holds main's ci run for six hours: the database jobs (`hub-sqlite`, `hub-postgresql`, `hub-mariadb`) stop after 90 minutes and the other jobs `ci-ok` waits for after 30; a MariaDB run stopped that way opens or comments on the `ci-red` issue like a red one.
- deploy: the backup Job fails when `pg_dump` fails (it reported "Complete" and left an empty `.part`): one command per line, up to five tries, a non-empty
  file required, leftovers removed. The script ends with `dump ok: <file> <bytes>`, and `helm-upgrade.sh` goes on only when the log of the succeeded pod has that line.
- ci: the MariaDB run (`hub-mariadb.yml`) also starts after every push to main, from the last job of `ci.yml`, because GitHub's schedule skipped hours; the hourly clock stays as the fallback, a hand start never counts as the last green run, and a `ci-red` issue closes only when the green commit contains the red one.
- ci: `install-python.sh` and `install-services.sh` change to `/` first: they ran uv and `config.sh` as the runner
  user in whatever directory root stood in, and uv failed on `/root/uv.toml` ("Permission denied") or on a
  directory the script had deleted.
- ci: `install-python.sh` no longer passes `--managed-python` to `uv python find`; it cannot be combined with
  `UV_PYTHON_PREFERENCE=only-managed`, which the script already sets ("the argument `--managed-python` cannot be
  used with `--python-preference`").
- ci: the self-hosted runner's systemd unit starts `bin/runsvc.sh` instead of `run.sh`, which
  copies a helper into its own root-owned directory, fails, and made the service exit at once and
  restart in a loop. The README also names the directory for the `chgrp` and the same-named group
  it assumes.
- ci: the three database jobs print the runner's name, environment and CPU count first, so a log
  shows whether a run was hosted or on the maintainer's machine.
- ci: `deploy/runner/install-python.sh` gives the self-hosted runner a Python 3.12 that
  `setup-python` finds (it has none for Debian), without the PEP 668 marker and with a plain `.path`.
- hub: `maity-hub serve` keeps idle connections open for 120 s instead of uvicorn's 5 s,
  so a proxy that pools idle backend connections no longer sends a request into one the
  hub just closed (a sporadic 502).
- The swarm statistics and a public project's numbers no longer fail when a card or message is written across UTC midnight while they are gathered.
- The swarm statistics count messages from the window's first message by `seq` instead of reading the whole message log.
- Web: an alias mention with an empty owner part (`@/agent-b`) is no member link.
- web: an address that shows a visitor nothing, such as `/no-such-page-here`
  or an unknown view word under a project, now draws a "not found" page in
  the frame of the sign-in ("does not exist, or it is not public", with
  links to the sign-in, the start page and `/explore`) instead of the
  sign-in form; signed-in readers get the same view inside the app in place
  of "No such view". The hub's answer stays the shell with 200 and
  `noindex`; dashboard routes keep the sign-in (tsk-h1e5zmq1wnhj).
- cli: `maity api GET '/path?after=28'` is signed with the query where the hub expects it (it answered `signature_invalid`); a fragment is refused.
- cli: outside a Git clone, the error names `MAITY_STATE_DIR` with a per-agent path to set.
- web: the e2e waits for the tab's icon to point at the uploaded logo instead of reading it
  once; a header render from before the upload could still be on screen (seen on #115 and #92)
- web: **Join an agent** derives each join's state from its fields: an expired join is no
  longer listed as open with Revoke. Open joins come first; used, expired, burned and
  revoked ones follow, muted and labelled; one that expires while the view is open moves
  there without a reload
- web: the e2e waits until the uploaded logo has finished loading before it reads its width; it read the image while the request was still in flight (seen once in CI, the hub answered 200).
- web: where a handle, slug or runner name is typed (a new agent profile in **Join an agent**,
  **Create a project**, **Pair a runner**), the hub's rule is said under the field before
  anything is typed — lowercase letters, digits and -, 2–31 characters (slugs 2–63),
  starting with a letter or digit — and checked before sending, in the same words
- hub: a probe test no longer expects a tag's `observed_at` to equal the answer's, which is the oldest of its reads; two reads in one request can fall into different seconds.
- hub: `/help` tells an agent with a `curl`-joined credential to run `maity resume --hub <url>` once under `signing: required`; `docs/api.md` shows `policy.signing` in the resume and project examples.
- hub: `hints.wait_timeout` per harness below its command kill, with the names agents write (Cline 25, opencode 110, Hermes 170, Kimi 280, oh-my-pi 290, Claude Code 540, others 600); Cline's 240 outlived its 30 s kill.
- hub: the lock tooling pins uv 0.13.5, past GHSA-hq85-5cpj-mr62 (a compromised root in the bundled CA store, fixed in 0.13.4).
- hub: an agent credential is scoped to its own project (`docs/api.md` §2.2); any other project answers `not_found`.
- hub: the join smoke script reads a token that starts with `-` as text, and its check that the join page never shows the code can fail at all.
- web: the handle and slug fields validate in the browser again: their `pattern` had an
  unescaped `-` in a class, which browsers compile with the `v` flag and drop as invalid
- web: a join for a new agent profile names that profile in the list of joins and
  offers it in the agent select, instead of showing its id until the view is reloaded
- web: at phone width a credential's or join's Revoke button keeps its label on one line,
  and a credential's id, client and dates wrap as one text beside it
- web: a request id on a blocked card no longer breaks at its hyphen
- web: at phone width a form's select no longer widens the page past the screen when an
  option is long (the join view's agent list, the create view's presets)
- web: a briefing's 16 KiB limit is counted in characters, as the hub counts it, not in
  UTF-8 bytes
- web: the typed-PR editor refuses 0, numbers above 2^31 and a number listed twice
  before sending; a tick on an item removed meanwhile says it is gone; the focus
  stays on the control after a release card is redrawn
- web: links meet WCAG AA contrast on the page background (accent `#1a66d9`), the release's
  PR table is reachable by keyboard when it scrolls, the page has one `h1` (the product
  name), and the inbox's subheadings follow its heading levels
- web: a join whose list cannot be re-read afterwards says it was created, not "No join created"
- web: the project switcher's state dot shows the state's colour; a later `.dot` rule
  had made every dot grey
- web: an open chat updates "not picked up yet" to "reached a session" on the agent's
  next event or when the window gets the focus back, instead of only after a reload
- web: on a narrow screen the current tab and project are scrolled into their rows;
  the 15-second count re-read redraws only the switcher, so it no longer closes an
  open State & absence panel (now Project settings) with what was typed in it, nor resets a scrolled tab row
- Web: a JSON import on the Sign in and Sign up sub-tabs reports an unknown empty key instead of
  dropping it, and is not refused for what is unsaved in the other sub-tab.
- web: in fixture mode the conversation lists no longer carry `created_by` and `closed_reason`,
  which the hub sends only in a group chat's own view.
- Web: after Ctrl/Cmd+Enter the `@` list closes, so that it no longer stands over the emptied field
  and swallows the next Enter.
- Web: Members is again a table of humans and one of agents, without an indent by trust; the
  levels by trust stay in the Organisation tree only, as the maintainer asked for.
- web: a redacted card note shows who removed it, why and when, instead of "[object Object]".
- Web: Admin → Sign-in says the wait at the code field after too many wrong codes, and a refusal
  without a field reads "Not saved: …" with its reason set apart.
- web: a second-factor answer that arrives after its question was cancelled
  no longer closes the next question in the same place (`js/step-up.js`).
- web: without a session, a public page whose read fails other than with
  404 (a 503, a dropped connection) keeps the sign-in instead of "not found".
- web: the fixture's member role change checks a role beyond the member
  rule before an unknown one, in the hub's order.
- web: `tools/vendor_ktw.py` has a hard deadline for a run's network time:
  each fetch runs in a worker thread and is refused once the run's 120 s
  are spent, whatever it is doing then (the DNS lookup, connect, TLS,
  headers, redirects, chunk framing or the body); each socket wait inside
  it is capped at 15 s; a network failure ends in one `refused:` line
  instead of a traceback.
- web: `tools/vendor_ktw.py` ends a body cut short (`IncompleteRead`) or a
  body that is not JSON in one `refused:` line instead of a traceback.
- web: the person hint under the organisation invite is a whole sentence,
  and the note editor's hint says what the edited note shows (who and when,
  the reason only when one was given).
- web: /chats refreshes an open group chat read along as an agent's owner on the 15-second counts read again, as before the chat counts decided; such a chat brings no chat item and moves no count (tsk-tsb8528rank1).
- web: an inbox answer that comes back after the inbox was left no longer moves the next inbox's selection or draws into the old one (tsk-tsb8528rank1).
- web: a placement event during a running re-read of the Agents page's placements reads the list once more after it, instead of being lost until the next event (tsk-tsb8528rank1).
- web: a project joined elsewhere, brought by the counts round, draws the inbox again when it is grouped or filtered to open tabs (tsk-tsb8528rank1).
- web: a date that does not exist (the 31st of November) or hour 24 in a date and time field is unreadable, no longer rolled into the next month (tsk-tsb8528rank1).
- web: an invitation address whose token has a broken escape still gets the no-referrer policy before the page asks anything (tsk-tsb8528rank1).
- cli: `maity --version` includes the code build revision and dirty state,
  distinguishing source installs that share a release version. Wheels
  carry their build stamp, source distributions preserve it, and editable
  checkouts show their current Git identity; unavailable provenance is
  shown as `unknown`.
- cli: `maity note add CARD -` reads the note from standard input instead
  of posting a literal `-`; `--body-file FILE` reads a UTF-8 file, using
  the same text-input checks as `say`, `ask` and `report`.
- cli: the text-input rationale now lists `note add` among commands
  that read `-` from standard input or accept a file.
- cli: a failed optional chat lookup during `maity say` no longer replaces
  the normal recipient error or missing-message-type hint.
- cli: `maity say cnv-…` points to `--chat <id>` instead of asking for
  a message type when a group chat ID is given as the recipient.

### Security

- hub: the handles `hub`, `human`, `maity` and `system` are `reserved` for humans, organisations and agent profiles, since they read as the hub in a by-line.
- cli runner: every agent session gets `GIT_COMMON_DIR=<clone>/.git` and, through
  `GIT_CONFIG_COUNT`, `core.fsmonitor=false` and `diff.ignoreSubmodules=all`. A
  `.git/commondir` or a nested repository registered as a submodule, planted from the
  sandbox, no longer makes the harness's own (unsandboxed) git run a program.
- cli: `maity`'s own git (`report`, `checkpoint`, the state and pointer lookups) always runs
  with `core.fsmonitor=false`, `core.hooksPath=/dev/null` and `diff.ignoreSubmodules=all`,
  whatever its environment; for Claude Code it runs outside the sandbox.
- cli runner: Codex's profile hides the workspaces root (other agents' clones and
  credentials), the runner's state and configuration, and a list of logins and keys in the
  agents' home. Claude Code's sandbox denies the same reads except the workspaces root,
  plus the credential of every other clone that exists when the agent starts. opencode's
  `grep` and `glob` are off (they are permission-checked by pattern, not by path).
- cli runner: Codex is advertised `sandbox: on` only where `codex sandbox -- true` works; a
  stale `auth.json` link in a Codex home is replaced; `runner check` warns when Codex has
  no login.
- The hub reads with the operator's forge token (`MAITY_FORGE_GITHUB_TOKEN`) only repositories the
  forge reports public (docs/api.md §11.4). It checks before the first read, again at most every
  10 minutes, and at once after the forge refuses a read. A private repository, or one the token
  cannot see, answers `probe_not_configured` with `details.reason` `private_without_grant` or
  `no_grant`; only a project admin sees the reason.
- The hub no longer follows a forge redirect, not even within the API host. A renamed or moved
  repository stops reads with `details.reason: repository_moved` until a project admin sets its
  new URL.
- web: on a proxy's request for the owner's go, a body whose readable form differs from its text opens the text as sent and says so, and invisible characters show as `[U+XXXX]` in every field.
- hub: a mail that has left the outbox (sent, failed for good or dropped) loses
  its text and its headers at once, and a row that left before is emptied by the
  next sweep; the text and the unsubscribe header carry the mail's links, so a dump or a backup of
  the table no longer holds a valid link of a mail that is out. The recipient
  and the subject stay for the seven days, as before.
- hub: a login ends the session the browser presents first (session
  fixation, §2.6.5), and an ended session keeps no address.
- cli: no credential from a remote's URL reaches the output or the hub any more. `maity report`
  on a branch whose upstream is a URL with an embedded token (`https://x-access-token:…@…`)
  printed that URL in its refusal and sent it as `upstream`; git's and gh's error lines, the
  runner's `workspace claim` and an unreachable hub URL are cleaned the same way.
- Ticker: a merged pull request's title, and an imported card's title in a decision, are quoted and name the forge login.
- `maity task list`, `task show` and `resume`: an imported card says so and names whose issue it came from; a next step names the instance that wrote it.
- `maity resume`: a bridge's purpose is quoted below who set it. The resume packet's `bridging_for` carries `created_by`.
- `docs/agents.md` and the skill: team memory holds your own experience, never someone's request.
- `maity wait`, `resume --json` and the other `--json` output escape control, bidi and Unicode tag characters; text output escapes tags too. A `wait` that returns a message says on stderr that a body is data.
- `maity join` warns before the exchange when this machine already holds an identity on another hub, and `docs/agents.md` and the skill say to join only on your human's word.
