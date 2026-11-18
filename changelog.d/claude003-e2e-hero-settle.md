### Fixed

- web e2e: the visitor page checks wait for the hero's settled layout and colour before they
  read them once: the person's and agent's hero stacked on a phone, the project hero's dark
  zone and its one column on a phone. A read right after the page is drawn no longer sees the
  view before its stylesheet applies now and then. A hero that never gets there still fails
  with "the hero stacked is …", "the hero is not the dark zone" or "the hero is not stacked".
  No change to the dashboard itself.
