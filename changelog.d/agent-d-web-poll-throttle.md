### Changed

- web: the dashboard reads `/me` (with the notification counts and the
  sign-in banner's sessions) every 60 seconds instead of 15, and a hidden
  tab skips it, the project's events and the chat lists until it is shown
  again; the hub's load from open tabs drops accordingly.
