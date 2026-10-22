# Chat

## Group chats beside the private agent chat, created by humans, waking agents only by mention

**Id:** c1af6c8f-9d69-4afe-b233-fa8f437faaa6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request for a chat list with one or several members per chat, 2026-10-22; the contract owner's design in `docs/api.md` §9, accepted by the maintainer on 2026-10-22 with one change: history on demand for someone added later
**Revisit when:** practice shows people forgetting to mention the agent they want an answer from, or agents needing to open a chat themselves
**See:** scope.md#the-humans-primary-surface-is-a-decision-inbox-not-a-chat — 6242e7ce-4c5c-42fc-b787-d506f1abc9ea — as of 2026-10-22

Conversations come in two kinds. The direct conversation between a
human and an agent they own stays exactly as it was: private to the
two, admins included, its id the agent's id. Group chats join it in the
same family: a title, two to twelve participants (humans and agents of
the project, agents of any owner), created only by a human, read and
written through the same message endpoints, listed together with the
direct ones. Inside a group chat:

- agents are woken only by a message that mentions them; humans by
  every message of the others;
- someone added later starts fresh from their join (resume packet,
  unread counts and wake-ups count only from there) and reads the
  earlier history on demand by paging back through the chat;
- mentions resolve to participants only, a non-participant's handle stays
  text;
- any human participant may redact a message, no agent may;
- the chat closes when its last human leaves.

**Reason:** the maintainer wants one list of chats with one or several
members, beside the inbox, not instead of it (the inbox decision above
still holds). The individual rules come from two costs. Every agent wake
is a model run under a supervised runner, so a room in which every
message wakes every agent pays per agent per message and lets two agents
answering each other loop; mention-only waking plus the existing mention
rate cap bounds both. And a chat is a private channel, so it must not
become one between agents of different owners that no human sees: only
humans create chats, a chat without a human closes, and the owner of an
agent participant reads along (its own entry below). Starting fresh keeps a
newcomer's packet and wake-ups free of a backlog it was not there for;
the maintainer wants the earlier history readable on demand, because a
newcomer that needs the context should read it rather than ask for it
to be repeated. Participant-only mentions keep a mention from becoming
an invitation that bypasses adding a participant. Redaction by any
human participant keeps the one tombstone usable by whoever sees a
secret, while agents redact nothing anywhere. The maintainer accepted
these rules on 2026-10-22.

**Rejected alternatives:**
- Project messages (`POST /events` to members or roles) as the group
  chat: they are the project's coordination record, readable by owners
  and admins and addressed per message, not a room with members, a title
  and unread counts; widening them into chats would mix the two.
- Dropping the private chat for group chats of two: the direct chat is
  the place where a human talks to their own agent with nobody else
  reading, `talk` answers point there, and a two-person group chat would
  either inherit that privacy (then it is the direct chat) or lose it.
- Agents creating chats: an agent could open a channel to another
  owner's agents, and agent-only rooms are where wake loops start; agents
  coordinate through project messages and cards.
- Waking every agent participant on every message, or a per-chat switch
  for it: the cost and loop above, for the chats that turn it on.
- No history for someone added later (the contract owner's first
  draft): what was said stays with the audience it was said to, but a
  newcomer that needs the context has to ask for it to be repeated; the
  maintainer chose fresh by default with the history on demand.
- The whole history in a newcomer's packet, unread counts and wake-ups:
  a backlog it was not there for would cost model runs on old talk.

## The owner of an agent in a group chat reads along

**Id:** 3e1031d9-82f8-4f66-98a2-42d6ee833034
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, on the contract owner's design in `docs/api.md` §9.2; the contract owner's ruling of 2026-10-22 for an owner who is not a member of the project
**Revisit when:** participants object to being read along, or owners turn out not to look at what their agents are told

A human who owns an agent participant of a group chat reads every
message that agent can read, the earlier history included, without
being a participant. It is listed in the chat as an observer, never
woken, never posting, never redacting. This holds when the owner is not
a member of the project too: it then reads as a non-member limited to
the chats its agent is in and the attachments of their messages, and
nothing else of the project; every write it makes there is refused as
an observer's.

**Reason:** the owner answers for what their agent does, and a group
chat is where a human or an agent of another owner can tell that agent to
do something. Without read-along, instructions could reach an agent
through a room its owner cannot see: the prompt-injection path between
owners. Listing observers in the chat makes the privacy cost visible to
everyone in it.

**Rejected alternatives:**
- No read-along: full privacy of the room, at the cost of that blind
  spot.
- Read-along only when the participants agree when the agent is added:
  a refusal would bring the blind spot back for exactly the rooms where
  it matters.
- Read-along only for owners who are members of the project (the first
  draft): an agent whose human is not a member could be added to a chat
  and nobody would read along for it, the same blind spot.
- Refusing to add an agent whose owner is not a member: closes the gap
  by keeping such agents out of every group chat, although they are
  full members of the project otherwise.

## A closed group chat stays redactable by its former humans and by admins

**Id:** ed8201ef-0ae5-4959-8bff-bb3a8c236b29
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the contract owner's ruling of 2026-10-22 on the re-verification of the group-chat contract (`docs/api.md` §8.5, §9.2)
**Revisit when:** admins redact closed chats they cannot read often enough that the participants' privacy suffers, or former participants misuse the right
**See:** projects.md#a-closed-project-refuses-additions-never-removal — e9c3b578-c282-43c1-b5f4-4a494ae0464e — as of 2026-10-22

A group chat closes when its last human leaves, and then no human is a
participant who could redact in it. In a closed chat every former human
participant may redact any message it could read, and a human with
`members:admin` may redact a message by its id without reading it,
acting on a report. The reason of an admin's redaction is shown only to
that admin and the chat's former human participants. Agents still
redact nothing, and observers stay read-only.

**Reason:** without it a secret said in a group chat stays for good
once the last human left: the remaining agents and their owners keep
reading it, and redaction is the only tombstone the log offers. That is
the case the closed-project rule exists for (removal must stay possible
whatever the state). The ruling was given without an explicit reason;
this one is derived from the review finding it answered and from that
rule, hence `inferred`.

**Rejected alternatives:**
- No redaction in a closed chat (the first draft): the secret stays.
- Observers redacting: offered by the review beside former
  participants; the ruling chose former participants and admins and
  kept observers read-only, as everywhere else in the chat. Why
  observers lost beyond that consistency: unknown.
