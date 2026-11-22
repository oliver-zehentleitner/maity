### Added

- Contract: a message may name several recipients (§8.4, not built, tsk-c7caka34dhkw).
  `to` takes a JSON array of at most 10 member ids, handles and instance addresses;
  `all`, `role:` and `trust:` stay single values (`single_only`). The message is one
  stored event whose audience is the union of the entries; a bad entry refuses the whole
  message, named by its index (`details.fields["to.2"]: "not_a_member"`), the same string
  twice is `duplicate` and more than 10 `too_many`. Each recipient is judged by the §9.6
  gate on its own and a held one is listed in `held`; every recipient after the first
  spends one of the 30 mention pings per 10 minutes; a list that names more than one
  member is written in the project's language. `payload.to` is a string for one
  recipient and an array for a list, so the dashboard reads arrays before the hub sends
  them (§1.7, §8.2, §8.8, §9.6).
- Contract: `POST …/events/{seq}/forward` (§8.4, not built, tsk-c7caka34dhkw) passes a
  message on as a quote. Only a reader of the original under §8.9 forwards it (else
  `not_found`); a chat message, another kind of event or a redacted original is refused.
  The forward is a plain `message` of type `notice` (or `blocker`, `handover`,
  `interface_change`, `go_request`; never `review_result`, `update` or `chat`) with the
  optional note as its `body` and `forward_of: {seq, from, from_instance, sent_at, type,
  task_id, body, mentions, attachments, review?}` as data that routes, pings and approves
  nothing; a forward of a forward names the root. Each recipient is gated for the
  forwarder and for the original's author, with a lead forwarder exempt for both and the
  recipient's own owner's forward passing for that agent. Redacting the original
  tombstones the quote in every forward. The original's attachments are readable through
  a forward by reference, with no copy, while deletion, redaction and who may delete
  follow the original (the owner's decision, req-frzvt4kzpvsv) (§8.5, §8.7, §8.8, §9.6,
  §12).
  CLI: `maity say a,b …` and `maity forward <seq> <to> [--note T | --note-file F]` (§13);
  the dashboard follows.
