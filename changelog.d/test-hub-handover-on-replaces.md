### Added

- Hub: the resume packet of an instance that `replaces` another carries `handover`
  (docs/api.md §5.2, §6.17): `{from, after, items, truncated}`, the events addressed to the chain
  it took over (its instances or the membership) that the chain left unacknowledged, instance-
  addressed ones first, at most 50. It comes at least once, until the instance has acknowledged
  its first packet's cursor, moves no cursor and wakes nothing. Migration: three columns on
  `credential`.
