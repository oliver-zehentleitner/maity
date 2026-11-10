### Fixed

- web: while the next view is read and drawn, the one being left takes no
  click or key (`inert`); a Revoke there no longer leaves the new view
  showing the runner as active. The end-to-end run also waits for `#/all`
  before it opens Runners again.
