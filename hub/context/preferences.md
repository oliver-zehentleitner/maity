# Preferences

## A preference proposal's go is checked before it is answered, and the human's edit travels in the proposal

**Id:** 3f1e2f4e-5cca-4b98-9df5-51c874f84bbd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (preferences, §19.4)
**Revisit when:** proposal settlements get the answer's body, or another kind needs to refuse an answer by its content

The personal answer route asks `preferences.check_answer` first: a `go`
on a stale `base_version`, plain or edited, is `conflict` and the request
stays open. An edited `go` writes its `markdown` and `base_version` into
the request's `proposal` as `edit`, in the same transaction, before the
request is marked answered; the registered settlement then applies the
proposal as stored, and records `result: {version, edited}` there too.

**Reason:** the proposals registry settles a request from the request
row alone (`proposals.Settlement` carries no answer body), after the
answer is stored. A conflict found there would come after the request was
already answered, and the human's edit would not reach it. Checking first
keeps a stale go from closing the request; carrying the edit in the
proposal keeps one settlement path for every proposal kind.

**Rejected alternatives:**
- Pass the answer body into `Settlement`: a change to every kind's
  signature for one kind's need.
- Apply preferences in the answer route itself, outside the registry: a
  second path for proposals, which the registry exists to avoid.

## "I am a meat proxy" is a flag on the human with one fixed sentence, set by the human alone

**Id:** c2f77cf7-91dc-4954-afe3-67ddb1bde91b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the owner's wish in the team chat (2026-10-28, a checkbox in the personal profile, default off, shown in the agents' briefing, the model's reading left to the model); the coordinator's constraints (a boolean on the human, only the human sets it, a short fixed sentence)
**Revisit when:** agents are meant to act on it (a rule instead of a remark), or humans want to say more than yes or no

`human.meat_proxy` (default `false`) is set with `PATCH /me` by the human for themselves. The resume packet
carries it on `me.owner` (the agent's own human) and on every human in `peers` (the humans of its project),
and while it is `true` adds `meat_proxy_note`, the one sentence "This person says: I am a meat proxy."
Nothing explains it. An agent's `PATCH /me` with it is `forbidden` (`humans_only`); no admin sets it for another.

**Reason:** the owner wants agents to know this about a person and to make of it what they will, so the hub
says it and does not interpret it. A boolean with a fixed text keeps what reaches the briefing bounded and
the same for everyone; it is context, like the preferences, and gives no right.

**Rejected alternatives:**
- A line in the free-text preferences (§19.4): reaches only the agents of projects that include them, is
  capped and quoted as the author's prose, and cannot be read by a machine or switched in one click.
- A note that tells the agent what to do ("treat this person as a relay"): the owner asked for no
  interpretation, and an instruction from the hub would read as a rule.
- Next to `language` in the notification settings: that is the mail and notification page, and the flag
  is not about notifications.
