### Changed

- web e2e (test only): the read limit round prints, for each burn, its attempt, the read that
  was refused and the Retry-After, so a CI log shows when the round signed in a second time;
  the first attempt's browser context is closed once, no longer a second time at the end.
- web: the context entry on the one role list is wrapped like the rest of the file
  (documentation only).
