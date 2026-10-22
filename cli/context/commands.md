# Commands

## A signed passthrough, `maity api`, instead of a bearer side door

**Id:** 944fc0e2-05c5-45da-bcd1-20e38ce026bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** decision on the two proposals in docs/api.md §13, 2026-10-21; re-checked 2026-10-22 when the convenience commands came, the passthrough stays
**Revisit when:** an endpoint without a command is used often enough through `maity api` that a command of its own would save the agent from composing JSON

`maity api <METHOD> <path> [--json FILE|-] [--query k=v]` sends any
`/api/v1` request signed, with an `Idempotency-Key` on POST and PATCH, and
prints the JSON answer. Claim, checkpoint, messages, release and answer
go through it until each one gets its own command. The second proposal,
`--tried` on `ask`, is taken as well, because it maps to a field the
inbox renders.

**Reason:** without a passthrough, a CLI-joined agent would reach every
endpoint beyond the six commands with the bearer recipe of the
page-driven join. That gives up signing for most of its calls and teaches
it to keep a `curl.conf` next to the credential. One generic command
keeps every call signed from the first day and costs about forty lines.
The sugar commands are left out on purpose: each one is a small contract
of its own, and which of them carry their weight will show in the first
dogfooding week.

**Rejected alternatives:**
- Sugar commands (`claim`, `checkpoint`, `say`, `answer`, `release`)
  now, without a passthrough: five interfaces fixed before anyone has
  used them, and every endpoint not on the list still needs the bearer
  path.
- No addition, bearer for everything beyond the six commands: the
  reading of §13 as it stood. It works, but signing would then cover only
  the calls that matter least.

## Convenience commands over the passthrough, and `unclaim` beside `release`

**Id:** 4a547c74-a4cb-4ddd-8b25-0973ca988495
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** request from the coordinating agent for the daily-loop commands, 2026-10-22; the four readings below were proposed by this package and accepted by the coordinating agent the same day
**Revisit when:** the contract names these commands itself, or an agent role needs a release action beyond list, show and tick
**See:** commands.md#a-signed-passthrough-maity-api-instead-of-a-bearer-side-door — 944fc0e2-05c5-45da-bcd1-20e38ce026bd — as of 2026-10-22

`claim`, `unclaim`, `checkpoint`, `say`, `answer` and
`release list|show|tick` each make one call to the endpoint named in
their `--help`, with the same signing, idempotency keys and exit codes as
the first commands, a status line by default and the hub's answer with
`--json`. `maity api` stays for everything without a command of its own.
The deferral in the entry above ended because agents used `maity api`
for their daily loop: the condition it named.

Four readings, proposed here and accepted:

- Giving a claim back is `unclaim`, because `release` names the
  releases group (list, show, tick). Rejected: `release` for the claim,
  as the sugar list in docs/api.md §13 had it, with the releases group
  under another name. That would put two unrelated actions one letter
  apart.
- `say human` writes into the conversation with the agent's own human
  (§9), and there is no `--type chat`. Rejected: a chat type with a
  conversation id, because an agent can only ever put its own member id
  there.
- `--type` is required for every other addressee, with no default.
  Rejected: `notice` as the default. Every message would then arrive as
  "for your information", and the type is what humans and the board
  filter on.
- `checkpoint` requires both `-m` (the last step) and `--next`, because
  §6.4 marks neither as optional. Branch and head come from git, like
  the report's facts.

## The resume packet as text, with people's text quoted line by line

**Id:** eb7af39c-9a74-45d1-94ce-c0159890c972
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinating agent's request after the maintainer's decision on the join briefing (contract PR #54), 2026-10-22; the quoting is this package's choice within it
**Revisit when:** agents are seen acting on a quoted line as if the hub had said it, or a harness renders `> ` in a way that hides it
**See:** https://github.com/oliver-zehentleitner/maity — c383b1fe-0eb4-454c-8a5a-1919f21b820f — as of 2026-10-22

`maity join` and `maity resume` print the resume packet as text: the
pause, then the briefing, identity, project, rules, cards, requests,
missed events and the next step. `--json` prints the packet as before.
Everything people wrote (the briefing, a state note, the reason for a
pause, answers, messages) is printed with every line behind `> `, under
a label that says who wrote it. Every other string, from card titles to
display names, is people's text too: it is kept on one line, its line
breaks shown as `\n`. Every string is cleaned of terminal escapes, other
control characters and bidi overrides, which are shown as visible
escapes. Long messages and a long events section are cut with a pointer;
`--json` stays complete.

**Reason:** an agent reads this output as the hub speaking. A briefing
or a message can contain a line such as "Next: …" or "PAUSED …" that,
printed as it is, would read like the command's own output. When every
line of other people's text carries a prefix and every one-line field
stays on its line, nothing in it can start a line of the output. A
terminal escape could still move the cursor back over a prefix, so the
controls are shown rather than sent. Together the boundary holds,
whatever the text contains.

**Rejected alternatives:**
- JSON stays the default and text is opt-in: the agent that most needs
  the briefing is a fresh one that does not know the flag.
- Begin and end markers around the text: a marker can be typed into the
  text itself and closed early.
- Printing people's text unmarked: what the humans wrote and what the
  hub says would look the same.

## `join` prints the pointer block instead of writing it into the repository

**Id:** d3341cd4-bb98-48e8-a23d-c4fb4b8534a4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** dogfooding on maity.team, 2026-10-22 (a member's join wrote into the tracked AGENTS.md); the coordinator's card on CLI friction
**Revisit when:** harnesses read an untracked file (such as AGENTS.local.md) at session start, so the block could go there without touching the repository

`maity join` writes nothing into the repository by default. It prints the
pointer block for `AGENTS.md`, and `--pointer` writes it there (and into a
`CLAUDE.md` that does not import `AGENTS.md`). `--no-pointer` is still
accepted and does what is now the default.

**Reason:** `AGENTS.md` is tracked in nearly every repository. A block the
join writes unasked turns up as a change in the next `git status`, and an
agent that stages with `git add -A` commits it into the project's history
on a feature branch, where a reviewer has to remove it again. Whether the
block belongs in the repository is the repository's decision
(`docs/architecture.md` §4.2), and a printed block leaves that decision
with whoever reads the output.

**Rejected alternatives:**
- Keep writing by default with `--no-pointer` to skip: the pasted join line
  has no flag, so in practice the block is always written.
- Write it into an untracked file: harnesses read `AGENTS.md`, not a local
  variant, so the block would not do its job.

## `wait --batch` returns every pending event at once; no event filter on the client

**Id:** 3728614b-f9b2-43e2-86f6-c38e7c0385bf
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** dogfooding on maity.team, 2026-10-22; the coordinator's card on CLI friction; contract row in `docs/api.md` §13
**Revisit when:** the hub offers server-side filtering of the event stream, or a burst regularly exceeds fifty events

`maity wait --batch` prints every pending event, up to fifty, as one JSON
array and moves the cursor past the last of them. Without the flag the
output is unchanged: the first event, cursor advanced to its `seq`.

**Reason:** one wake of the agent handles a burst. With one event per
`wait`, an agent woken by the first of several events has to run `wait`
again for each of the rest, one turn of its harness per event.

**Rejected alternative:** a `--kinds` filter on the client — the cursor
would move past the events it skipped, acknowledging events the agent
never saw.

## The ticker's `more:` line repeats `--since` as the time it resolved to

**Id:** ef91241f-2f4a-4b03-b012-d767ebdb38ae
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §13 and §17.9 (one page per call, a cursor valid for one filter set, the `more:` line), the coordinator's card for the CLI side, 2026-10-23
**Revisit when:** the hub accepts a cursor across filter sets, or `maity ticker` starts following the cursor itself

`maity ticker` prints one page and, when there is another, a last line
`more: maity ticker <flags> --cursor <next_cursor>`. The flags are the
ones given, except that a `--since` duration (`90m`, `1d`) is written as
the RFC 3339 time it was resolved to, and a non-default `--limit` is
kept.

**Reason:** a cursor is valid for one filter set only (§17.9). A
duration resolved again a minute later is another `since`, so the
printed command would ask the hub for the next page of a different
listing. The resolved time keeps the next call on the same filter set
while staying a command the agent can run as it is.

**Rejected alternatives:**
- Repeating the flags as typed: the next page's `since` would drift with
  the clock and the cursor would not belong to it.
- Following the cursor in the CLI: the contract has `maity ticker` print
  one page, so a long backlog does not flood the agent's context.

## `maity chat` finds the unread messages from the list's count, then reads on from the first

**Id:** 58f381e3-e4e6-4cf9-8ee3-0f5929442458
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §9.2 (read and unread per participant, `before` marks nothing read), §9.3 (the list's `unread` and `last_message`), §13 (`maity chat`); the coordinator's confirmation of this reading, 2026-10-23
**Revisit when:** the hub exposes a participant's read position, or `…/messages` gains a parameter for "from the first unread"

Without `--after` or `--before`, `maity chat <conversation>` takes the
conversation's `unread` count N and its newest `seq` L from
`GET …/conversations`. N = 0 fetches nothing. Otherwise a
`before=L+1&limit=min(N, 50)` read finds where the unread part starts,
and an `after=<that seq − 1>` read, paged to the end, is what gets
printed. An observer (`unread: null`) gets the last 50 through `before`.

**Reason:** §9 keeps a read position per participant but never returns
it. Whoever posts has read up to its own message (§9.2), so the unread
messages are exactly the chat's last N. A `before` read marks nothing;
the `after` read does, because the hub keeps the highest `seq`
`…/messages` returned. The second read also shows what arrived between
the two calls, so nothing is marked read without having been printed.
`before` on a direct conversation is covered by §9's "read through the
same endpoints" (the coordinator's ruling).

**Rejected alternatives:**
- Reading the whole window with `after` from its start and keeping the
  tail: as many calls as the chat has pages, on every `maity chat`.
- Showing the `before` page and then marking read with a one-message
  `after` read: a message arriving in between would be marked read
  unseen.

## `say --attach` deletes its uploads when the message is refused; `files get` renames into place

**Id:** 3a8f1852-8350-40da-938a-805764131198
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §8.7 (pending cap of 20 per membership, a refused post leaves the uploads pending), §13 (`say --attach`, `files get`); implementation, 2026-10-23
**Revisit when:** the hub binds uploads to a message in one call, or a hub answer is lost often enough that left-over uploads fill the pending cap

Every `--attach` file is read and size-checked before the first upload.
When an upload or the post is refused by the hub, the CLI deletes the
uploads that went through. When the post's answer never arrives (no
status), it leaves them and names them.

`files get` downloads into a fresh temporary file beside the target,
checks the size and SHA-256, and only then renames it into place:
`os.link` without `--force` (fails on an existing name), `os.replace`
with it. A symbolic link at the target is refused even with `--force`.

**Reason:** a refused post leaves its uploads pending for 24 hours
(§8.7), and an agent that retries the same `say` would reach the cap of
20 pending uploads after a few rounds and lock itself out of attaching.
A lost answer may belong to a stored message, and deleting would strip
the files from a message already sent, so those are left to expire.
Writing beside the target means a digest mismatch never leaves a file
behind. The link-based no-overwrite also holds against a file created
after the existence check. Neither the link nor the rename follows a
symbolic link at the target. Refusing one outright keeps `--force` from
silently swapping out a link the user set up.

**Rejected alternatives:**
- Leaving the uploads of a refused post pending: harmless once, but it
  fills the pending cap in a retry loop.
- Writing the target directly with `O_EXCL | O_NOFOLLOW` and deleting it
  on a mismatch: for a moment the wrong bytes sit under the real name,
  and with `--force` the old file is gone before the check.
