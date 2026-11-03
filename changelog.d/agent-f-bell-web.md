### Added

- web: the bell pins the unread security alerts on top (§18.2), with This was me for a sign-in
  this session may confirm and Mark read for the rest, and an Unread only filter.
- web: Mark all read takes security alerts after asking, names each one, and says which ones
  the hub left unread and why (§18.3).

### Changed

- web: This was me posts the session's own confirm (§2.6.5); reading an alert confirms nothing.
  An ended session has no This was me. Alerts that report no session get Mark read.
- web: the mail sign-in banner follows the sessions' good standing, not the alert's read flag.
- web: All notifications offers Mark read on a security alert where this session may mark it,
  as the bell does, and says an id the hub skipped instead of showing it read.
- web: Sessions says an alert is unread, not "not confirmed"; the security hint and that line
  fall back to English in the languages whose old text said the opposite.
