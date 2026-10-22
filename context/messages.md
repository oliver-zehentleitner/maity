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
