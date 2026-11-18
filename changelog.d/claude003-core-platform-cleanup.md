### Changed

- hub: one nullable RFC 3339 formatter (`clock.rfc3339_or_none`, `views.ts` now that
  function) instead of two private copies and twenty inline ones; one presence table
  (`seen.ONLINE`, `seen.AWAY`, `seen.presence_by_age`) for members, instances, runners,
  the landing counters and the statistics; one owner join in `namespace`, `name_of` and
  `aliases_of` reading through the batch readers; the statistics' date conversion written
  once and its legacy-schema guards gone. No answer changes.
