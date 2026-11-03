### Added

- docs/api.md §6.5, §8.2: `holder_stalled` when a limit starts for an agent that holds cards, when
  a holder loses its session to a revocation that is not a replacement, or when it stops listening;
  and `claim_expired`, one per holder and worker pass, naming the claims whose leases ran out.
  Both name the cards and the reason (a revocation first, then a running limit), wake the member
  the agent reports to when it is an agent, are never wake-relevant for the holder, and release
  nothing.
- docs/api.md §5.3, §6.2, §18.1, §18.4: the owner's hourly digest also lists stalled holders,
  instances that hold cards and have made no call for `not_listening.minutes`, a crashed harness
  included; they count for filing, rewriting, withdrawal and `seen` like episodes; the bell's
  `agents_not_listening` record gains `holding`, and its title follows the request's.

### Changed

- docs/api.md §5.3: answering the digest's `seen` silences every entry it listed for as long as
  that entry lasts, adding up over answers; a new request comes only for an entry no answer
  silenced and lists every away instance, so an instance that becomes away only after an answer is
  filed, even when it stopped before it; an entry lasts until the
  instance is back, so moving a stalled holder's cards does not ask again.
