### Fixed

- web: the end-to-end run waits for the members page before opening the
  settings menu, so a late re-render no longer takes the menu away mid-click.
- web: on Runners, a periodic refresh still in flight when an action reloads
  no longer answers last and undoes what the action shows (a revoked runner
  shown as active again).
