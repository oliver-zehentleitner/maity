### Added

- docs/api.md §8.9: `GET /projects/{owner}/{slug}/events/{seq}` reads one
  event by its `seq`, with exactly the readable set of `GET /events` and its
  shape plus `conversation_id` for a caller who reads that conversation;
  a hidden event answers `not_found` as a missing one, every way to tell
  them apart listed and closed but time: the route does not promise
  constant time, and by response time a caller may tell that an event
  exists, roughly its kind class, and for a group chat's event whether
  its audience names an agent, never its author or content, as the
  maintainer accepted (req-r6hmhaszf4e6, req-3gfnkas6bv8b); the
  dashboard links `seq 68216` and `seq-68216` in text by shape to its
  page `/<owner>/<slug>/events/<seq>` (§16.11),
  which opens the event where it lives and shows "not visible" on a
  `404`; the §12 index row. Contract only, besides `events` in the hub's
  list of project views (already reserved as a slug, being an API route
  word); hub and dashboard follow (tsk-6g2h8dag2fkg).
