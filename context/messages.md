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
