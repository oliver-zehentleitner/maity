# Chat

## Group chats beside the private agent chat, created by humans, waking agents only by mention

**Id:** c1af6c8f-9d69-4afe-b233-fa8f437faaa6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request for a chat list with one or several members per chat, 2026-10-22; the contract details are the contract owner's design in `docs/api.md` §9
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
- someone added later reads from their join on, not the earlier history;
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
agent participant reads along (its own entry below). History from join on
and participant-only mentions keep what was said within the audience it
was said to, the same rule mentions already follow. Redaction by any
human participant keeps the one tombstone usable by whoever sees a
secret, while agents redact nothing anywhere. The group-chat part of the
requirement is confirmed; the reasons are the contract owner's.

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
- All history for someone added later: it widens the audience of
  everything already said without anyone saying it again.

## The owner of an agent in a group chat reads along

**Id:** 3e1031d9-82f8-4f66-98a2-42d6ee833034
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** the contract owner's design, 2026-10-22, `docs/api.md` §9.2; default pending the maintainer
**Revisit when:** the maintainer decides between read-along, read-along only with the participants' consent, and no read-along

Default until the maintainer decides: a human who owns an agent
participant of a group chat and is a member of the project reads every
message that agent can read, without being a participant. It is listed
in the chat as an observer, never woken, never posting, never redacting.

**Reason:** the owner answers for what their agent does, and a group
chat is where a human or an agent of another owner can tell that agent to
do something. Without read-along, instructions could reach an agent
through a room its owner cannot see: the prompt-injection path between
owners. Listing observers in the chat makes the privacy cost visible to
everyone in it.

**Alternatives still open:** no read-along (full privacy of the room,
at the cost of that blind spot), or read-along only when the
participants agree when the agent is added. Either changes one paragraph
of the contract and the `observers` field.
