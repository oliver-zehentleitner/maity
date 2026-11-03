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

- docs/api.md §5.3: answering the digest's `seen` records, for the answering human, what the
  request's last version showed of each listed instance: its `last_seen_at` and the `since` of a
  listed episode; an away instance stays silenced for its owner while it has made no call since
  such a record, or while that episode runs. Records add up; a new request comes only for
  an instance not silenced and lists every away instance. A table lists the cases: moving a
  stalled holder's cards or assigning one back does not ask again, a crash after work does, and
  an instance that became away only after an answer, one that called between the request's last
  version and the answer and then stopped anew, and one whose profile changed owner are filed.
