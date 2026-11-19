### Fixed

- web e2e: the visitor page checks wait for each settled value before they read it once: the
  person's and agent's hero stacked on a phone, the project hero's dark zone and its one column
  on a phone, the columns of the projects, agents, figures and team grids, the tab bar
  scrolling on a phone, the frame's stylesheet listed and the page no wider than the window.
  A read right after the page is drawn no longer sees the view before its stylesheet applies
  now and then. A page that never gets there still fails with the same message as before
  ("the hero stacked is …", "… project columns", and so on). No change to the dashboard itself.
