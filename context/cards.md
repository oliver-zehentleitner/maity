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
**Source:** the maintainer's wish in the Maity chat, 2026-11-02, that the overview link the contract and better show it rendered inside Maity (card tsk-yhbmz7mjng7n); the coordinator's go the same day for the implementer to write the contract; the arbiter's ruling on #1235, 2026-11-02; the contract review of #1235 and the arbiter's ruling on its findings the same day (Markdown only, `private, no-cache`, the repository in the `ETag`), and the arbiter's rulings on the delta reviews the same day (a symlink refused, told by the tree's mode, each directory's tree read and the check failing closed); contract in `docs/api.md` §6.8, §6.1, §6.11, §16.11
**Revisit when:** a project's contract outgrows 4 MiB, or a project keeps its contract in more than one file
**See:** cards.md#a-contracts-text-stays-in-the-repository-the-card-shows-the-section-read-from-it — f29e3cb3-12ab-4af6-83f1-9b04dbaeb578 — as of 2026-11-02

The overview links the project's contract and shows it in a view of its
own, read-only: the hub reads the file a project setting names
(`settings.contract_path`, default `docs/api.md`) through the probe at
the default branch's commit and answers it whole, with a table of
contents and an anchor per heading, under an `ETag` over the
repository, the path and the file's bytes. The setting names a Markdown
file only (`not_markdown` otherwise, the extension in any case), which
keeps it from exposing arbitrary repository files to every
`project:read` holder, guests included; a symlink is refused too, since
the name says nothing about the file it points to: the hub reads the
non-recursive tree of each directory on the path at the commit, every
segment must be listed as a directory (`040000`) or, last, a regular
file (`100644`, `100755`), and anything else, a missing entry or a
truncated tree included, is `not_markdown`: the check fails closed. The
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
  lists nothing under `scripts/`), so a symlink there would pass; the
  directory's own tree is never truncated, and a missing entry fails
  closed.
- `no-store` like the other API answers: every tab and reload would
  read the whole file again, so the load would grow with tabs.

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

**Reason:** a reason often names exactly what was sensitive ("contained
a password"), and notes of a public project are public; one rule for
every redaction is easier to keep right than a second, looser one.

**Rejected alternatives:**
- The reason visible to every reader of the note: it would publish the
  description of what was removed, and set notes apart from every other
  redaction (§8.5).
