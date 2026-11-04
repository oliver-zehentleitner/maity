### Changed

- docs/api.md §2.6.5, §18.3: a sign-in alert (`session_created`) whose session, and every
  session it approved by device code, has ended may be marked read (not confirmed) from any
  session of the human in good standing. Before, only a session older than the sign-in could,
  so an alert stayed unread for 90 days once those sessions had ended. `email_address_changed`
  keeps the older-session rule. The dashboard's text for `not_earlier` names the second way
  out: end that session, then mark it read.
