### Added

- web e2e: the second step of a sign-in with TOTP against the real hub (on the second hub): after
  the password the page asks for the app's code and shows nobody as signed in, then the dashboard

### Changed

- web e2e: the TOTP step-up takes the current step when the confirmation comes late; the rounds
  after the scenario report their trace on a failure too
