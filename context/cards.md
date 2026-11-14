# Cards

## Cards carry links, an edit history and notes; a note never changes the card

**Id:** 4e1208f1-4ca9-45ad-9005-3327b2638a0c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, with the contract owner's rulings of 2026-10-22 and the contract owner's confirmation, the same day, of the remaining decisions and of the reason for ruling 2; contract in `docs/api.md` (card links, import, edit history, notes)
**Revisit when:** a second forge is probed, or the holder of a card needs to resolve notes on it
**See:** integrations.md#a-read-only-forge-probe-in-v1-observed-pr-check-and-tag-state-next-to-agent-claims — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-22
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22
**See:** cards.md#a-notes-author-edits-it-in-place-and-the-hub-keeps-no-trace-of-the-old-text — 0e6b3b31-1656-4744-841d-d48f1899a7fd — as of 2026-11-02

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
never edited or withdrawn, a wrong one is dismissed (replaced on
2026-11-02: its author edits it, entry 0e6b3b31); forge links stay at
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

## The whole contract is read inside Maity from a project setting, whole or not at all

**Id:** 7f6ed086-6faf-44f1-81d8-c25ffaa4011a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish in the Maity chat, 2026-11-02, that the overview link the contract and better show it rendered inside Maity (card tsk-yhbmz7mjng7n); the coordinator's go the same day for the implementer to write the contract; the arbiter's ruling on #1235, 2026-11-02; the contract review of #1235 and the arbiter's ruling on its findings the same day (Markdown only, `private, no-cache`, the repository in the `ETag`), and the arbiter's rulings on the delta reviews the same day (a symlink refused, told by the tree's mode, each directory's tree read and the check failing closed, a missing segment `not_found_on_forge`); contract in `docs/api.md` §6.8, §6.1, §6.11, §16.11
**Revisit when:** a project's contract outgrows 4 MiB, or a project keeps its contract in more than one file
**See:** cards.md#a-contracts-text-stays-in-the-repository-the-card-shows-the-section-read-from-it — f29e3cb3-12ab-4af6-83f1-9b04dbaeb578 — as of 2026-11-02

The overview links the project's contract and shows it in a view of its
own, read-only: the hub reads the file a project setting names
(`settings.contract_path`, default `docs/api.md`) through the probe at
the default branch's commit and answers it whole, with a table of
contents and an anchor per heading, under an `ETag` over the
repository, the path and the file's bytes. The setting names a Markdown
file only (`not_markdown` otherwise; the extension is checked in any
case, while every path segment must match byte for byte), which
keeps it from exposing arbitrary repository files to every
`project:read` holder, guests included; a symlink is refused too, since
the name says nothing about the file it points to: the hub reads the
non-recursive tree of each directory on the path at the commit, every
segment must be listed under exactly its name as a directory (`040000`)
or, last, a regular file (`100644`, `100755`); a tree answered with
`truncated: true` is `not_markdown` before any segment is looked up in
it, a segment missing from a complete tree is `not_found_on_forge`, as
for any file not there at the commit, and any other mode is
`not_markdown`: the check fails closed. The
tree of a commit never changes, so it is cached per commit SHA and
directory. The file cap for this read and for a card's section is
4 MiB instead of 1 MiB; a larger file is refused, never cut.

**Reason:** a setting is the one place that says which file is the
contract when no card names one. The whole file in one answer keeps the browser's search
over the entire contract and costs one read, which the `ETag` makes
cheap to repeat while the file does not change. The cap moved because
this project's own contract passed 1 MiB on 2026-11-02, so a card's
section read already refused it; cutting instead would show part of a
contract as if it were all of it. The answer is `private, no-cache`, as
attachments are, so a new tab or a reload revalidates instead of
reading up to 4 MiB again; after a `304` the view keeps the `ref`,
`url` and `fetched_at` of the last full answer.

**Rejected alternatives:**
- The table of contents plus one section per request: smaller answers,
  but no search across the contract, and every jump a new read.
- The first of `ticker.contract_files` as the file: ties the view to an
  opt-in ticker and to a list whose order means nothing.
- The file taken from the contract cards' `path`: no card, no contract;
  several paths, no answer.
- The 1 MiB cap kept, with the text cut: a cut contract reads as whole.
- Any file of the repository as the contract: the whole-file read shows
  everything, unlike a card's section, which shows only Markdown under a
  matching heading; so the setting names a Markdown file (`.md`,
  `.markdown`), lest a committed secret reach every `project:read`
  holder, guests included.
- The name rule alone: a committed symlink `x.md` to a non-Markdown
  file resolves on the forge to the target's bytes, so the hub refuses a
  symlink (`not_markdown`) instead of trusting the name.
- Comparing the answer's `path` with the setting to catch a symlink:
  GitHub's contents answer names the requested path, not the target's,
  so the comparison never fires there.
- Comparing the Git blob hash of the bytes with the answer's `sha`: the
  raw form that §6.8 prescribes above 1 MB carries no `sha`, so large
  files would slip through, and the hash only infers what the tree's
  mode states directly.
- One read of the recursive tree, a missing entry taken as no symlink:
  GitHub truncates that tree for a large repository (torvalds/linux
  lists nothing under `scripts/`), so a symlink there would pass; each
  directory's own tree is read instead, and one answered truncated fails
  closed.
- A missing segment as `not_markdown`: a complete directory tree lists
  every entry, so a missing one means the file is not there, which the
  read already answers with `not_found_on_forge`; two codes for one case
  would depend on the order of the reads, and the file may appear later,
  which that code says. Nothing is shown either way.
- `no-store` like the other API answers: every tab and reload would
  read the whole file again, so the load would grow with tabs.

## A large contract file is read as JSON first, and raw only when the forge leaves the content out

**Id:** bb11fd25-ec47-47ca-923d-063b0beafd0e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub change of tsk-zd9es4kp51w1 (#1261), `Forge.file_at` in `hub/src/maity_hub/forge.py`; the review of #1261 and the coordinator's go for this entry, 2026-11-03; contract in `docs/api.md` §6.8 "The cap", §11.1
**Verification:** corroborated — GitHub's contents API answered `docs/api.md` (1253728 bytes) with `encoding: none` and empty content, and the raw media type with the bytes and no redirect, 2026-11-03
**See:** cards.md#the-whole-contract-is-read-inside-maity-from-a-project-setting-whole-or-not-at-all — 7f6ed086-6faf-44f1-81d8-c25ffaa4011a — as of 2026-11-03

The hub asks the contents API for JSON first. Only when the answer is a
file with `encoding: none` and a `size` within the cap does it ask again
in the raw media type, reading at most cap + 1 bytes, so a file over the
cap is told apart without the forge sending the rest. The raw read takes
the same route as every read (`_get`, `_call`), so the visibility check
and the grant binding hold for it too.

**Reason:** the JSON answer says what the path is (`type`) and how large
(`size`) before any byte of the file is read; the raw form says neither,
and §6.8 counts the cap in bytes read.

**Rejected alternatives:**
- Always the raw form, one request fewer: no `type` and no `size` up
  front, so the cap would rest only on the cut read.
- A separate raw reader beside `_get`: a second route to the forge that
  could skip the visibility check and the grant binding.

## Agents watch cards too: a status change or an update message wakes everyone waiting on the card

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
that thing so the others get it pushed. Waking only on status changes and
explicit updates is the coordinator's addition against
noise, part of the proposal he approved. Resolving the watchers at
write time into a private list, and showing each reader only its own
wakes, is the contract owner's design so that no event reveals who
watches a card (inferred, not discussed with the maintainer).

**Rejected alternatives:**
- The change ticker, which the maintainer asked about: it is the
  project-wide change feed and wakes nobody for a single card.
- Keeping watches human-only, as before 2026-10-27: the waiting agents
  would keep polling or depend on a coordinator to pass the news on.

## A note's author edits it in place, and the hub keeps no trace of the old text

**Id:** 0e6b3b31-1656-4744-841d-d48f1899a7fd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision of 2026-11-02 on the card for editing a note (five points: who, no history, reason, updates, redaction stays); the coordinator's rulings the same day on the creator in the audience, closed cards, redacted notes and the reason's readers; contract in `docs/api.md` §6.16, §8, §8.6
**Revisit when:** someone needs to see what a note said before an edit, or agents need to correct other members' notes
**See:** cards.md#cards-carry-links-an-edit-history-and-notes-a-note-never-changes-the-card — 4e1208f1-4ca9-45ad-9005-3327b2638a0c — as of 2026-11-02
**See:** cards.md#a-cards-edit-history-can-be-redacted-by-a-human — b780ee68-6e79-4b1f-b26a-67e7bb190989 — as of 2026-11-02

A note is edited in place (`PATCH …/notes/{note_id}`). Its author edits
their own, human or agent; a human with `events:admin` edits any note of
the project, and must give a reason, shown with the edit mark to every
reader; an agent never edits another member's note. The hub keeps no
earlier version: the new text replaces the old one on the note and in
every event that carried the note, rewritten in place the way a
redaction rewrites them, so what stays is the new text and "edited by X
at T". What a client already received stays with it, and a mail
already sent is beyond reach. The edit reaches everyone involved in an
open card (author, holder, creator, everyone with a note on it, the
mentions computed again) and wakes as a new note does; on a done or
cancelled card it reaches the author and the newly mentioned only. A redacted note is not edited, and redaction
stays the way to remove a note as a whole.

This replaces the ruling of 2026-10-22 that a note is never edited or
withdrawn and a wrong one is dismissed (entry 4e1208f1).

**Reason:** in the maintainer's framing, the point of the feature is to
remove what should not have been written, sensitive data included; a
kept version would keep exactly that. Dismissing a wrong note leaves its
text readable, and redaction needs a human with `events:admin`, so an
agent or a member could not correct a typo or a pasted secret in their
own note. Keeping the author as the one who edits, and agents away from
others' notes, follows the rule that a remark gives its author no
authority over anyone else's words (`trust.md`). An edit on an open card reaches
everyone it mentions, not only the newly mentioned as a card body does
(§8.6): the maintainer listed the mentioned among those involved, and a
correction of a remark changes what each of them was told, while a card
body's mention is a call to act that a re-save should not repeat
(inferred from the two rules side by side; the decision itself and
the purpose above are confirmed). A redaction drops the edit
mark with the text, since an edit's reason speaks of the old text.

**Rejected alternatives:**
- Keeping a version history of a note, readable by admins or by
  everyone: the old text, a secret included, would stay readable, which
  is what the edit is for removing; the card history keeps before and
  after because a card is an instruction others work from, a note is
  not.
- Redacting and posting a new note: it needs `events:admin`, loses the
  note's place and state, and leaves a tombstone where a correction was
  meant.
- Waking only the newly mentioned on an open card, as for a card body:
  those mentioned before would keep a stale picture of a remark that
  was addressed to them.
- Letting agents with `tasks:admin` edit any note: an agent could
  rewrite a human's or another agent's remark; a correction of someone
  else's words stays with a human who answers for it with a reason.

## Editing or redacting a note names the version it was made on

**Id:** 23165436-966c-48d6-94f4-80ea0638abf6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** a review finding on the web pull request for editing a note (#1227), and the coordinator's ruling as contract arbiter on card tsk-b6wb439f88nr (2026-11-02): a precondition on editing and removing a note, the details left to the contract pull request; contract `docs/api.md` §6.16 "Precondition"
**Revisit when:** the API takes conditional request headers (`If-Match`, ETags) elsewhere, or notes gain a kept history
**See:** cards.md#a-notes-author-edits-it-in-place-and-the-hub-keeps-no-trace-of-the-old-text — 0e6b3b31-1656-4744-841d-d48f1899a7fd — as of 2026-11-02

A note carries a `version`, 1 when posted and one more with each edit
and with its redaction. An edit (`PATCH …/notes/{note_id}`) and a
redaction send it as `base_version`, always; a stale one is `conflict`
with the note as it is now, and nothing changes.

**Reason:** without it, an admin who edits a note to take out sensitive
text while the author has the card open loses that edit when the author
saves: the author's older text comes back, and since the hub keeps no
history (entry 0e6b3b31) nobody sees that it happened. Reading the note
again before editing narrows the window but leaves the race between
reading and saving. The precondition itself is the arbiter's ruling
(confirmed); the shape below was settled in the contract pull request
(inferred): a body field named `base_version` and `conflict` with
`current_version` are how the contract already guards a soul and a
human's preferences against the same lost update (§19.1, §19.4), so
clients and the CLI handle one pattern. Required, because the overwrite
happens exactly in the client that sends nothing; no client on main
edits notes yet, so nothing breaks. The redaction takes it too, so that
an admin never removes a text it has not seen.

**Rejected alternatives:**
- `If-Match` with an ETag and `412 Precondition Failed`: the API uses no
  conditional headers anywhere, and a second way to say the same thing
  would serve no client better.
- An optional `base_version`: a client that leaves it out is exactly
  the one that overwrites; the hub could not tell a careful client from
  a careless one.
- Comparing `edited.at` or the old body instead of a counter: a
  timestamp can repeat within its resolution, and sending the old body
  back would carry the very text an edit may be removing.
- Only the web reading the note again before saving: leaves the race
  between the read and the write.

## A redacted note's reason reaches only the owners, the admins and the redactor

**Id:** 09c47db5-75b7-4636-8c49-0cc46c8c9d46
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling as contract arbiter, 2026-11-02, on a question two members raised while building the dashboard's tombstone, confirmed by the maintainer the same day ("nicht jedem anzeigen"); contract in `docs/api.md` §6.16, §8.5
**Revisit when:** a project wants the readers of a card to learn why a note was removed
**See:** cards.md#a-notes-author-edits-it-in-place-and-the-hub-keeps-no-trace-of-the-old-text — 0e6b3b31-1656-4744-841d-d48f1899a7fd — as of 2026-11-02

A redacted note follows the event rule of §8.5: the reason of the
redaction reaches the human owners and admins and the one who redacted;
every other reader, agents included, sees the tombstone with who and
when and `reason: null`. That holds for the note in the API and for the
note inside the `note_added` and `note_edited` events that carried it,
which the hub shapes per reader when it serves them. The public card
page already shows a redacted note as removed, without a reason.

A redacted card history entry follows the same rule (tsk-dd14yts44h1f):
in the history, in the redaction's answer, in the field values of the
`task_created` or `task_updated` event of its write, and in a link the
hub answers from the entry. A replayed `Idempotency-Key` loads the entry
with the caller's membership as it is at the replay, so it shows what
the caller's own read of the history shows then.

**Reason:** a reason often names exactly what was sensitive ("contained
a password"), and notes of a public project are public; one rule for
every redaction is easier to keep right than a second, looser one.

**Rejected alternatives:**
- The reason visible to every reader of the note: it would publish the
  description of what was removed, and set notes apart from every other
  redaction (§8.5).

## A card's restricted text is read only by a set the project names, closed by default; access control, not encryption

**Id:** b5b1218b-e4e1-422e-86cb-ef5d41c9a4d9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request of 2026-11-04 (card tsk-g8ts5vxhj1md); the coordinator's rulings the same day on the contract draft and on the review findings of its pull request (#1380), each review round; contract in `docs/api.md` §6.1 "Restricted access", §6.4 "Restricted text"
**Revisit when:** the text must stay unreadable to the instance's operators, an owner or admin needs to read every text without entering the set, or the hub learns which instance of an agent acts
**See:** cards.md#cards-carry-links-an-edit-history-and-notes-a-note-never-changes-the-card — 4e1208f1-4ca9-45ad-9005-3327b2638a0c — as of 2026-11-04

A card may carry one small plain-text value outside every card field,
read and written only by the members of a set the project names in
`settings.restricted_access` (`nobody_except` or `all_except` a list).
Without the setting nobody is in the set, owners and admins included;
a human with `project:admin` and a step-up changes it, the hub's own
narrowing on an owner change excepted. The set is per
membership, never per instance. Under `all_except` an agent is in it
only while its owner is, and every way into the set (the setting, a
join — the memberships the hub makes for an organisation's owners
included — a guest raised, an isolation ended, an agent's owner changed)
tells the set with a `restricted_changed` event. Under `nobody_except`
there is no owner gate, so whoever controls a listed agent reads
through it; a listed agent whose owner changes leaves the list, and an
admin lists it again. The list is otherwise never pruned. The routes
answer `Cache-Control: no-store` and the dashboard keeps the text in
memory only. Writes are capped per membership and, for `PUT`, per
card; a `DELETE` is never held by the card's cap. Notifications are
capped at one per card and human, and one for the set per human and
project, in 10 minutes. A person's export carries only the texts whose
current version they wrote, of projects whose set they are in.

**Reason:** the request was a place on a card for what not every member
may read. Closed by default means no existing project changes what
anyone reads when the feature arrives. The hub stores the text as other
project data and limits who reads it; it does not claim more, and the
dashboard says so, because an admin can add themselves, the operators
hold the data and an agent passes what it reads to its owner and its
model provider. An instance has no identity the trust model rests on,
a membership does. Under `all_except` an agent that read without its
owner would let a human left out read through a new agent of their
own, and a set that grows without a change of the setting would grow
unseen without the event. A pruned list would let a removed member
excluded under `all_except` back in when it joins again. The see-all
of owners and admins would tell them which cards have a text and who
changes it, which is what the set keeps to itself. An export of texts
others wrote, or of a project whose set one left, would carry them out
of the hub past the set. An agent's owner change is a way in like the
others: under `all_except` it can bring an agent in with no change of
the setting, so it is told the same way. Under `nobody_except` the
admin confirmed the agent with the owner it had, and the new owner
would read through it unconfirmed; taking it off the list keeps the
set closed by default, and only narrows, so it does not bring back
what pruning risks under `all_except`. The memberships the hub makes
or raises for an organisation's owners are joins and trust raises like
any other: under `all_except` they bring a human, and their agents that
are not guests, isolated or listed, into the set with no change of the setting. A `left` is written only for an agent that was
in the set: one that was not has left nothing, and the list change is
told by `project_updated` either way. A browser cache, storage or
history outlives the session and the set: a member taken out of the
set, or the next person at a shared machine, would still find the
text, so nothing is kept outside the page's memory. The write caps
keep a member in the set — an agent in a loop above all — from
filling the history, the events and the notifications; the card's cap
keeps many members from doing that on one card. A shared card cap
counting `DELETE` would let one looping member block for up to an
hour everyone's clearing of a text pasted by mistake, which is the
write that most needs to go through; a `DELETE` changes at most once
per text, so leaving it to the membership's cap costs little. The
10-minute notification caps keep a burst of edits, or of members
entering, from becoming a burst of mail and push; the events stay
readable, so suppressing the further notices loses nothing that the
set cannot see.

**Rejected alternatives:**
- Encrypting the text: the hub, its operators and every agent in the
  set would still hold the key or the plain text, so it would promise
  a protection it cannot keep.
- Open by default, or owners and admins always in the set: every
  existing project would change who reads the moment the feature
  arrives, and the set could not leave an owner out.
- A set of instances: an instance is a session of a membership, with
  no standing of its own in the trust model.
- Under `all_except`, agents in the set whatever their owner, or
  telling the set nothing when it grows without a change of the
  setting: a human left out could read through their own new agent,
  and the set would not learn who reads with it.
- Pruning the list when a member leaves: a member left out under
  `all_except` would be in the set when it joins again.
- The owners' and admins' see-all over its events, or a see-all view
  of the texts: it would show outside the set which cards carry a text.
- Exporting every text the person can read: the export would carry
  texts out of the hub that others wrote or the person may no longer
  read.
- Under `nobody_except`, a listed agent staying in the set when its
  owner changes, with only an event to the set: its new owner would
  read until an admin acts. Keeping the owner each agent was listed
  with and checking it on every call: a second state to store and
  show, for the same outcome as taking the id off the list.
- A `left` on every owner change of a listed agent, in the set or not:
  it would tell the set of a member leaving that never read with it.
- An owner gate under `nobody_except` as under `all_except`: there the
  admin names each agent on purpose, and the gate would make listing
  an agent of an owner who is not listed pointless; the contract says
  instead that whoever controls a listed agent reads through it.
- Ordinary caching, or keeping the text in the browser for speed or
  offline use: the copy would outlive the set and the session.
- No write caps, or a cap per membership only: a looping agent, or
  several members on one card, could flood the history, the events and
  every human's notifications.
- `DELETE` under the card's cap: one looping member could keep
  everyone from clearing a text pasted by mistake.
- A notification for every change, or a digest instead of dropping the
  further ones within 10 minutes: every change would be a mail or a
  push, and a digest would be a second kind of notice to build and
  keep for what the events already show.
