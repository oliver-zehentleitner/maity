### Changed

- web: the dashboard reads `/me` (with the notification counts and the
  sign-in banner's sessions) every 60 seconds instead of 15 and the open
  project's events every 15 seconds instead of 5; a hidden tab skips them
  and the chat lists until it is shown again, then catches up within 5
  seconds.
