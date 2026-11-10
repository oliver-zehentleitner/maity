### Added

- docs/api.md §8.9: `GET /projects/{owner}/{slug}/events/{seq}` reads one
  event by its `seq`, with exactly the readable set of `GET /events` and its
  shape plus `conversation_id`; a hidden event answers `not_found` as a
  missing one, every way to tell them apart listed and closed; the
  dashboard links `seq 68216` and `seq-68216` in text by shape, opens the
  event where it lives and shows "not visible" on a `404`; the §12 index
  row. Contract only; hub and dashboard follow (tsk-6g2h8dag2fkg).
