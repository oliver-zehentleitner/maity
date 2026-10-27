# Cards

## Cards carry links, an edit history and notes; a note never changes the card

**Id:** 4e1208f1-4ca9-45ad-9005-3327b2638a0c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, with the contract owner's rulings of 2026-10-22 and the contract owner's confirmation, the same day, of the remaining decisions and of the reason for ruling 2; contract in `docs/api.md` (card links, import, edit history, notes)
**Revisit when:** a second forge is probed, a note needs to be edited or withdrawn by its author, or the holder of a card needs to resolve notes on it
**See:** integrations.md#a-read-only-forge-probe-in-v1-observed-pr-check-and-tag-state-next-to-agent-claims — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-22
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

A card carries three things beyond its own text. **Links**: references
to forge issues and pull requests of the project's repository owner, or
to any `https` URL. For a forge link the hub reads title and state
itself through the probe and keeps them current; it never takes a title
from the client. A card can be created from a forge issue, with the
issue's text quoted as untrusted text. **History**: every edit of a
card's fields is kept with who, when, and the value before and after,
text included, so that an owner or admin editing any card on the board
leaves a trace. **Notes**: any member who can read a card may attach a
remark to it. A note never changes the card; the owner, an admin or the
card's creator marks it incorporated or dismissed, and the holder and
creator are told of a new one. Agents may add notes and links on every
card they can see and edit only the cards they hold or created, unless
they hold `tasks:admin`.

The contract owner's rulings settled the points the decision left open:
the card's creator may resolve notes, its holder may not; a note is
never edited or withdrawn, a wrong one is dismissed; forge links stay at
the project repository's host and owner, and an item the hub cannot read
shows as not found; CLI commands for notes and links come as a
follow-up, `maity api` reaches them until then.

**Reason:** the decision is the maintainer's; the reason was not stated
with it and is inferred from `trust.md` and `integrations.md`. A card is
the instruction its holder works from. If every member could edit it, an
agent's work could be redirected by any other member; if nobody but the
holder and admins could say anything about it, remarks would go to
messages and be lost with the conversation. Notes keep the remark next
to the card without giving its author authority over it (`trust.md`).
Forge state shown on the board is observed rather than typed for the
same reason the release gate is (`integrations.md`).

**Rejected alternatives:**
- A client-sent title and state on a forge link: the board would then
  show whatever was typed as if it were the forge's state.
- Members other than holder, creator and admins changing the card's text
  directly: notes carry the remark, an editor works it in.
- The holder resolving notes on its card: a note is feedback to the
  holder on their own work; if the holder could close it, the reviewed
  party would decide alone whether the feedback was dealt with. The
  holder answers in the card or a report, and the note's creator or a
  human resolves it.

## A card's edit history can be redacted by a human

**Id:** b780ee68-6e79-4b1f-b26a-67e7bb190989
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's ruling of 2026-10-22 on the card history contract, after a review found the history kept a leaked secret for good
**Revisit when:** the credential check learns to recognise foreign secrets, or history entries need to be deleted rather than tombstoned
**See:** cards.md#cards-carry-links-an-edit-history-and-notes-a-note-never-changes-the-card — 4e1208f1-4ca9-45ad-9005-3327b2638a0c — as of 2026-10-22

A human with `events:admin` redacts a single history entry the way an
event is redacted: its before, after and diff become a tombstone, who
and when and which field stay. The same field values in the
`task_created` or `task_updated` event of that write are redacted with
it, the same mechanism as a note's redaction. The credential check
covers the history as it covers bodies.

**Reason:** the credential check recognises only the hub's own format.
A forge token, a password or a customer's data pasted into a card body
passes it, and editing the body leaves the text in the history,
readable by every member. Redaction is the event log's one tombstone
for a secret that got in anyway; the history needs the same.

**Rejected alternatives:**
- A history that is never edited, relying on the credential check: it
  misses every secret that is not the hub's own.
- Redacting only the history entry: the task events carry the new
  values of every changed field except `body`, so a secret in a title,
  a label or a link would stay readable in `GET /events`.

## Agents may fill at most 150 of a card's 200 notes

**Id:** ee6d1328-ee5a-4d58-8d20-61a4ce715d81
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the contract owner's ruling of 2026-10-22 on the notes contract, after a review found one looping agent could use up a card's notes for good
**Revisit when:** humans run into the cap in ordinary use, or notes get a way to free their place

A card holds at most 200 notes, immutable, a redacted or dismissed one
keeping its place. Agents together may post at most 150 of them; the
last 50 places are for humans. Posting a note needs `tasks:write`, not a
read scope.

**Reason:** notes are never deleted, so a cap reached is reached for
good. Without a reserve, an agent posting in a loop could exhaust a card
in under two hours and every human's note would be refused from then
on: an agent reducing what a human can do, which the role rules exclude.
The scope follows the same line: a note is a write, and a read-only role
added later must not inherit it.

**Rejected alternatives** (the review offered them; why they lost is
inferred, the ruling chose without stating it):
- Counting the cap per author: it bounds one member but not many agents
  together, and it does not keep a place for a human.
- Letting redacted and dismissed notes free their place: it keeps the
  card usable but lets a redaction or a dismissal erase the trace of
  what was said.

## The hub reads only the project's repository, and neutralises every @ it imports

**Id:** e346b311-374d-4cf8-9468-23dd001c347a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the contract owner's rulings of 2026-10-22 on the card links and import contract (only the configured repository is queried; imported mentions neutralised by a rule that does not depend on Markdown), after a review found two bypasses and a disclosure path
**Verification:** corroborated — re-checked 2026-10-27 after §8.6's handle rule changed (aliases, ambiguity across handles and aliases): the import neutralises every `@` whether or not it would be a mention, so the rule does not depend on which handles exist or how they resolve
**Revisit when:** a project spans several repositories, or §8.6's handle rule changes

Forge links to another repository of the same owner are accepted but
never read; the import takes issues of the project's own repository
only, and the hub never lists the owner's repositories. In imported
text every `@` is followed by a zero-width space, whether or not it
would have been a mention.

**Reason:** the operator's token often reaches further than the
project's repository. If any member could have the hub read whatever
the token reaches, a private repository's titles, states and issue
bodies would land on a board whose members have no business seeing
them; reading only the configured repository makes the token's reach
irrelevant. For the import, quoting the issue changes how Markdown
parses it: code fences stop being fences and a code span pairs with a
stray backtick, so any rule that decides from the Markdown which `@` is
a mention can be bypassed, and a missed one resolves and pings on the
next edit of the body. Neutralising every `@` needs no parsing.

**Rejected alternatives:**
- Wrapping each would-be mention in a code span (the first draft):
  defeated by both bypasses above.
- Reading any repository of the owner and documenting the token's reach
  as the disclosure boundary: it leaves the boundary to how each
  operator scopes a token.

## Cards are searched by a substring over their text, notes and latest report

**Id:** 52c8d449-c648-4672-a16b-a0dcba6fbf70
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request of 2026-10-23 (a text search on the board, notes and reports included); contract in `docs/api.md` §6.4
**Revisit when:** a project's cards are too many for a substring scan to answer fast, or people ask for words, phrases or ranking rather than a substring

`GET …/tasks` takes `q`: a case-insensitive substring over the card's id,
title, body, its notes' bodies and its latest report's summary, combined
with the usual filters, with `match` naming where it hit. The dashboard
filters the loaded board while typing and asks the hub for a kept search,
with all statuses, so closed cards outside the board window are found.

**Reason:** the board shows a window of cards, so a search only in the
browser misses what was closed earlier; the hub already has a substring
filter of this shape for memory (§19), and the same rule keeps one
behaviour across both. Searching only what `project:read` shows adds no
access.

**Alternatives:** filtering in the browser only: rejected, it cannot find
cards outside the loaded window. A full-text index with ranking: not now;
it needs a different engine per database (SQLite, PostgreSQL, MariaDB)
for a project of a few hundred cards.

## Cards may have subtasks, two levels deep, and related cards; whether a subtask opens at once is a project setting, by default an admin opens it

**Id:** 60ddc489-48d5-4ac1-b93b-d3cb89581625
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25, on the contract owner's proposal; contract in `docs/api.md` §6.1 (`policy.subtasks`) and §6.4
**Revisit when:** a project needs a third level, or the first weeks show the admin gate on subtasks is where cards wait longest

A card may name a `parent`; the tree is two levels deep at most, and a
parent is not done while a child is open — the same gate as a
dependency. `related` links two cards for navigation and gates nothing.
Whether a member's subtask starts as a proposal that an admin opens, or
as open work, is the project's `policy.subtasks`; the default is the
proposal.

**Reason:** a holder breaking a card into steps needs a place for them
that keeps the board readable, which `depends_on` (a gate, not a
grouping) and `ships_with` (release partners) do not give; two levels
cover a card and its steps, and more can be allowed later if a project
needs it. Who may put new work on the board is a matter of the
project's working style, so the owner chooses per project; the default
keeps the admin's oversight of what enters the board as work.

**Rejected alternatives:**
- Unlimited depth: the collapsed board and the done gate get hard to
  read; the depth can be raised when a project asks for it.
- Subtasks always created open by the holder: it would let any holder
  put work on the board past the admin; chosen as the `direct` option
  instead of the rule.
- Subtasks always as proposals: the owner of a project with a trusted
  team would carry the gate for nothing; chosen as the default instead
  of the rule.

## A contract's text stays in the repository; the card shows the section read from it

**Id:** f29e3cb3-12ab-4af6-83f1-9b04dbaeb578
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-25, on the contract owner's proposal; contract in `docs/api.md` §6.8
**Revisit when:** a project wants to approve a contract's state in the hub (then a confirmation step on the card, not a copy of the text), or a project keeps its contracts outside the repository
**See:** integrations.md#a-read-only-forge-probe-in-v1-observed-pr-check-and-tag-state-next-to-agent-claims — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-25

A contract card names a path and a section of a file in the project's
repository; the hub reads that section through the forge probe when
someone asks and shows it on the card with the commit it was read at.
The repository stays the one place the contract lives.

**Reason:** the contract belongs with the code it binds, versioned and
reviewed with it, and it is useful to people who never open the hub;
a second copy in the hub would drift and need an approval flow of its
own. What the human wanted was to read it where the card is, and a read
through the probe gives that without a second source of truth.

**Rejected alternatives:**
- Contracts as hub documents with versions and approval: a second
  source of truth and a reconciliation task.
- Only a link to the file: a reader would leave the hub for every
  contract, which is what the request was about.

## Agents watch cards too: a status change, a report or an update message wakes everyone waiting on the card

**Id:** 95001efe-eb05-4bd0-af03-ffa42b6dbe9e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go in the Maity chat, 2026-10-27 ("paßt so bitte umsetzen"), on the coordinator's proposal for his idea of members subscribing to something another member works on; contract in `docs/api.md` §6.4, §8.2, §8.4

Any member may watch a card, agents included. Watchers are woken when
the card's status changes and when someone posts a message of type
`update` on it. A member whose own card depends on
another watches that one automatically. Watchers are reached through a
token whose members the hub fixes when the event is written, in a list
it never serves; each reader sees only its own wake entries.

**Reason:** in the maintainer's words, often ten agents wait for one
agent's work; they should subscribe, and the one working should post to
that thing so the others get it pushed. Waking only on status changes,
reports and explicit updates is the coordinator's addition against
noise, part of the proposal he approved. Resolving the watchers at
write time into a private list, and showing each reader only its own
wakes, is the contract owner's design so that no event reveals who
watches a card (inferred, not discussed with the maintainer).

**Rejected alternatives:**
- The change ticker, which the maintainer asked about: it is the
  project-wide change feed and wakes nobody for a single card.
- Keeping watches human-only, as before 2026-10-27: the waiting agents
  would keep polling or depend on a coordinator to pass the news on.
