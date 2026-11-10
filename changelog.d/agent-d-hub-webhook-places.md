### Fixed

- hub: a forge webhook request refused for a full slug bucket no longer uses up a place of its
  source address, and a verified delivery gives back its own two places, not the newest ones (a
  body read that outlasted the window freed someone else's)
