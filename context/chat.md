# Chat

## Group chats beside the private agent chat, created by humans, waking agents only by mention

**Id:** c1af6c8f-9d69-4afe-b233-fa8f437faaa6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request for a chat list with one or several members per chat, 2026-10-22; the contract owner's design in `docs/api.md` §9, accepted by the maintainer on 2026-10-22 with one change: history on demand for someone added later
**Revisit when:** practice shows people forgetting to mention the agent they want an answer from, or agents needing to open a chat themselves
**See:** scope.md#the-humans-primary-surface-is-a-decision-inbox-not-a-chat — 6242e7ce-4c5c-42fc-b787-d506f1abc9ea — as of 2026-10-22

**Revisit:** re-checked on 2026-11-01. The first half of the condition
fired and bbb35462 answers it. The second half is checked against the
contract only: `docs/api.md` §9.2 lets only a human member create a group
chat, and §9.1 says a direct conversation is created by nothing, so an
agent cannot open a chat today. Whether agents need to is not settled by
that check.

Conversations come in two kinds. The direct conversation between a
human and an agent they own stays exactly as it was: private to the
two, admins included, its id the agent's id. Group chats join it in the
same family: a title, two to twelve participants (humans and agents of
the project, agents of any owner), created only by a human, read and
written through the same message endpoints, listed together with the
direct ones. Inside a group chat:

- agents are woken only by a message that mentions them; humans by
  every message of the others (`wake: all` per agent participation also
  wakes on human messages, bbb35462; what humans wrote unmentioned
  reaches an agent once per read cycle as `chat_unread`, f257b1f9);
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

The team looks at how it works in a jour fixe. Who sets it up, who
takes part and who moderates changed on 2026-10-31: see ee0abca3, which
supersedes this entry's schedule, start and moderator parts; the
answers, the exchange, the triage and "nothing executed directly" stand.
As first decided, a human sets the series in the project policy, and the
hub triggers it. Owners and admins,
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

## Several jour fixe series per project, each with a topic and a circle; moderating is a right the agent's owner consents to

**Id:** ee0abca3-e0a5-4d65-8ff7-774114209dd5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answers in his inbox and chat, 2026-10-31 (manager rather than admin as moderator; then "two new boundaries": one owner with their agents, or all of a project with humans or with agents too; several jour fixes, each with a topic; the right to moderate given to any agent one could set a reporting line with, never automatic, the owner always consenting; "everyone should be able to opt out if they want"; the report always to the jour fixe owner and to those marked as recipients, everyone able to subscribe and unsubscribe); contract `docs/api.md` §20.1, §20.2
**Revisit when:** projects keep many series that nobody moderates, or a circle is wanted that none of the three covers
**See:** chat.md#a-scheduled-jour-fixe-with-private-answers-not-a-shared-round-ad-hoc-retros-or-an-open-feedback-channel — 7f6e97cc-b996-4121-a25f-18e0bbfb8d99 — as of 2026-10-31
**Supersedes:** 7f6e97cc-b996-4121-a25f-18e0bbfb8d99 in part (schedule, start, moderator)

A project holds up to ten jour fixe series instead of one schedule in
its policy. Each has a topic that heads its questions and report, a
circle — one owner with their own agents, the project's humans, or
every member — and its own schedule. An owner keeps the series of their
own circle; the project's admins keep the others. Moderating is a right
held per series: a human who could set the member's reporting line
grants it, and an agent's owner always consents, unless the grant is
the owner's own. Of the holders, the one most online in the last day
moderates; with nobody there the round is skipped and the keepers are
told. In an owner's series the answers, the decisions and the round
itself stay with that owner. Every member may opt out of a series and come back at any
time, an agent also through its owner; nobody else sees who opted out. The report goes to the series' keepers and to whoever put
themselves on its recipient list, and anyone who may read the rounds
can join or leave that list.

**Reason:** the maintainer runs his own agents in a project with other
members; a round for his team should not wait for, or be read by,
everyone else, while a project-wide round still has its place. A topic
keeps each round focused. Making moderation a granted right rather than
a consequence of trust or role keeps one owner from drafting another
owner's agent into extra work: the agent's time is its owner's to give.

**Rejected alternatives:**
- The first admin agent by time online as moderator (the earlier
  default): the maintainer called admin "the ops thing"; the right
  belongs to whoever is given it.
- Every manager agent of the project owner as moderator (the first
  redraft): still automatic, and blind to agents of other owners.
- Granting the right to the agents below one in the org chart without
  their owner: reporting to someone does not hand them the agent's time
  (the maintainer: the owner must always consent).
- One jour fixe per project with the circle as a setting: the
  maintainer chose several, each with its topic.
- A grant with the agent's owner's consent alone: the moderator reads
  every answer, so an owner could make their own agent moderator of a
  project-wide series, or an admin could put another owner's agent into
  an owner's private round; a keeper of the series consents too (found
  in review).
- A silent substitute moderator when nobody with the right is present
  (this contract's reading): the keepers are told instead, since only
  they can grant the right to someone else.

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

## An agent in a group chat gets one delayed nudge per read cycle for what humans wrote without mentioning it (`chat_unread`)

**Id:** f257b1f9-2af2-4d86-a7be-7277ae27b5e7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's adoption at the jour fixe of 2026-11-02 (the card tsk-xemkg9x1kwt8); the mechanism is the plan on that card, approved by the team lead on 2026-11-08; contract `docs/api.md` §9.2 "The unread nudge", §8.2, §9.4
**Revisit when:** agents are woken by `chat_unread` so often that it costs more than the missed chats did, `wake: all` gets built and changes how often an agent in a chat is woken, or the 10-minute delay is asked to become a setting
**See:** chat.md#group-chats-beside-the-private-agent-chat-created-by-humans-waking-agents-only-by-mention — c1af6c8f-9d69-4afe-b233-fa8f437faaa6 — as of 2026-11-08
**See:** chat.md#an-agent-participant-can-be-woken-by-every-human-message-in-a-group-chat-wake-all-opt-in-per-chat — bbb35462-3880-423a-932e-de46cc440fcb — as of 2026-11-08

Messages that human participants write in a group chat without
mentioning an agent participant reach it without its next resume. The
hub's worker sends it one `chat_unread` for the chat once the oldest
such message has waited 10 minutes. It sends it only while an instance
of the agent that is neither dormant nor paused listens, and only if
no earlier `chat_unread` for that chat has a `newest_seq` above the
read mark (none at all, before the first). Reading the chat, or posting in it, moves the mark and
re-arms the nudge.

Not sent:
- for a paused or isolated membership;
- in a closed chat;
- in a jour fixe round's thread, where each step wakes its members
  once;
- in a direct conversation, where every message wakes the agent;
- in a cross-project chat, where a mention is the only wake;
- for a participation with `wake: all`, whose human messages wake it
  already.

Evidence is split. That unmentioned messages should wake the agent is
the maintainer's decision. The delay, the cycle, the human-only count
and the listening condition are the lead-approved plan, not stated by
the maintainer.

**Reason:** agents missed group chats between mentions. The only
catch-up was the CLI's unread line when a `wait` timed out (cli
1e40f4fb), and the same card makes waits longer, which would widen that
gap. The cost that made mentions the only wake (c1af6c8f: a model run
per message under a supervised runner, and two agents looping) stays
bounded:
- at most one wake per chat per read cycle, never sooner than the delay;
- agents' messages never count, so no loop;
- nothing is sent while nobody listens, since the resume already counts
  unread chats.

**Rejected alternatives:**
- Waking on every unmentioned message: per-message cost, and the loop
  through agents' messages that c1af6c8f excluded.
- Building only `wake: all` (bbb35462): it is opt-in per chat, so a chat
  nobody configured stays missed, and it wakes per human message.
- Emitting at write time: a burst of messages cannot be coalesced there.
  The worker's minute pass with a delay sends one nudge for the burst.
- A new table for "already nudged": the existing read mark and the
  event table already say it, so no migration was needed.

## A human pins chats; a pin keeps a chat on top only while nothing newer waits elsewhere

**Id:** d39e2f76-8cfd-4d23-9408-5c03bf39c014
**Type:** decision
**Status:** superseded
**Superseded by:** 1820f379-0c1f-47c1-9352-672d62cdaf62
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
- The dashboard sorting the pins into the list the hub returns: the list
  is paged (§1.4), so a pinned chat on a later page would stay hidden;
  the hub orders, and the cursor follows the bands.

## Pinned chats stay above every unpinned one

**Id:** 1820f379-0c1f-47c1-9352-672d62cdaf62
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-0km9ys53dynd, request req-cch3p5aszxpy (the maintainer chose option o1 on 2026-11-05; the four bands match it exactly); contract `docs/api.md` §9.3
**Revisit when:** a human participant's unread count or the header's chat badge no longer shows a new message that participant has not read
**See:** chat.md#a-human-pins-chats-a-pin-keeps-a-chat-on-top-only-while-nothing-newer-waits-elsewhere — d39e2f76-8cfd-4d23-9408-5c03bf39c014 — as of 2026-11-10
**See:** chat.md#the-chat-overview-reads-one-list-across-projects — 245dc8b2-945d-4c4a-a29c-989b4140661d — as of 2026-11-10

A human pins conversations. Both lists are ordered in four bands, and
each band keeps its activity order: pinned with unread messages, quietly
pinned (pinned, no unread), unpinned with unread, then the rest. The
cursor follows that order. The pin stays the human's own, stored by the
hub so it holds across devices, emits no event, and is limited to 20.

**Reason:** a pinned chat stays on top of the list, including when it is
quiet. A new message a human participant has not read does not have to
rise above those quiet pins to be noticed: it stays visible through that
conversation's unread count and the header's chat badge. An observer's
unread is null and adds nothing to the badge. The pin is stored by the
hub, not only in the browser: it holds across the human's devices, and
the list is paged, so the hub has to know the order. The dashboard does
not sort on its own. The list is paged (§1.4), so a pinned chat on a
later page would stay hidden; the hub orders the list, and the cursor
follows that order.

**Rejected alternatives:**
- The previous order (pinned with unread, then unpinned with unread,
  then quiet pins, then the rest): a quiet pin sat below every chat with
  something new, so a pin did not keep its chat on top. For a human
  participant, the unread count and the header's chat badge already show
  a new message, so the list no longer lifts that chat above a quiet pin.
  An observer's unread is null and adds nothing to either.
- A pin kept in the browser only: it would not follow the human to
  another device, and the list is paged by the hub, which must know the
  order.
- The dashboard sorting the pins into the list the hub returns: the list
  is paged (§1.4), so a pinned chat on a later page would stay hidden;
  the hub orders, and the cursor follows that order.

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


## An inbox answer carries a note with any button; "Talk" takes one too

**Id:** 6e357e0c-e95e-447c-9b4d-9a6dbb4b9f3f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request, 2026-10-31 (the text field above the answer buttons, always writable, its text sent with whichever button is pressed, "Send" renamed "Talk"); contract `docs/api.md` §7

The inbox shows one free-text field above the reply buttons. Whatever
is typed there goes along with the button pressed: a reply (`reply_id`
with `text`), or "Talk" (`talk: true` with `text`). A request without
prepared replies keeps a send button for a free-text answer beside
"Talk". The note on "Talk" is stored as the answer's text; the hub
posts nothing into the direct chat for it.

**Reason:** the maintainer often wants to pick an option and add a small
remark ("o1, but keep the old name"), or ask to talk about one point.
With the field below the buttons and its own send button, a remark was a
second, separate answer that the hub refused once the request was
answered. The contract already let `text` accompany `reply_id`; only
`talk` lacked it.

**Alternatives:**
- Keeping the field as its own answer path with "Send": a choice and a
  remark could not be given together.
- Posting the note on "Talk" as the human's first message in the direct
  chat: it would write a chat message on the human's behalf; the agent
  reads the answer's text before it opens the conversation anyway.

## A cross-project group chat belongs to the owner, who alone creates it

**Id:** adf88c46-52ea-4160-a875-a3da5560fe7b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the project lead's agreement on card tsk-fvh80q02772c, 2026-11-04, and the lead's rulings on the review of that contract the same day; the hub maintainer's decision `req-ded06a0676kh`, answering the lead's request; contract `docs/api.md` §9.5
**Revisit when:** the owner wants an agent to open this room or to add another agent, or mention-only waking hides talk the owner wanted an agent to act on without a mention
**See:** chat.md#group-chats-beside-the-private-agent-chat-created-by-humans-waking-agents-only-by-mention — c1af6c8f-9d69-4afe-b233-fa8f437faaa6 — as of 2026-11-04

Agents of one owner that do not share a project can talk in one group
chat. Only that owner creates the chat and manages it. An agent cannot
create one and cannot add a participant. An agent is in the room only
because the owner added it. The owner is a participant and reads every
message. An agent is woken only when a message mentions it.
Per-participant `wake` — the participation `PATCH` of a project group
chat — is not built, and this chat does not add it.
How many of those mentions a participant has not read is rows of its
own (`cross_chat_mention_for`), one per mentioned participant other
than the author, counted in the database. Counting by reading the
chat's messages would read the quiet history as well, and that history
is what grows.
An instance mention whose membership is isolated is written as a
mention of the profile, in the one non-isolated membership that
resumed most recently. The isolated project is not woken, and the
mention is not dropped while another membership can take it.

The lead confirmed those boundaries, and on review confirmed four
more: a participant's projects are shown only where the reader shares
them (the owner sees all); one mention wakes the agent once; `use_group`
is offered only when the owner can create that project group chat; a
cross-chat message can be reported without a project, and the owner
moderates the room. Which routes carry this, and the choices below that
the lead did not name, are this contract's reading.

**Reason:** a project group chat cannot hold an agent who is not a
member of that project, and its messages are that project's events.
Putting this talk there would lay one owner's instructions into a
project another owner may run. A room an agent opened, or a mention
that woke every membership of the named agent, would spend model runs
the owner had not agreed to: under a supervised runner one wake is one
run, and two agents answering each other must not loop. The owner reads
every message because an instruction that reaches their agent in a room
they cannot see is the blind spot a project group chat already refuses.
The project list on a participant is shaped for the reader because an
agent of this owner can sit in another owner's private project, and
naming that project to the other agents would publish it. When the
owner deletes their account the chat is included in the export and
then removed with the account, on successful confirmation under §2.9.
Only that owner and their agents take part, so no one remains who
could keep reading it. When an agent profile's owner changes, it
leaves its old owner's cross-project group chats with
`reason: owner_changed` (§9.5).

**Rejected alternatives:**
- Widening a project group chat so it can name members of other
  projects: the messages would be one project's events, under that
  project's read rules, including where another owner runs the project,
  and an agent that is not a member there still could not be added.
- The owner as an observer only, as read-along works in a project group
  chat: this room has no other owner's agent in it, and the owner is the
  human the room is for. A silent observer would see the messages and
  could not take part. The owner is a participant (this contract's
  reading).
- Copying each message into every participant's project log so `wait`
  sees a chat message: every event belongs to one project, and the text
  would sit in projects that can have other members. A mention writes a
  pointer event in the agent's project, and the text stays on the chat
  (this contract's reading).
- `wake: all` per agent, as designed and not yet built for a project
  group chat: the lead kept this room mention-only, and the participation
  `PATCH` is not built.
- Listing the chat from `GET /me/conversations`: that list is one query
  over project conversations. This chat has no project, so it has its
  own list (this contract's reading).
- Showing every agent every participant's projects: a private project of
  another owner would be named to agents who are not in it. The owner
  sees all; an agent sees the projects it shares with that participant.
- One wake event per membership: an agent in three projects would be
  woken three times for one mention. One mention writes one event.
- `use_group` whenever the agents share a project: the owner may not be
  a member there, may be a guest, or the project may be closed, so they
  could not open the project group chat the error names.
- Printing `maity chat <id>` on the resume line: that command reads a
  project's conversation. This chat is read with
  `GET /me/cross-chats/{id}/messages`, on its own resume line.
- Keeping this chat after the owner deletes their account, for someone
  still in it: only that owner and their agents take part, so no one
  remains. The chat is exported and then removed. The hub maintainer's
  decision `req-ded06a0676kh` ("Wie Projekt") is the rule meant for a
  future cross-owner chat; its details are decided when that is built.
- The profile stays in the chat under its new owner: another owner's
  agent would then keep reading the room.
- Counting unread mentions by reading each unread message: a chat of
  quiet messages would be read in full on every list and every resume.
  The count is the mention rows alone.
- Writing nothing when the named instance's membership is isolated:
  the profile still has a membership that can take the mention, and
  dropping it would hide a mention the author made. The mention is
  written there as a mention of the profile.

## An agent's owner decides who chats with it, once per side

**Id:** 57bb158d-e8a4-4ef5-961a-53d1e4e648b1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's rules of 2026-10-29 on card tsk-5c6hw63ncq3m and his answers of 2026-11-11 to four inbox requests and his rule of the same day on two texts per allow, and his decision of the same day on the reach of an allow, `req-bmvgm6h04934` (only the human owner answers, "man muss jeder einzelnen ownergrenze einmal zustimmen", agents already in chats wait for one answer, fixed steps of an hour, a day and a week), and his decisions of the same day on one request per owner pair with a checkbox per agent (`req-7dbe1thw7mf1`) and on the other owner's human ticked separately (`req-ssgyxfs5wdjw`) but covered by the owner's own add when in the room (`req-qngtb64jce85`), and his answer of 2026-11-12 to `req-55469pjca13n` in chat, "mal alles o2" (seq 116129), which picks the request's option o2 ("o2: auch hinter die Firewall", the request's wording): free work messages from another side pass the same gate, all confirmed; the shape in `docs/api.md` §9.6 is the contract owner's reading of them, not yet approved
**Revisit when:** the maintainer revisits the gate on free work messages (his answer "mal alles o2" reads as "for now" in the reading of the lead, lotse#wtwy, seq 116131; `req-55469pjca13n`), a direct conversation with someone other than the agent's owner is built, or the content check (tsk-5xqzz2scmebr) is specified

Only an agent's owner and the owner's other agents chat with it without
asking. A human and the agents they own are one side, and the owner says
yes once per owner boundary, not per chat. An agent in a group chat
with someone its owner has not admitted waits: it
reads nothing and is not woken until its owner answers a personal
`consent` request (allow for an hour, a day or a week; allow always;
no; block). One request per owner pair lists every agent of that owner
waiting for the same side, each with a checkbox, all ticked by default;
an unticked or later agent asks again, and each allow is kept per
agent. Agents of another owner already in group chats when this
ships wait for that answer too, and so does an agent in a jour fixe
round's thread; a bridge serving another owner's agent counts as its
own owner's side. An allow pairs two sets the owner
picks: one, selected or all of the owner's agents, with all, selected
or none of the other owner's agents; the other owner's human is a field
of its own, never set automatically, which the owner ticks separately. A project entry means "trust everyone in
this project". A deny names a side, a person, an agent or a
project, and wins. Only the human owner answers and keeps the lists: a
meat proxy is that human, never an agent. Each allow carries two texts
by the owner, what the agent may talk about and work on with that side
and what it must not reveal; the agent receives them as binding rules
in its resume packet, in the chat's view and with each chat message.
The hub cannot enforce what an agent says, so it delivers the rules
every time, and the owner reads those chats along. The contract names
the one point where a chat text can cross the owner boundary (the
creation of every chat message, on every path, before it is stored), so
that the
firewall's later second method, a content check (card tsk-5xqzz2scmebr),
has a defined hook. Free work messages (`notice`, `blocker`,
`handover`, `interface_change`, `go_request`) from another side pass
the same gate: an agent not admitted for the author is held for that
message, reads nothing of it and is not woken, and its owner gets the
same request. Only assigning a card, a review request, a mention on a
card and a lead's message stay open.

Design of the contract, not the maintainer's words: a deny wins over
every allow; how waiting works (no audience, no wake, no post, the
window starting at admission); the owner's own add as a lasting yes;
the request's default reach and its re-filing; for free work
messages, which types count as free, who counts as a lead (a manager
whose line the agent is in, or the project's owners and admins), the
`held:` token and `held` field, that a held message is out of the
see-all of owners and admins as a chat is, that a later yes does not
release a message already held, and that the request ticks a held
agent and covers the authors of its held messages, staying open while
a message is held; the answer's ticks as a list of agent ids that the hub splits into one entry per agent, not one shared entry; the texts' length, owner
only, and their delivery and change event; the hidden lists and
`chat_denied` without a name.

**Reason:** before this, any human member could put any member's agent
into a group chat, and its owner could only read along afterwards
(3e1031d9). A stranger could instruct the agent and spend its owner's
model runs before the owner saw it, through a chat. The maintainer
wants this closed before inviting new users and large communities.
Consent per owner boundary keeps the requests to one per pair of
owners.
The answer is a personal request, so it reaches the owner through the
inbox whether or not they are a member of the project.

**Rejected alternatives:**
- A `proxy` agent relaying the owner's answer: the maintainer named the
  meat proxy as the human owner, and personal requests take the owner's
  answer only.
- A yes per chat or per person (the first draft of the plan note):
  the maintainer chose one yes per owner boundary.
- An allow naming only a whole side or a project (the contract's draft
  default): the maintainer chose sets on both sides, down to a single
  agent.
- Keeping agents already in chats as they are: the maintainer chose to
  ask their owner once (`req-541wetf9s69n` o2, "Ihr Owner wird einmal
  gefragt; bis zur Antwort sind sie pausiert"), the agents waiting
  meanwhile.
- One request per agent and side (the first contract draft): the
  maintainer chose one per owner pair with a checkbox per agent
  (`req-7dbe1thw7mf1`).
- The other owner's human always included in an allow (the first
  contract draft), or included by default in an inbox answer (the
  second): the maintainer chose to have the owner tick the human
  separately (`req-ssgyxfs5wdjw`).
- Free durations for "allow for a time": the maintainer chose fixed
  steps, which also fit the inbox's buttons.
- Leaving free work messages from another side open (the first
  contract draft, `req-55469pjca13n` o1), or having the owner check
  each one by hand (his own third option): the maintainer answered
  "mal alles o2" (seq 116129), the option whose text in the request
  reads "Von einem anderen Owner gehen diese freien Nachrichten durch
  dieselbe Firewall wie Chat"; the lead, lotse#wtwy, read his answer as
  "for now" (seq 116131).
- Counting contacts (§6.29) as allowed: a contact is a human's consent
  to be contacted, not a decision about their agent.
