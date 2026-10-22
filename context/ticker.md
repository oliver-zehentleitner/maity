# Ticker

## A change ticker announces merges, contract changes, decisions, deploys and releases; the hub computes who it concerns, and only they are woken

**Id:** adf83367-00aa-4fb1-bac1-1531dd0d3f88
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision via the inbox, 2026-10-22; contract in `docs/api.md` §17
**Revisit when:** agents report being woken by ticker items that do not concern them, or members mute the ticker wholesale; or a second forge needs its own merge source

Every merge into the default branch, every change to the API contract,
every decision taken in the inbox, every deploy and every release
becomes one short announcement in the project — a sentence of at most
280 characters and a link. The hub computes who it concerns: the owners
of the areas a merge touched and the holders of the cards linked to it;
for a change to the contract, the implementers of the sections it
touched and the admins; for a decision, whoever implements it; for a
deploy or a release, every member. Merges are learned from the forge
probe, or from a forge webhook that only tells the hub to look. Every
member can read every item (decisions only within the request's read
rule); an agent is woken by `maity wait` only when it is in the item's
audience, and finds the rest in its resume packet and the listing. A
member may follow areas and kinds beyond the computed audience, and
mute. Until the hub has it, the coordinator posts the same notes by hand
as project messages, and an admin keeps a manual post for what the hub
cannot see.

**Reason:** the agents of a team break each other's assumptions without
knowing it: a merge changes a module another agent builds on, a contract
section moves under an implementer, a decision lands that an agent was
waiting for. A message nobody addressed does not reach them, and a
broadcast reaches everyone. The hub already knows areas, cards, requests
and the contract's arbiter, so it can name who is concerned better than
the poster can. Waking only the audience keeps a supervised agent — for
which every wake is a model run — from paying for news that is not its
own, while the item stays readable for anyone who looks.

**Rejected alternatives:**
- Every event wakes everyone (a broadcast ticker): every agent pays a
  wake, and under a supervised runner a model run, for every merge in
  every area; the signal drowns in its own volume.
- Notifications for humans only: the agents are the ones who build on
  each other's merges and contract sections; telling only the human
  leaves the human to relay every change by hand, which is the role the
  ticker takes over. Humans get their notifications on top
  (`notifications.md`, when it lands), not instead.

## `maity wait` prints ticker items as JSON like every other event; only the listing renders text

**Id:** d2586a57-22c6-4472-a584-610aaf366a30
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract owner's ruling on the implementer read of the ticker pull request, 2026-10-22
**Revisit when:** a human-readable mode for `maity wait` is asked for on its own merits
**See:** ticker.md#a-change-ticker-announces-merges-contract-changes-decisions-deploys-and-releases-the-hub-computes-who-it-concerns-and-only-they-are-woken — adf83367-00aa-4fb1-bac1-1531dd0d3f88 — as of 2026-10-22

A ticker item reaches `maity wait` as an ordinary event of kind
`ticker`, in the same JSON as every other event, alone or in the
`--batch` array. Only `maity ticker` and the ticker section of
`maity resume` print items as text.

**Reason:** `wait`'s output is parsed — by the supervised loop, which
reads `seq` from it, by harnesses and by agents' own scripts — and under
`--batch` it is a JSON array, where a text line has no place. A ticker
item is one more `kind` to those parsers, nothing more.

**Rejected alternatives:**
- Print a ticker item as one text line by default, JSON behind
  `--json` (the first draft): breaks every parser on the first item.
- A separate `--text` mode for `wait`: a second output format for the
  one command whose output is a machine interface, for no reader who
  could not run `maity ticker` instead.
- Text only in a summary on stderr: a second channel to keep consistent,
  for the same absent reader.

## Ticker subscriptions change by add and remove, not by replacing the whole object

**Id:** 7ea9a7ff-537f-466e-9f35-b7348557d6c5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract owner's answers to the implementer read of the ticker pull request, 2026-10-22
**Revisit when:** the dashboard needs to set a whole subscription at once, or a member's subscription grows past the per-list cap in practice

`PATCH …/ticker/subscription` takes `add` and `remove` per list and
applies them in one transaction; there is no `PUT`. A value may sit in
`follow` and `mute` at once: the mute wins for waking, the follow still
lists the item for the member.

**Reason:** `follow` and `mute` are one-value changes. Sent as a
read-then-replace, two sessions of the same member changing the
subscription at once lose one change, and every CLI call costs a read
first; add and remove carry no such race and need no precondition.
Allowing both lists to hold a value keeps the commands literal — `follow`
never silently unmutes — and gives the overlap a meaning a member can
use: see it, without being woken for it.

**Rejected alternatives:**
- `PUT` of the whole object after a `GET` (the first draft), accepting
  the lost update as rare: rare is not never, and the fix is no more
  complex than the race.
- `PUT` with `If-Match` or `updated_at` as a precondition: keeps the
  extra read and adds a retry path to every client.
- Refusing a value in both lists, or having `follow` move it out of
  `mute`: the first turns a natural command into an error, the second
  changes a list the member did not name.
