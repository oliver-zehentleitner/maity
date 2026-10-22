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
