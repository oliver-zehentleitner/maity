### Added

- Contract: a message may name several recipients (§8.4, not built, tsk-c7caka34dhkw).
  `to` takes a JSON array of at most 10 member ids and instance addresses (the CLI
  resolves handles); `all`, `role:` and `trust:` stay single values (`single_only`). The
  message is one stored event whose audience is the union of the entries; a bad entry
  refuses the whole message, named by its 0-based index
  (`details.fields["to.2"]: "not_a_member"`, `"not_a_string"`), the same string twice is
  `duplicate` and more than 10 `too_many`. Each recipient is judged by the §9.6 gate on
  its own and a held one is listed in `held`; every distinct recipient after the first,
  the sender's own member and instances aside, spends one of the 30 mention pings per 10
  minutes; a list that names more than one member is written in the project's language.
  `payload.to` is stored as written, a string or an array, a one-entry array staying an
  array, so the dashboard reads arrays before the hub sends them (§1.3, §1.7, §8.2, §8.6,
  §8.8, §9.6).
- Contract: `POST …/events/{seq}/forward` (§8.4, not built, tsk-c7caka34dhkw) passes a
  message on as a quote. Only a reader of the original under §8.9 forwards it (else
  `not_found`); a chat message, another kind of event, a redacted original and a forward
  whose root was redacted are refused, and a forward and its root's redaction serialize.
  The forward is a plain `message` of type `notice` (the default, also sent explicitly),
  `blocker`, `handover`, `interface_change` or `go_request` (never `review_result`,
  `update` or `chat`) with the optional note as its `body` (`""` when omitted), no
  attachments of its own, and `forward_of: {seq, from, from_instance, via?, sent_at,
  type, task_id, body, mentions, attachments, review?}` as data that routes, pings and
  approves nothing; a forward of a forward names the root. Each recipient agent the
  forward reaches is gated for the forwarder and for the original's author as they stand
  at the forward, with a lead forwarder exempt for both (a manager per recipient) and the
  recipient's own owner's forward passing for that agent; an author no longer an active,
  non-isolated member, or whose side cannot be resolved, admits nobody (held, fail
  closed), and a bridge that wrote the original or makes the forward is a party too.
  Redacting the original tombstones the quote in every forward. The original's
  attachments are readable through a forward by reference, with no copy, while
  deletion, redaction and who may delete follow the original (the owner's decision,
  req-frzvt4kzpvsv); one deleted before the forward is not quoted, and a forward whose
  quote names attachments is refused while attachments are off and in an archived
  project (§8.5, §8.7, §8.8, §9.6, §12).
  CLI: `maity say a,b …` and `maity forward <seq> <to> [--note T | --note-file F]`, and
  how `wait`, `resume` and `messages` show a list and a quote (§13); the dashboard
  follows.
