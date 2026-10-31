### Changed

- docs/api.md §7: an answer's `text` may accompany `talk` as well as `reply_id` — a short note
  on "let's talk" or on the chosen reply, stored as `answer.text`. The inbox shows one free-text
  field above the reply buttons; every button sends its text along, and the talk button reads
  "Talk".
- docs/api.md §9.3: a conversation's own view (§9.1, §9.2 and its replay) carries `pinned` too;
  no event carries it.
- docs/api.md §20.1: the upgrade's pending moderator grants get their consent request from the
  hub after it starts, not from the upgrade; §20.6 (b): a `to_owner` request in an owner series
  goes to the owner's membership while they are a member, and is personal only otherwise.
