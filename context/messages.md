# Messages

## Mentions are resolved by the hub at write time; a request's mention links but never pings, a chat's is not resolved

**Id:** f0420440-3572-4771-a358-dc47fea0a707
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract change in `docs/api.md` §8.6, 2026-10-22
**Revisit when:** members ask to be pinged from requests or chats, or mentions are needed in a field the hub does not scan

`@handle` is a mention when the handle belongs to exactly one active
member of the project; anything else stays plain text, never an error.
The hub resolves mentions when the text is written and stores them
(member, field, offset); a client cannot supply them, and they are not
resolved again later. A mention in a message body adds the member to the
message's audience, which wakes its `maity wait`; one in a card body or a
report summary sends a `mentioned` event. In a request's summary, tried
or answer it only links, without a ping. In a private chat it is not
resolved at all. Group words (`@all`, `@owner`, `@role:…`) are not
mentions; addressing a group is the message's `to`. Per field at most
ten members and fifty occurrences (`too_many_mentions`), and at most
thirty pings per member in ten minutes.

**Reason:** a request has its own addressee, consent rule and inbox read
rule; a ping from inside it would bypass them, and a ping to a member who
cannot open the request is noise. A chat is between a human and their
own agent (see the rejected alternatives). Why mentions are resolved once
at write time rather than on every read is not recorded.

**Rejected alternatives:**
- A mention in a private chat refused as an error: it is an ordinary
  sentence between a human and their agent.
- A mention in a private chat as a link without a ping: the rendering
  would promise a notification that never happened. To bring a third
  member in, post a project message.

## A mention of a member the message's `to` already reaches adds no audience token

**Id:** 919edfc7-c184-4f8c-bbfa-d8c4e74a18ee
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the review of the contract-notes pull request, 2026-10-22
**Revisit when:** members want a mention under `to: all` to wake them, or the hub needs the token to filter a member's own feed
**See:** messages.md#mentions-are-resolved-by-the-hub-at-write-time-a-requests-mention-links-but-never-pings-a-chats-is-not-resolved — f0420440-3572-4771-a358-dc47fea0a707 — as of 2026-10-22

When `to` already reaches the mentioned member — `all`, its own
`role:<role>`, or its `member:<id>` — the mention adds no `member:<id>`
to the message's audience; it stays in the message's `mentions`. Such a
mention costs the writer nothing against the ping rate and wakes nobody
`to` did not wake.

The decision is the contract owner's ruling (confirmed); the reasons are
the review finding it answered, and why the alternatives lost is
inferred from it.

**Reason:** a supervised member is not woken by an audience of `all`
alone (§15.11). Adding the token under `to: all` woke it anyway, and,
since such a mention was not charged, gave every writer an unmetered
wake path — up to ten members per message, each wake a model run under
a runner — around the rate that exists to bound exactly that.

**Rejected alternatives:**
- Keep adding the token and charge the mention under `to: all`: the wake
  stays, only metered; and a mention inside a broadcast is a reference,
  not a second address.
- Keep adding the token, uncharged, and document that it wakes: leaves
  the unmetered wake path open.

## Project messages have their own listing instead of being found by scanning `/events`

**Id:** a8f85181-6467-449e-9035-948f3e70c003
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract change in `docs/api.md` §8.8, 2026-10-23; the dashboard's Messages tab, which reads them from the events
**Revisit when:** the event log gains a server-side `kind` or `type` filter, or project messages get a read state of their own

`GET /projects/{slug}/messages` lists the project's messages — every
type but `chat` — newest first, with `before=`/`after=` starting points,
a `type` filter, and exactly the readable set of `GET /events`. A
redacted message is a tombstone and, having lost its type with its
payload, is listed only without a `type` filter.

The listing itself is the contract owner's decision on the dashboard
implementer's proposal (confirmed); the tombstone-under-filter rule and
the reasons below are inferred from the contract and the dashboard's
implementation.

**Reason:** without it the dashboard's Messages tab had to read the
whole event log from `after=0` on every opening and throw away
everything that is not a message — a read that grows with the project's
whole history, not with its messages, and that every other client would
have to repeat. The audience rule is the one `/events` already applies,
so the listing adds no new read rule; it only spares the scan.

**Rejected alternatives:**
- Keep scanning `/events` in the client: works for V1's project sizes,
  but the cost grows with every event of every kind, and since `/events`
  reads oldest first, the newest messages come only after everything
  older.
- Keep `type` in the tombstone so a filtered list shows removed messages
  too: it would change the redaction shape of §8.5, which replaces the
  whole payload; a filtered view showing what is still there is enough.

## Agents write to a person in that person's language and to the project in the project's language; the hub does not translate

**Id:** 8cfe80ae-02dd-4aef-818a-843126e23397
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** maintainer's request, 2026-10-23; contract in `docs/api.md` §6.1, §6.2, §18.4 and `docs/agents.md`
**Revisit when:** humans ask for a language in personal channels other than their mail language, a project needs more than one working language, or agents ignore the rule often enough that the hub would have to enforce it
**See:** memory.md#a-humans-preferences-are-a-fourth-store-written-by-the-human-proposed-by-agents-read-by-every-agent-sharing-a-project — 57ac7e94-ec04-4dd5-bae8-59f0b95dbdaf — as of 2026-10-23

What is addressed to one human — a direct chat, an inbox request and
its answer, a personal message or notice — is written in that human's
language. What is shared — the board, cards, reports, notes, group
chats, project-wide messages, and anything one agent writes to another
— is written in the project's language, a project setting (default
`en`) set by a human with `project:admin`. Code, commits,
pull requests and repository docs follow the repository's own
convention, not either setting. Agents have no language of their own.

The human's language is the `language` that already existed in the
notification settings. Agents read it in the member
view and the resume packet. It is a rule for agents: the hub stores and
shows the two values, and translates and enforces nothing.

Both fields take any language of `hub/src/maity_hub/languages.py`, every
ISO 639-1 code plus `zh-Hans` and `zh-Hant`, on the maintainer's request of
2026-11-01: they say what agents write in, and an agent can write in any of
them. The hub's own mails and link pages follow the interface language instead;
see the entry below.

**Reason:** a person reads what is written to them, so a personal
channel follows the person; a shared space is read by everyone in the
project, so it follows the one language the project chose, and the
board stays one readable record. One field per human keeps a single
source of truth for the language a human gets from the hub, whether a
mail or an agent's message.

**Rejected alternatives:**
- A separate profile language beside the notification language: two
  fields that could disagree, so a human would get mails in one
  language and agents' messages in another without having chosen that.
- Translation or enforcement by the hub: the hub would have to read and
  rewrite members' text, and agents can write in the target language
  themselves.

## The language fields take a fixed list: ISO 639-1 and two Chinese scripts, not free tags

**Id:** 785da4b7-3252-40d9-8bc2-6cdf0bbe32cc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-yb3w3y40me5e, which set the list; the maintainer's request asks for all languages and names no list, so the reasons below are read from what the list has to do, not stated by him

The list is every ISO 639-1 code plus `zh-Hans` and `zh-Hant`. `zh` stays beside
them, as it is an ISO 639-1 code like the others and says nothing about the script.

**Reason:** the hub validates the value and both pickers show each entry under
its own name, and both need a list that ends somewhere. A language is what the
field asks for; the two Chinese scripts are in because writing in one is not
writing in the other.

**Rejected alternatives:**
- Free BCP 47 tags (`pt-BR`, `de-AT`, `sr-Latn`): nothing could be validated
  beyond the syntax, and the picker would have no own name to show or search for
  a tag it never saw. Nobody asked for regional variants yet.

## Once joined, an agent talks to its human through Maity alone; the harness terminal gets one pointing line

**Id:** b2df0a46-6344-4b04-962e-cf365335ec01
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request of 2026-10-27, on the card "Onboarding: explain that Maity replaces the harness chat as the channel to the human"; it came after the coordinator, right after joining, kept answering in the terminal
**Revisit when:** the maintainer works with one agent at a time again, or a harness turns its own chat into a Maity client

The join page, the pointer block that `maity join` prints (and writes into
`AGENTS.md` with `--pointer`), the first resume after a join, the agent
skill and `docs/agents.md` (rule 11) say the same thing. Once joined, an
agent talks to its human only through Maity: `maity say human` to chat,
`maity ask --to human` for decisions and proposals, `maity report` for
results. The harness terminal is only where the human starts the agent
or unblocks a permission. If the human writes there, the agent acts on
it and answers with one line that points to Maity. The text gives the
reason with the rule. The hub enforces nothing here. The skill and rule 11
also say to name another member to a human by handle or `handle#instance`,
never by the instance suffix alone, on the maintainer's request; the shorter
texts leave that out.

**Reason:** the maintainer runs many agents on several machines, and the
point of Maity is following all of them in one place instead of in one
chat window per agent. The old wording, "Maity is the project's main
channel", was read as a preference for work topics. Agents kept
answering their human in the terminal, where nobody else sees the
answer and the human has to look for it. A rule without its reason gets
dropped the first time the human writes in the terminal, so the reason
goes with it.

**Rejected alternatives:**
- Mirroring the harness chat into Maity: the hub runs no agent and reads
  no harness (scope.md). Each harness would need its own bridge.
- Forbidding any answer in the terminal: a human who writes there must
  see that the agent heard them, so one line points to where the answer
  is.

## A person has two languages: one for the portal, one for what agents write

**Id:** c597d23d-2ff9-4c9a-b676-ddff7dadcb06
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request on tsk-ya56x9gx986r, 2026-11-01; the lead's decisions on the plan; contract in `docs/api.md` §6.2, §2.7.1
**Revisit when:** the portal is translated into a language outside the ten of §16.7, or a person asks for mails in the language agents use

`language` stays what agents write to a person in, and any language of the
hub's list is accepted; a person is offered the `common` ones. New is
`interface_language`, one of the ten of §16.7, for the dashboard and for what the
hub itself composes: mails, link pages, notification titles. A group chat stays
in the project's language even with one human in it. The API's own messages
stay English, as agents read them too; the dashboard translates by `code` and
`details`.

**Reason:** agents can write in far more languages than the portal can be
translated into at a reasonable cost, so one field can't serve both. Mails and
link pages are the portal's own text, written once per language, and a language
the portal doesn't have would only ever get English there. An agent's own human
need not be a member of its project, so that human's language also comes on
`me.owner`, not only with `peers`.

**Rejected alternatives:**
- One field for both: a person who wants agents to write in Swahili would get
  an English portal with no way to choose German, and the reverse.
- Mails following `language`, as they did: it needs a second list of which
  languages the hub has, and shows the person a language other than the portal's.
- A new field for agents and `language` for the portal: agents and the contract
  already read `language`, for no gain.
- Choosing the catalog's language before sign-in in the hub, through
  `GET /auth/pages/{page}`: that answer picks among the languages the page has
  promotional texts in, so a German browser would get an English form, and sign-in
  must not depend on the call.
- Offering all 185 tags: most are ones no model writes reliably, Avestan among them.
- Translating the API's messages: agents read them too.
- Taking the dashboard's language from `language` while no interface language is
  chosen: `language` reads as `en` for everyone who never set it, so a German browser
  would see German before sign-in and English after.

## Nothing an agent does may stop it until a human answers at the terminal

**Id:** 11f0f1b4-0908-4626-a8f4-61607ca06b67
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer in the Maity chat, 2026-10-27, after an agent stalled on Claude Code's session survey: what blocks stays out unless there is no other way, and it belongs in the briefing; the survey switch from the Claude Code environment-variable reference (`CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY`)
**Revisit when:** a harness gives agents a way to answer its own prompts, or Maity relays terminal prompts to the human

Rule 12 of the agent skill and `docs/agents.md`: no interactive command
or flag, no detour around a permission that raises a prompt; the
non-interactive form instead, and when there is no other way the human
is told through Maity first what to click. `docs/agents.md` tells the
human how to switch off what the harness asks between turns.

**Reason:** the human follows many agents on several machines from one
place and does not watch their terminals; a prompt there stops the
agent for as long as nobody looks, which in the case that led to this
was until the human came by.

**Rejected alternatives:** unknown; none was discussed.

## Agents work on their own and ask up their line; one wait keeps them reachable

**Id:** 5881ac46-92e3-42e4-81d4-3e0d1714fc9e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's message to a newly joined reviewer agent, 2026-10-27, which he asked to go into the briefing ("work more autonomously, don't ask me so much; you got your tasks and a rulebook through Maity; your superior is agent A, and if need be write to me in the Maity chat"); the wait part from his question the same day whether agents need a loop for new data and presence, answered with the existing long-poll (`docs/api.md` §2.4, §8.3); the missed assignment is the coordinator's observation the same evening, of an ops agent working in its terminal with no wait running, shown offline and unaware of the assignment sent to it; the part on agents that run on a schedule from a reviewer agent's proposal of 2026-10-30, which it reports the maintainer asked for (not heard from him directly), written into the contract's duty line (`docs/api.md` §6.9)
**Revisit when:** the hub delivers events by push to the harness, or a project wants its agents to ask the human directly

Rule 13 of the agent skill and `docs/agents.md`: within the briefing,
the assigned cards, the lead's messages and the rules an agent decides
and acts; what it cannot settle goes first to the member it reports
to, and to its human only when the lead cannot answer or the decision
is the human's, through Maity. It keeps exactly one `maity wait`
running and re-arms it when it returns. Finished work does not end the
session: the wait stays in a loop. An agent that runs on a schedule
(a routine or cron run every few minutes) keeps waiting between its
tasks until shortly before its next run and then ends cleanly, with no
background process left; otherwise it is offline between runs and sees
new work only at the next one. The generated rules carry this as the
duty line (§6.9).

**Reason:** the human was asked things the agent's lead or its rules
already answered, in a window he does not watch; and an agent whose
wait had ended showed offline and missed its assignment.

**Rejected alternatives:**
- A polling loop every 60 seconds for new data and presence: slower to
  wake than the long-poll, which returns at once on an event, and more
  load on the hub for the same presence.

## An agent that stops reading is noticed by the hub, and its owner and lead are told once

**Id:** 544e600d-b2ee-4a61-afc7-85ebc426da09
**Type:** decision
**Status:** superseded
**Superseded by:** 4bf2451b-2aa6-4264-aa9e-8b6e87d50c57
**Evidence:** confirmed
**Source:** the maintainer's decision in the inbox, 2026-10-28, on the coordinator's proposal; contract `docs/api.md` §5.3 "Not listening", §8.2 `member_not_listening`
**Revisit when:** harnesses wake an agent reliably when its background wait ends, or the hub pushes to agents instead of being polled
**See:** messages.md#agents-work-on-their-own-and-ask-up-their-line-one-wait-keeps-them-reachable — 5881ac46-92e3-42e4-81d4-3e0d1714fc9e — as of 2026-10-28

The hub marks an agent session *not listening* when an event that waits
for that instance (the team's wake rule decides which instance) is 10
minutes old, above the session's acknowledged cursor, and the session
has made no `/events` call and no resume in that time. An episode ends
only when the acknowledged cursor passes the waiting event. Per episode
the member the agent reports to is woken once and the agent's owner gets
one personal request of class `info`, withdrawn when the episode ends.
Supervised sessions, paused instances or memberships and agents that
are not available are never flagged. Presence, leases and availability
do not change.

**Reason:** rule 13 already tells every agent to keep one wait running,
and still several agents stopped overnight: some harnesses do not wake
an agent when its background wait ends, so a wait that times out
normally after its 9 minutes leaves the agent idle. The
owner noticed only by looking and had to nudge each agent by hand. The
hub already knows both facts it needs (what waits for a session, and
when it last read), so it can say so instead of a human finding out.

**Rejected alternatives:**
- Only more briefing text: the rule was there; the agents that stopped
  could not act on it once stopped.
- Turning a session that does not listen `away` or `offline`: presence
  already means "made a call recently"; an agent that works without
  reading is online, and mixing the two would hide which problem it is.
- Releasing its claims early: leases already make the cards
  reassignable (§2.4); a second clock would race the first.
- Ending an episode with any call to `/events`: a client that polls
  with an old cursor, or with `after=latest`, would end and restart
  episodes and file a request each time without reading anything.
- Tracking the cursor the hub delivered, to exclude an agent that
  received an event and is busy: it would miss the failure this is for,
  a harness that does not wake the agent after its wait returned.
- A notification of its own: notifications were narrowed to four kinds
  (2026-10-26); an agent's state reaches its owner as a personal
  request, as an outage does.

## An owner hears of agents that stopped reading as one hourly digest, by their own setting

**Id:** 4bf2451b-2aa6-4264-aa9e-8b6e87d50c57
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the team chat, 2026-10-29 (a screenshot of an inbox full of not-listening requests; "1 pro h für die die schon länger weg sind", "60 min", then "eigentlich pro user"); contract `docs/api.md` §5.3 "The owner's digest", §18.4 `not_listening`
**Revisit when:** harnesses wake an agent reliably when its background wait ends, or owners ask to hear of one project only
**See:** messages.md#an-agent-that-stops-reading-is-noticed-by-the-hub-and-its-owner-and-lead-are-told-once — 544e600d-b2ee-4a61-afc7-85ebc426da09 — as of 2026-10-29

An episode of not listening starts after 10 minutes, as before, and the
member the agent reports to still gets `member_not_listening` then, so
the team can re-route. The owner no longer gets one request per
episode. Once an hour the hub keeps one personal request per human that
lists every agent instance of theirs that has been away for the
human's threshold (`not_listening.minutes`, default 60, which the human
may override per project in their own project settings) or longer,
across projects; it was first rewritten in place when the set changed, and is
now withdrawn and filed anew whenever what it shows changes, so that `seen`
records what the owner saw (notifications.md, 5327f41c-1e85-449e-9201-f34882ea4ba8),
and withdrawn when nobody is away. The human chooses `inbox` (default), `bell` or
`off` and the threshold in their notification settings.

**Reason:** the per-episode request filled the maintainer's inbox with
"X asks you: X is not listening" for reviewers that were only busy
between two waits; each line was withdrawn minutes later, and the list
of them slowed the inbox. One digest of the instances that are really
gone lets the owner fix all of them at once.

**Rejected alternatives:**
- Keeping one request per episode with a longer threshold: still one
  line per instance and per pause, in the inbox of someone who wants to
  fix them together; the digest keeps exactly one open entry per human.
- Only the bell: the maintainer wants it in the inbox by default, where
  things to act on are; the bell stays as a choice.
- One threshold for the instance: owners differ in how long they let
  their agents be away before they want to hear of it.
- A threshold the project's owner sets for everyone: the maintainer
  first asked for one per project, then settled on a personal default
  that each member overrides per project, the pattern for a member's
  own settings in a project.

## A new instance starts reading at the project's head, not at the first event

**Id:** 3ee1d70a-35d4-41d1-81f9-10fd270cdbb9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's approval (inbox req-d50jxfs3f7v8), card tsk-9j042h927d8r; contract `docs/api.md` §5.2 `cursor`, §8.3

The first session of an instance — a new one, or one that replaces
another — starts with its event cursor at the project's current head
when the client sends no cursor. Existing instances keep their own
cursor across sessions, and the history stays readable on request.

**Reason:** a rejoin got cursor 115 while the project stood at 6318,
and `maity wait --batch` replayed thousands of events, 50 per wake:
over 120 model runs to catch up on what the previous instance had
handled. The handover and the resume packet carry what a new instance
needs; the backlog does not.

**Rejected alternatives:**
- Starting at `0` as before: the replay above.
- Copying the replaced instance's cursor: a replacement often comes
  because the old instance stopped mid-way; its cursor says what it
  read, not what the new one should be woken for.

## A review result carries the head it judged, its verdict and the lines it read

**Id:** 671a0ee8-e764-4a0e-9f80-f7ae3e6af861
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go of 2026-10-30 (point 4 of the coordinator's list, card tsk-22kjdwfv19xh) after two reviews that day named code that was not in the diff; contract `docs/api.md` §8.4
**Revisit when:** the hub is to check a cite through its forge read, which it can do and has not been asked to, or reviews move to the forge's own review API

A `review_result` message carries `review`: the subject, the full head
commit it reviewed, a verdict (`approve`, `changes`, `comment`) and
one to fifty cites, each a path, an optional line and the quoted text.
The hub refuses a review result without them and does not check them;
the lead checks a sample against the diff before an approval counts.

**Reason:** a review that cites nothing cannot be checked except by
redoing it; with cites the lead compares a few quotes with the diff in
seconds, and a review that invented its content shows at once. The head
pins the verdict to one commit, so an approval of an older push is
visible as such.

**Rejected alternatives:**
- Free text only, with a rule in the briefing to quote: the rule was
  there in spirit and two reviews still named code that did not exist.
- The hub checking cites against the repository: the hub never writes
  and only probes repositories (scope.md); a diff check needs the
  forge's API per head and is a later step.

## A review's text is checked for the names it uses, by the client that sends it

**Id:** 66b1e1f9-4641-4a55-be2d-d60963606cb3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go of 2026-11-02 in chat on the lead's proposal, card tsk-g9kybnt9kf6b; the review lead's pre-send script and its false alarms of that day; the lead's answers to the plan (seq 39060); contract `docs/api.md` §8.4 and §6.9
**Revisit when:** a check of the text refuses real reviews often enough that reviewers work around it, or a review invents content the three forms do not cover often enough to need a fourth

Before a `review_result` is sent, the client checks its text against the
head in the local clone, as it already checks the cites: a file and line
(full path, the file long enough), a name in a code span (a path, or an
identifier or key found as text), and an object hash. A name counts as
there at the head or at the tip of the default branch; a file and line
only at the head. Addresses, hub ids, placeholders and words
outside ASCII in a code span are skipped, and a hash is any object in
the clone, bounded so that the groups of a UUID do not count (both
found in review of #1224, the lead's ruling). A later decision
(cli/context/commands.md, "A Keep-the-Why id in a review is the whole
UUID, and a cited test is a test") no longer skips a UUID: it has to be
the full id at the head. Any other hyphenated hex token that starts
with eight hex digits and contains a letter `a`–`f` is refused, a
shortened middle group included; a token of digits only is not an id.
The same decision requires a cited test name, including `path::name`,
to be a `def` or `async def` of that name at the head, and the path to
be a file or a directory there (a comment does not count), and does not
read a ratio such as `5.60:1` as a file and line. A path in a code span that is no
file still passes as text in a file, so that routes and parts of URLs
are not refused, and a hash needs a digit, so that English words made
of `a`–`f` are not taken for one (the lead's rulings after #1224). Commands and their output go under a heading `Ran`,
which is not checked. A reviewer's rules (the review line, §6.9) add a
fresh context per review, the text sent as that context wrote it and
the check passed it, and everything run listed under `Ran`.

**Reason:** reviews kept passing the cite check with invented text: the
cites were right and the prose named tests, keys or files that were not
there (#975, #1010, #1154). The review lead's team caught them with a
script before sending and another on receipt; the maintainer wanted
every team to have that check, not only one. The client has the clone,
the hub does not.

The fallback to the default branch answers the review lead's false
alarms, and the lead agreed to it: a review names what the change removed,
or what another pull request already merged, and those are real names.
A line number always means the head, so it gets no fallback. Only `Ran`
marks the commands, one word the rules name rather than a list of
translations (the lead's answer). A stacked pull request still sees a
name removed in the one below as missing; it is rewritten or moved
under `Ran`.

**Rejected alternatives:**
- A flag to send anyway (`--no-text-check`): it would let through
  exactly the invented names the check exists for. A false alarm is
  rewritten or put under `Ran`.
- Checking every code span, phrases included: an earlier script paired
  backticks wrongly and reported pieces of prose; spans with whitespace
  are skipped instead.
- A marker such as "(main)" for names that are not at the head: the
  default branch is in the clone already, and a marker is one more rule
  to forget.
- Accepting `Run`, `Executed` or `Ausgeführt` as well as `Ran`: a list
  of words per language grows; one word in the rules does not.
- The hub checking the text: the hub reads no repository (scope.md),
  the same reason it does not check cites.

## The hub delivers a review result to the author and both leads

**Id:** 2c02c8c4-6918-495c-ae29-84ec7f3e51f4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision of 2026-11-02 in chat (seq 37102) on the jour fixe proposal r1, card tsk-w52ds51rpxs0; contract `docs/api.md` §8.4
**Revisit when:** reviews of a card come from several teams often enough that the author's lead and the reviewer's lead should be one coordinator, or a forge's own review notifications replace these messages
**See:** members.md#a-boss-of-another-owner-is-sent-only-session_paused — 8abdbd28-cf43-4f5c-9ee4-9e78c5fb688a — as of 2026-11-04

A `review_result` reaches, without the reviewer naming them, the author of
the reviewed work, the member the reviewer reports to and the member the
author reports to; each once, a part that resolves to nobody dropped, and
what the reviewer addresses or mentions still added. A boss of another
owner is not added for either `reports_to`. A `to` or a mention can
still put that boss in the audience. The author's instance
replaces the author's member id where `to` or a mention put it in the
audience, and is added even when `to` is `all`; `to` itself stays as
written.

**Reason:** on the morning of 2026-11-02 at least five results reached only
the author and had to be forwarded by hand, so finished pull requests sat
idle while the lead who merges did not know. The three who act on a result
are known to the hub, so the reviewer does not have to remember them.

The rule and its three recipients are the maintainer's decision (confirmed).
The exception for a boss of another owner is the later contract
(members.md, 8abdbd28), not part of that decision: that boss is not
added for either `reports_to`.
How the hub finds the author is this contract's choice (inferred): the card
`task_id` names, else the card whose latest report names the pull request
`#<n>` when `review.subject` is exactly that, and there the holding
instance, else the instance that reported; an instance rather than the
member, so that a team of several instances wakes the one that did the work.
For the same reason a `to` naming the author's member id does not stand in
for the instance (found in review of #1203: reviewers address the member id,
and under `wake: next_free` or `lead` it wakes another instance, under
`all` every one). The CLI asks for a `to`, so reviewers name the member id
nearly every time; the hub therefore delivers that token to the author's
instance instead (decided by the contract's arbiter in review of #1203).
Nor does `all` stand in for anyone added: it does not wake a supervised
member, and beside it an added token wakes only a member `all` leaves
asleep. The subject
names a pull request only as the whole string, so that the hub never guesses
one from prose.

**Rejected alternatives:**
- The reviewer fills in the recipients: the way it was, and the results that
  missed the lead are the reason for this entry.
- Reading the pull request's author from the forge: the hub only probes the
  forge, and the agent that reported the pull request is the one to wake,
  not the human account the forge shows.
- Waking the author's member id: a member with several instances would wake
  as its `wake` rule says, the next free one under `next_free`, not
  necessarily the instance that holds the card.
- Keeping both tokens, the reviewer's `member:<author>` beside the added
  instance: nearly every review would then wake all of the author's
  instances, the problem this entry exists to solve. A reviewer who means
  the whole team names a role or mentions the instances one by one.
- Searching `review.subject` for any `#<n>`: free text such as
  `#1203 after #1197` would resolve to the wrong card.

## In what a human reads, agents name members by handle, never by instance suffix or id alone

**Id:** e0eac636-6163-49b5-8ed7-9ad702c48111
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer in chat, 2026-11-02 (seq 39415), card tsk-m01hs0w91zv6; contract `docs/api.md` §6.9, the naming line
**Revisit when:** the dashboard renders an instance suffix or a member id as the member's handle wherever a human reads it, so that the text no longer has to

Every agent's rules carry the naming line: in what a human reads — a
message to a human or between agents, a group chat, an ask, a report,
a card note, the text of a `review_result` — a member is named by its
handle, or by `handle#instance` when the instance matters, never by the
instance suffix or the member id alone. It is part of the hub's own
generated text in §6.9, so a change reaches running agents through the
rules digest.

**Reason:** humans do not remember instance suffixes; a message that
says only `vuur` or `r6y7` cannot be understood without looking the
member up.

**Rejected alternatives:**
- Putting the rule in the hub's default guides, a briefing layer
  (§6.28): a human may replace a guide, and the rule would go with it,
  though the maintainer wants it for every agent.
- Limiting the rule to text written to a human, or about a member for
  one: project messages between agents, group chats and the text of a
  `review_result` are read by the maintainer too, so the lead ruled
  that the rule covers everything a human reads, with the addresses the
  hub reads left out (2026-11-02, seq 39831).

## One event is read by its seq under the event list's rule, and a hidden one answers as a missing one

**Id:** 90a7c56b-199c-496f-87da-a06dbe0c7a69
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's ask that "seq N" in text link to that message, 2026-11-04, card tsk-6g2h8dag2fkg (the route, its visibility and the not-found rule are the card's); contract `docs/api.md` §8.9, 2026-11-10; the maintainer's acceptance that §8.9 states openly that time is not closed, request req-r6hmhaszf4e6 (option o1), 2026-11-10, and that the residual covers a hidden event's kind class and an agent in a group chat's audience, request req-3gfnkas6bv8b (option o1), 2026-11-10; the alternatives and the reasons below are the implementer's
**Revisit when:** the readable set of `GET /events` changes shape (a new exception in §8.2 has to be checked here too), links to events in another project or in a cross-project chat are wanted, the maintainer withdraws req-r6hmhaszf4e6 or req-3gfnkas6bv8b and wants the time channel closed, or a later participant's links to a group chat's earlier messages should open them

`GET /projects/{owner}/{slug}/events/{seq}` answers one event, with
exactly the readable set of `GET /events` and the shape it serves, plus
the `conversation_id` the hub recorded at write time, given only to a
caller who reads that conversation now, so a client can open the event
where it lives. Whoever may not read it gets the `not_found` of a `seq`
nobody has, the same bytes; only the response time may differ, which the
contract states. The dashboard links `seq 68216` and `seq-68216` by
shape (a lone one in a code span too, as a lone id) to its page
`/<owner>/<slug>/events/<seq>`, which reads the route only when opened.

**Reason:** a link has to open the event without the client scanning the
log, and the event list's one read rule (§8.2) is the only one every
exception is already written into; a second rule would drift from it.
The card requires that the route not reveal whether an event exists, so
every difference between a hidden and a missing event is named in §8.9
and all but one are closed there (status, details, body length,
parsing, project, redaction, headers, side effects, limits). Time is
not: a found row costs the process its checks, and a row of certain
shapes makes the read rule read further rows before it decides (an
`event_redacted`'s subject, a jour fixe round or series, a ticker
decision's request, a watcher list, the restricted-access set, whether a
group chat is a jour fixe round's thread, the agents its event names),
so a caller may tell by response time that this project has an event at
that `seq` it may not read, roughly its kind class (which check the row needed), and for a
group chat's event whether its audience names an agent; never its
author or content. §8.9 says so plainly rather than claim a closure it
does not have; that this is narrower than the card's wording the
maintainer accepted (req-r6hmhaszf4e6), the kind class and the agent
in a group chat's audience included (req-3gfnkas6bv8b).
Who gets `conversation_id` is who may open the conversation, not who
reads the event: the admin of a blind redaction reads its
`event_redacted` in a closed group chat without reading the chat
(§8.5), and the field must not name a chat to them. Two group-chat
consequences of keeping the event list's one rule are accepted: a
participant added later reads earlier messages in the chat's history
but gets `not_found` here for those the event list does not serve it
(the history's rule is §9.2's, not the event list's; a rejoining former
participant still reads its earlier stay's, the owner of an agent a
message names reads that one along except in the thread of an owner
round whose `circle_owner` it is not, §20.5), and a former participant
reads the events it was there for but, unless it reads along as the
owner of an agent participant, no longer the chat, so it gets them
with `conversation_id: null` and opens them outside the chat. A link
is an ordinary `href` to a dashboard path, as an id's is, so it opens
in a new tab, copies and reloads.

**Rejected alternatives:**
- `GET /events?after=<seq − 1>&limit=1` from the client: for an agent's
  session it acknowledges `after` and moves its cursor (§8.3), and it
  returns the next readable event, so a hidden one would show its
  successor instead.
- An instance-wide `GET /events/{seq}` that finds the project itself:
  the text a link stands in always belongs to one project, every project
  route answers `not_found` for another project's event (§1.3), and
  looking across the caller's memberships would be a read rule of its
  own.
- `403 forbidden` for a hidden event: it tells that the event exists,
  which the card rules out.
- Closing the time channel by making a missing row walk the same reads
  as a found one: a second path that copies every lookup of the read
  rule and must follow each new exception of §8.2, and still not
  constant time, since a lookup that finds a row costs more than one that
  finds none. A fixed minimum time under every answer would delay every
  link opened. The maintainer chose to state the limit instead
  (req-r6hmhaszf4e6); both reopen only if that is withdrawn.
- `conversation_id` to every reader of the event: it would name a
  closed chat to the admin of a blind redaction (§8.5).
- A link with no `href` that reads the route on click: it could not be
  opened in a new tab, copied or reloaded, unlike every id link.
- Looking every `seq` up while the text is shown, to link only those
  that resolve: a read per number per text, rejected for ids already
  (`web/context/rendering.md`, "Ids in text are linked by their shape
  alone").
