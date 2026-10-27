### Changed

- web: the header with the Maity lockup is part of `index.html`, so it shows before any script
  runs or the hub answers, and it stays when the page cannot load; the loader (48 px,
  "Loading Maity…", only after 300 ms) and the failure stand centred in the rest of the screen,
  on a phone as on a desktop. The failure is a calm block, no longer a red error box: the mark at
  rest, what does not work in plain words ("Maity can't reach its hub"), what to do, the reason
  under Details, a primary **Try again** and, where the session is gone, **Sign in again**
