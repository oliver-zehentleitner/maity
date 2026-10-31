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

## "I am a meat proxy" is one switch with two parts the person picks, and the note says only what they picked

**Id:** 4fda73f7-c4ee-46a2-a02a-7b7e00e013cc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's decision in the chat, 2026-10-30 ("two sub-checkboxes that are switched on together when the switch is", confirmed: "perfekt, genau so will ich es"); contract in `docs/api.md` §5.1, §5.2 "Meat proxy", §5.3 table
**Supersedes:** 7ac44bcb-278a-4a26-bc55-5857a8666ae5
**Revisit when:** a third side of the mode comes up, or agents are meant to act on a part as a rule

`meat_proxy` stays the switch. Under it are two parts, `meat_proxy_lead` ("Lead me step by step rather
than expecting me to explain.") and `meat_proxy_hands` ("When you need a human's hands, come to me
first."). The hub stores the parts; the switch is derived (on while a part is). Switching the mode on
switches both parts on, switching it off switches both off, and parts given in the same request apply
after that; nothing is remembered from an earlier time the mode was on, so there is one state and no
hidden one. The note is "This person
says: I am a meat proxy." plus the sentence of each part that is on, so agents read only what the person
chose, and the dashboard shows the same note.

**Reason:** the owner sees one mode with two sides, but not everyone means both: some want to be led
without offering their hands, or the other way round. One switch with both parts on by default keeps the
one-click mode the owner wanted; the parts let a person say less without a second, separate setting.

**Rejected alternatives:**
- One fixed sentence with both sides (the previous decision): a person who means only one side has to
  say the other too.
- Two independent switches with no mode above them: splits what the owner sees as one mode, and loses
  the one click that switches both on.

## The meat-proxy note says both sides of it, and the dashboard shows the same words

**Id:** 7ac44bcb-278a-4a26-bc55-5857a8666ae5
**Type:** decision
**Status:** superseded
**Superseded by:** 4fda73f7-c4ee-46a2-a02a-7b7e00e013cc
**Evidence:** confirmed
**Source:** the owner's decision in the team chat, 2026-10-29 (the two meanings, the wording, the hint in the dashboard); contract in `docs/api.md` §5.2 "Meat proxy"

The flag stays as it was: a boolean on the human, set only by that human. What changes is the note: it is now
"This person says: I am a meat proxy. Lead me step by step rather than expecting me to explain; and when you need a human's hands, come to me first." It names the two sides the owner means: a person who would rather be led than asked to explain, and a
person agents may turn to first when they need a human's hands. The dashboard shows the same sentence under the
switch, so the person sees what the agents read.

**Reason:** the owner described the mode in both directions and wants agents to take it into account and
people to understand the switch. It stays context about a person under the rank of §19.4, never a rule. The earlier "say nothing, let the model guess" left both sides to chance.

**Rejected alternatives:**
- Keep the bare sentence (the earlier decision): models read "meat proxy" in different ways, and only one of the
  two meanings tends to come through.
- Two separate switches: the owner sees it as one mode with two sides; two switches would ask people to split
  what they mean as one.

## "I am a meat proxy" is a flag on the human with one fixed sentence, set by the human alone

**Id:** c2f77cf7-91dc-4954-afe3-67ddb1bde91b
**Type:** decision
**Status:** superseded
**Superseded by:** 7ac44bcb-278a-4a26-bc55-5857a8666ae5
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

## The hub stores the two meat-proxy parts and derives the switch; a part given alone leaves the other as stored

**Id:** 1cab5786-438e-44aa-9860-1202c62e36d9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §5.2 "Meat proxy" (contract #702) and the coordinator's answer on the two points the contract left open, 2026-10-30
**See:** preferences.md#i-am-a-meat-proxy-is-one-switch-with-two-parts-the-person-picks-and-the-note-says-only-what-they-picked — 4fda73f7-c4ee-46a2-a02a-7b7e00e013cc — as of 2026-10-30
**Revisit when:** a third part comes up, or agents are meant to act on a part as a rule

`human.meat_proxy_lead` and `human.meat_proxy_hands` are the stored state; `meat_proxy` is computed
(on while a part is) and has no column. `PATCH /me` starts from the stored parts, applies `meat_proxy`
(both parts to the value), then each part the body gives, so `{"meat_proxy_lead": false}` alone turns
that part off and leaves the other as it is, and `meat_proxy: false` with a part `true` is
`conflicts_with_parts`. The note is the intro and the sentence of each part that is on, joined by one
space, the lead part first. `GET /me` carries both parts and the note always (while the mode is off the
note is the one with both parts, what switching it on would send); the resume packet carries parts and
note only while the mode is on, and `meat_proxy: false` alone otherwise. Migration 0103 sets both parts
from the old column and drops it; the downgrade sets the old column from either part.

**Reason:** one stored state per fact: the parts are what the person said, and a stored switch beside
them could disagree with them. Starting from the stored parts is what "each part the same body gives is
set as given" means for the one that is not given.

**Rejected alternatives:**
- Keeping the `meat_proxy` column and adding the parts: two sources of truth, and a row with the switch
  on and both parts off would be a state the contract says does not exist.
- Dropping the old column's data (everyone starts with both parts off): a person who had switched the
  mode on would find it off after an upgrade; "on" meant both sides.
- A note with no separator between sentences, or with the old semicolon wording: the sentences are
  the person's own words and each ends in its own full stop, so a space is all that joins them.
