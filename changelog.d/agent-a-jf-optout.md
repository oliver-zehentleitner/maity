### Changed

- docs/api.md §20: every member may opt out of a jour fixe series and back in
  (`PUT/DELETE …/jour-fixe/series/{jfs}/opt-out`, an agent also by its owner; not invited, not
  woken, not chosen as moderator, still reads the report); `too_few` now means fewer than two
  circle members to invite, so an anonymous answer never points at its author; an owner series'
  keepers are its owner alone, and the owner of an outside moderator agent does not read along.
  The report goes to the series' keepers and its recipient list, which members join and leave
  themselves (`PUT/DELETE …/series/{jfs}/report`), as an `inbox` item.
- docs/api.md §2.3, §6.4: a card claimed through a bridge is held by the served agent with
  `instance: null`, renewed by the bridge's calls; §1.3: a bridge's owner outside the project may
  end that connection; §12: which calls answer `204`.
