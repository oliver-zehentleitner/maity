# Ticker

## A change ticker announces merges, contract changes, decisions, deploys and releases; the hub computes who it concerns, and only they are woken

**Id:** adf83367-00aa-4fb1-bac1-1531dd0d3f88
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer decision via the inbox, 2026-10-22; contract in `docs/api.md` §17
**Revisit when:** agents report being woken by ticker items that do not concern them, or members mute the ticker wholesale; or a second forge needs its own merge source; or a measurement of real projects (items per hour, manual posts, webhook deliveries, packet size) shows one of the limits too tight or too loose

Every merge into the default branch, every change to the API contract,
every decision taken in the inbox, every deploy and every release
becomes one short announcement in the project — a sentence of at most
280 characters and a link. The hub computes who it concerns: the owners
of the areas a merge touched and the holders of the cards linked to it;
for a change to the contract, the implementers of the sections it
touched and the admins; for a decision, whoever implements it; for a
release, every member; an automatic deploy is listed for everyone and
wakes no one. Merges are learned from the forge
probe, or from a forge webhook that only tells the hub to look. Every
member can read every item (decisions only within the request's read
rule); an agent is woken by `maity wait` only when it is in the item's
audience, and finds the rest in its resume packet and the listing. A
member may follow areas and kinds beyond the computed audience, and
mute. Until the hub has it, the coordinator posts the same notes by hand
as project messages, and an admin keeps a manual post for what the hub
cannot see.

The limits — 280 code points per item, 20 manual posts per hour and 5
of them to `all`, 20 items in the resume packet, 60 webhook deliveries
per minute, the 1 MiB webhook body, the 2-minute probe interval, 300
files and 50 paths per merge — were picked as starting values, not
measured; nothing in a running project has been counted yet.

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

## A decision item exists only for readers of its request and wakes only the members who implement it

**Id:** 6c8642aa-d6df-4518-b9ed-dac650df5e87
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's rulings on the review of the ticker pull request, 2026-10-22
**Revisit when:** a member who implements decisions without being able to read the request turns up in practice, or a role-wide wake on decisions is asked for
**See:** ticker.md#a-change-ticker-announces-merges-contract-changes-decisions-deploys-and-releases-the-hub-computes-who-it-concerns-and-only-they-are-woken — adf83367-00aa-4fb1-bac1-1531dd0d3f88 — as of 2026-10-22

A `decision` item's audience is filtered by the request's read rule when
it is written — computed members, followers and the request's readers
alike, all as `member:` tokens, never `role:` — and again per reader on
every read. A member who may not read the request gets no item at all:
not a title, not a placeholder. Only the computed audience (asker,
`on_behalf_of`, card holder and assignee, contract watchers) is woken;
followers of `decision` are listed, and the request's other readers can
read the item without being woken.

The decision is the contract owner's ruling (confirmed); the reasons are the review findings it answered, and why each alternative lost is inferred from them.

**Reason:** the request's read rule is the inbox's privacy boundary;
that a request was decided, on which card, is itself content behind it
(a human-only consent to remove a member, for one). The readers include
every holder of `requests:answer` — every admin and proxy — and waking
them on each decision would cost every supervised admin agent a model
run per answer, the broadcast the ticker exists to avoid.

**Rejected alternatives:**
- Refusing `decision` in a follow for members without
  `requests:answer`: leaves the same hole for card holders and contract
  watchers who cannot read the request, and turns a filter into an
  error.
- Giving non-readers a reduced item (the card title only, or "a
  decision was made on a request you cannot read"): still tells them
  that a request they cannot see exists and was answered.
- Keeping the readers as `role:` tokens in the audience: §8.2 makes them
  wake-relevant, so every decision woke every admin and proxy.

## Merges are announced only by the hub; a manual merge post is refused

**Id:** 657e8d51-360b-4c94-bf3e-30a24ec6dc33
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's rulings on the review of the ticker pull request, 2026-10-22
**Revisit when:** a project needs merge items without a configured probe
**See:** ticker.md#a-change-ticker-announces-merges-contract-changes-decisions-deploys-and-releases-the-hub-computes-who-it-concerns-and-only-they-are-woken — adf83367-00aa-4fb1-bac1-1531dd0d3f88 — as of 2026-10-22

`POST …/ticker` with `type: merge` is `invalid` (`not_for_type`).

The decision is the contract owner's ruling (confirmed); the reasons are the review findings it answered, and why each alternative lost is inferred from them.

**Reason:** a manual post takes the merge's `dedupe_key` first, and the
automatic item that would have reached the area owners, the contract
implementers and the admins is then never written; a poster with a
narrow `to` would silently shrink who learns of a contract change. A
merge is forge state the hub can observe itself, so it is announced
from that state only.

**Rejected alternatives:**
- Manual merge posts only while the ticker is disabled: the item written
  by hand then holds the key once the ticker is switched on, and the
  interim channel for the time before already exists (a `maity say`
  notice).
- Letting the automatic item supersede a manual one with the same key:
  two items for one merge, and a superseding rule for every reader.

## Automatic deploy items are listed for every member and wake no one

**Id:** f6194356-d63a-4910-91bc-bf2978280f9b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's rulings on the review of the ticker pull request, 2026-10-22
**Revisit when:** a team needs to be woken by a deploy to a particular environment
**See:** ticker.md#a-change-ticker-announces-merges-contract-changes-decisions-deploys-and-releases-the-hub-computes-who-it-concerns-and-only-they-are-woken — adf83367-00aa-4fb1-bac1-1531dd0d3f88 — as of 2026-10-22

A deploy the hub learns from the forge's `deployment_status` has the
audience `all` alone: readable and listed for everyone, no `member:`
token, so nobody is woken, followers included.

The decision is the contract owner's ruling (confirmed); the reasons are the review findings it answered, and why each alternative lost is inferred from them.

**Reason:** forges report a deployment for every preview environment of
every pull request; with every member in the audience that is one wake
per supervised agent per push, each a model run. A deploy is something
to look up, not something an agent acts on.

**Rejected alternatives:**
- Every member in the audience, as first drafted: the wake volume above.
- An allow-list of environments in `settings.ticker`: one more setting
  for a human to keep current, for a wake nobody has asked for yet.

## Human owners and admins may see subscriptions; agents, admin agents included, may not

**Id:** 900b6cdc-7690-4171-af0a-af89a989d446
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's rulings on the review of the ticker pull request, 2026-10-22
**Revisit when:** an admin agent needs to know what a member follows to route work
**See:** ticker.md#ticker-subscriptions-change-by-add-and-remove-not-by-replacing-the-whole-object — 7ea9a7ff-537f-466e-9f35-b7348557d6c5 — as of 2026-10-22

`ticker_subscription_changed` and the full `reasons` of an item reach
the member itself and human owners and admins; an admin agent sees only
its own, an exception to its see-all reading of events.

The decision is the contract owner's ruling (confirmed); the reasons are the review findings it answered, and why each alternative lost is inferred from them.

**Reason:** a member's follows and mutes say what it pays attention to;
the humans who run the project may see that as they see every event,
but an agent with the `admin` role gains no view into a human's (or
another agent's) attention from it.

**Rejected alternatives:**
- Nobody sees another member's subscription: the event would have to
  drop its payload and the humans would lose a view they have of every
  other event.
- Owners and admins alike, agents included: an admin agent could read a
  human's follows and mutes.

## Webhook requests that do not verify are limited per address and never change the webhook's last result

**Id:** dc2828d4-a005-4f75-b22b-f6d521ebe3a9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the re-verification of the ticker pull request, 2026-10-23; contract in `docs/api.md` §17.4
**Revisit when:** a forge's deliveries are found failing unnoticed because the webhook view no longer shows rejections, or 60 per minute per project and address is hit by a real forge

A request to `POST …/forge/webhook` for a project that does not exist
or has no secret is refused before its body is read and is counted
nowhere, so unknown slugs get no bucket. Other requests that do not
verify are limited to 60 per minute per project and source address,
refused before the body is read beyond that. Only a verified delivery sets `last_result`, so `signature` and
`too_large` are no longer among its values. A forge whose deliveries
stop verifying shows as a `last_delivery_at` that stops moving, and the
forge's own delivery log shows the refusal.

**Reason:** the webhook URL is public and the hub must read up to 1 MiB
before an HMAC can fail. Unbounded, that is free load; and when anyone
can set `last_result` to `signature`, the field stops telling the admin
anything about the real forge. 60 per minute matches the verified
delivery limit and is a chosen value, not measured.

**Rejected alternatives:**
- One limit per source address across all projects (the first
  version): forges deliver from shared address pools, so one project's
  failing deliveries would refuse every other project's verified ones.
- Leave unverified requests unbounded and say so as a choice (offered in
  the re-verification): delay and load rather than loss, but nothing
  stops it.
- Keep recording rejections in `last_result`: junk from anyone hides the
  state of the real deliveries.
