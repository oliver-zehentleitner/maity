### Fixed

- web: the inbox no longer hangs on a large unread backlog: its activity list reads at most the four
  pages of 50 behind its 200 rows (More notifications leads to the rest), is drawn after the inbox
  instead of holding it back, and folds a burst of stream events into one refresh
