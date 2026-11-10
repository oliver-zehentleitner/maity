### Added

- hub: `GET /projects/{owner}/{slug}/events/{seq}` reads one event by its
  `seq` (docs/api.md §8.9): the event list's own read bounded to that
  `seq`, so it answers exactly what `GET /events?after=<seq − 1>` would
  serve the caller, plus `conversation_id` only for a caller whose
  `…/messages` of that chat answers; a hidden event, one of another
  project and a `seq` nobody has all get the same `404 not_found`, and a
  `seq` that is no number `invalid` (`not_a_seq`). A bridge reads for an
  agent with `Maity-For`; a `for` query is `invalid` (`fields.for`).
  Reading acknowledges nothing, delivers nothing, does not count as
  listening and writes nothing (tsk-6g2h8dag2fkg).
