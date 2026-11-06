### Changed

- Dashboard: a page switch draws the next view from the session, `/me` and the project it read last
  (for at most 60 seconds, dropped after any write of the tab) and reads them again behind the view,
  so a switch waits for two round trips instead of four.
- Dashboard: while the next view loads, a bar along the top shows that the click was taken, and the
  view being left is dimmed and marked busy.
