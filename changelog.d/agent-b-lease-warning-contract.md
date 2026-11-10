### Added

- docs/api.md §6.5, §8.2, §2.4, §5.3: the lease warning (not built yet). The hub's minute worker
  sends a holder `claim_lease_expiring` when its leases are at most
  `min(300, max(120, lease_seconds / 10))` seconds from running out (the tenth rounded down to
  whole seconds), once per lease period. The event wakes the holder and never makes it not
  listening. `POST …/claims/renew` renews every claim of the calling instance and answers with the
  new leases. The events long-poll still renews nothing.
- docs/api.md §13: `maity claim renew [card]`, where a card only picks the line printed, and a
  `maity wait` line per card a `claim_lease_expiring` names (not built yet).
