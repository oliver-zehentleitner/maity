# Chat

## Group chats beside the private agent chat, created by humans, waking agents only by mention

**Id:** c1af6c8f-9d69-4afe-b233-fa8f437faaa6
**Type:** decision
**Status:** needs-review
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
  every message of the others (partly superseded, pending the
  maintainer's confirmation: `wake: all` per agent participation wakes
  on human messages, bbb35462);
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
  for it: the cost and loop above, for the chats that turn it on (a
  switch limited to human messages, which cannot loop, is bbb35462).
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
**Evidence:** confirmed
**Source:** the contract owner's ruling of 2026-10-22 on the re-verification of the group-chat contract, and its reason given the same day (`docs/api.md` §8.5, §9.2)
**Revisit when:** admins redact closed chats they cannot read often enough that the participants' privacy suffers, or former participants misuse the right
**See:** projects.md#a-closed-project-refuses-additions-never-removal — e9c3b578-c282-43c1-b5f4-4a494ae0464e — as of 2026-10-22

A group chat closes when its last human leaves, and then no human is a
participant who could redact in it. In a closed chat every former human
participant may redact any message it could read, and a human with
`members:admin` may redact a message by its id without reading it,
acting on a report. The reason of an admin's redaction is shown only to
that admin and the chat's former human participants, and the admin's
call answers only that the message is redacted, never the event. Agents
still redact nothing, and observers stay read-only.

**Reason:** a secret pasted into a chat must stay removable after
everyone left. Without this, it stays for good once the last human
left: the remaining agents and their owners keep reading it, and
redaction is the only tombstone the log offers. Observers stay
read-only because they never were part of the conversation.

**Rejected alternatives:**
- No redaction in a closed chat (the first draft): the secret stays.
- Observers redacting: offered by the review beside former
  participants; rejected because observers never were part of the
  conversation, so they stay read-only here as everywhere else in the
  chat.

## A participant's window starts at an event seq, and every stay in a chat is its own row

**Id:** 7c3796af-aa65-4818-94aa-e10b2ccc67c1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the hub's group chats (`hub/src/maity_hub/group_chats.py`, migration `0035_group_chats`), 2026-10-23
**Revisit when:** messages stop being events in the project log, or a chat needs a window that is not "from the latest join on"

The hub keeps one `conversation_participant` row per stay of a member in a
group chat: leaving ends the row, being added again starts a new one, and
an at-most-one marker (`here`) keeps a single open stay per member. Each
row stores `window_after`, the project's highest event seq at that join;
the participant's window, `unread` and the default page of `…/messages`
count only messages after it.

**Reason:** the window is "the chat from the latest join on" (§9.2), and
messages are events ordered by seq, so a seq bound needs no clock and
cannot drift against the order of messages. Rows per stay keep each
departure's `by`, `reason` and `left_at` for the participation answer and
for redaction in a closed chat, which asks who was a human participant
at any time. Inferred from the contract and the code, not stated by the
maintainer.

**Rejected alternatives:**
- A `joined_at` timestamp as the window's start: two writes in the same
  instant, or a clock step, would put a message on the wrong side.
- One row per member, overwritten on a rejoin: the earlier stay's
  departure is lost, and with it who was a former human participant.

## A scheduled jour fixe with private answers, not a shared round, ad-hoc retros or an open feedback channel

**Id:** 7f6e97cc-b996-4121-a25f-18e0bbfb8d99
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's approval of 2026-10-22, card tsk-1h94qh8497p1, the maintainer's redesign of 2026-10-23, and the maintainer's confirmation of the remaining defaults (windows, moderator order, presence, deciding) on 2026-10-31; contract in `docs/api.md` §20, forwarding in §7
**Revisit when:** the cost of a round (wakes, steps) turns out higher than its proposals are worth, rounds keep being skipped for want of a moderator or members, or members stop answering
**See:** chat.md#group-chats-beside-the-private-agent-chat-created-by-humans-waking-agents-only-by-mention — c1af6c8f-9d69-4afe-b233-fa8f437faaa6 — as of 2026-10-23
**See:** memory.md#a-humans-preferences-are-a-fourth-store-written-by-the-human-proposed-by-agents-read-by-every-agent-sharing-a-project — 57ac7e94-ec04-4dd5-bae8-59f0b95dbdaf — as of 2026-10-23

The team looks at how it works in a jour fixe. A human sets the series
in the project policy, and the hub triggers it. Owners and admins,
admin agents included, can also start one by hand. The hub asks every
present member three questions: what went well, what went badly, what
would help. Each member answers privately to the moderator, by name or
anonymously, or does not answer at all; nobody is chased. The moderator
bundles the answers into a statement of topics, citing who said what,
anonymous items marked as such. A bounded exchange per topic follows:
response, reply, rejoinder, each once and in its own window. The
moderator's report triages every proposal. The moderating admin agent
decides a proposal itself within the rules and its owner's
preferences, cited by version (the maintainer's decision of
2026-10-23, which replaced the owner's memory entries as that basis),
or sends it to the owner's inbox as a decision request. Nothing is executed
directly: an adopted proposal becomes an ordinary card.

**Reason:** answers given privately to the moderator are more honest
than answers given in front of the team, and anonymity makes the hard
ones possible. A member is woken for the questions and then only for
the steps that concern it, so the cost stays bounded and predictable.
The hub triggering the round means nobody has to remember it. The
triage keeps the owner's decisions with the owner while the admin agent
settles what the rules already allow.

**Rejected alternatives:**
- A shared group-chat round, in which every present member answers in
  one room, everyone reads every answer, and follow-ups run by mention
  (the first design, 2026-10-22). It lost on honesty, because people
  answer differently in front of the team; on wakes, because every
  answer can draw follow-ups that wake others; and on noise, because
  everyone reads everything.
- Ad-hoc retros: they depend on someone remembering to hold one, and in
  practice nobody does.
- An always-open feedback channel: it wakes everyone constantly, so its
  cost has no bound.

## A request carries its own discussion thread; the decision stays a separate click

**Id:** 4e46effb-1e30-4a52-999f-c337db71dbfd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#the-humans-primary-surface-is-a-decision-inbox-not-a-chat — 6242e7ce-4c5c-42fc-b787-d506f1abc9ea — as of 2026-10-27

Every request in the inbox gets a comment thread beneath it. Whoever may
read the request may write: the human, the asking agent and its team,
and for project requests the admins; agents are woken when they asked or
are mentioned. The decision stays a separate action (an option or a
text), so a comment never counts as one. "Let's talk" opens this thread
instead of the direct chat. After the decision the thread stays
readable; follow-ups go into a new request. Attachments as in the chat.

**Reason:** the maintainer wants to discuss a request where it is
asked, without losing track of what was decided.

**Rejected alternatives:**
- Keeping "Let's talk" as a jump into the direct chat, as built: the
  maintainer asked for a discussion inside the request instead.
- Leaving the thread open for follow-ups after the decision: offered as
  an option, not chosen; no reason given.

## The chat overview reads one list across projects

**Id:** 245dc8b2-945d-4c4a-a29c-989b4140661d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report that the dashboard feels slow, above all the chat, 2026-10-28; the web owner's measurement that `#/chats` reads `GET …/conversations` once per project each round, p95 7.8 s
**See:** chat.md#group-chats-beside-the-private-agent-chat-created-by-humans-waking-agents-only-by-mention — c1af6c8f-9d69-4afe-b233-fa8f437faaa6 — as of 2026-10-28

A human's chat overview gets its own route, `GET /me/conversations`,
that merges the §9.3 lists of all the human's projects into one paged
list, newest activity first, each item naming its project, with the
unread totals of all items. The project routes stay the place to read
and write a conversation; agents keep the per-project list, since an
agent lives in one project.

**Reason:** the overview's cost grew with the number of projects, one
request per project per refresh, and the slowest of them set the pace
of the whole page. One query over the caller's memberships answers it
in a single round trip.

**Rejected alternatives:**
- Reading the project lists in parallel in the browser: fewer seconds
  of waiting, but the same number of requests on the hub, which was
  the load problem in the first place.
- Caching the per-project lists in the browser and refreshing them less
  often: new messages would show late, which is what the overview is
  for.

## An agent participant can be woken by every human message in a group chat (`wake: all`), opt-in per chat

**Id:** bbb35462-3880-423a-932e-de46cc440fcb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** a gap reported on the maintainer's behalf by an agent in a chat of two humans and that one agent, 2026-10-30 (messages without a mention went unseen); the contract owner's design in `docs/api.md` §9.2 and §8.2, confirmed by the maintainer in his inbox, 2026-10-31
**Revisit when:** agents with `wake: all` are woken so often that it costs more than the missed messages did, or people ask for the same in chats with several agents
**See:** chat.md#group-chats-beside-the-private-agent-chat-created-by-humans-waking-agents-only-by-mention — c1af6c8f-9d69-4afe-b233-fa8f437faaa6 — as of 2026-10-30

The trigger of c1af6c8f fired: in a chat where two humans talk to their
one agent, the humans did not mention it, and the agent saw their
messages only by reading the chat by hand. Each agent participation now
has `wake`, `mentions` by default as before, or `all`: then every
message of a human participant wakes the agent and is in its packet. An
agent's message still wakes another agent only by a mention. Those who
manage the chat, the agent itself and its owner set it, also when adding
the agent; `all` for an agent of another owner only the agent and its
owner.

**Reason:** the costs c1af6c8f guards against stay bounded. A wake per
human message is what the humans asked for in a chat they hold with
their agent, and humans write at a human pace; two agents cannot loop,
since agent messages never wake through `wake: all`. Opt-in per chat
keeps busy chats from crowding the packet.

**Rejected alternatives:**
- Wake on every message automatically when the member is the only agent
  in the chat — the behaviour would change silently when a second agent
  is added, and a chat with one agent can still be busy.
- The chat's managers set `all` for any agent — `all` costs the agent's
  owner a model run per human message, and an agent's settings are its
  owner's (66d4076f); a manager may still set `mentions`.
- `all` waking on agents' messages too — two agents with `all` would
  answer each other without end, the loop c1af6c8f excluded.

## A human pins chats; a pin keeps a chat on top only while nothing newer waits elsewhere

**Id:** d39e2f76-8cfd-4d23-9408-5c03bf39c014
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request, 2026-10-31 ("Empfänger pinnen … ganz oben, außer sie haben keine neuen Nachrichten, aber ein anderer Chat hat neue, dann ist der auch ungepinnt drüber"); contract `docs/api.md` §9.3
**See:** chat.md#the-chat-overview-reads-one-list-across-projects — 245dc8b2-945d-4c4a-a29c-989b4140661d — as of 2026-10-31

A human pins conversations; the list is ordered in four bands, each by
activity: pinned with unread messages, unpinned with unread, pinned
without, the rest. The pin is the human's own, stored by the hub so it
holds across devices, emits no event, and is limited to 20.

**Reason:** the maintainer wants the chats he works with at the top, but
never at the price of missing something new elsewhere: a quiet pinned
chat must not sit above a chat with a new message. Four bands express
exactly that and keep the activity order inside each.

**Alternatives:**
- Pinned always on top: a new message in an unpinned chat could drop
  below several quiet pinned ones and be missed.
- A pin kept in the browser only: it would not follow the human to
  another device, and the list is paged by the hub, which must know the
  order.

## A human switches the meat-proxy mode per chat; the profile gives the default

**Id:** 1bdcfac7-9bf9-4ae3-9ad6-23b7f8e9a535
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request, 2026-10-31 (a meat-proxy button next to "Attach" and "Send" that switches the mode on and off for this chat; with "I am a meat proxy" in the settings the chat starts in that mode); contract `docs/api.md` §9.3

A human sets the meat-proxy mode for one conversation: `true`, `false`,
or `null` to follow the profile. The value that holds in a chat is on the
human's entry in that chat's participants, with the profile's note while
it is on, so the agents in the chat read it next to the person. Only the
human sets it, for itself; it is context, never a permission.

**Reason:** the same person may want to be led step by step with one
agent and talk briefly with another, or in one project and not in the
next. Changing the profile for every chat would switch it for all of
them at once. Putting the value on the participant entry means the
agents see it where they already see who is in the chat, without a new
field elsewhere.

**Alternatives:**
- Only the profile switch (the state before): all or nothing across
  every chat and project.
- A per-project switch: still too coarse for the case of one chat with
  one agent, which is the one the maintainer described.
- Both parts per chat (`{lead, hands}` per conversation): the button the
  maintainer asked for is one on/off switch; whoever wants one part only
  sets it in the profile and leaves the chat on `null` (this contract's
  reading).
- A change as an event that wakes the agents in the chat: it would cost
  a model run per agent for context that matters only at their next
  turn; a change emits no event, and the agents read it on their next
  resume or read of the chat (this contract's reading).

