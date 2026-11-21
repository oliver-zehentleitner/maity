### Changed

- web smoke (test only): a Place arrow in the opened card's panel part that the board's late draw
  kept reads its neighbours at the click; a card that arrived beside the opened card with the late
  read is the one it is placed below. The case "a caller's own timeZone wins and makes its
  formatter once" runs on a page afresh with no account zone, so only `when` skipping the zone
  keeps it at one formatter (tsk-v7nshwn4vcfc, review of #2061).
