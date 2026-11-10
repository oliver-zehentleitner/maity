### Fixed

- docs/api.md §15.13: local mode's `maity wait` long-polls between runs keep the session online
  and renew no claim lease, as §2.4 and §8.3 already say; the sentence said they renewed them. A
  `claim_lease_expiring` (not built yet) wakes that wait, and the run it starts renews with
  `maity claim renew` or releases the card.
