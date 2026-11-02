### Changed

- docs/api.md §18.4, §18.5, §2.6.5, §16.2: mail notifications for mentions and chat default to a
  daily digest, inbox and security stay immediate; a new `weekly` mode with `weekly_on`; every kind
  takes every mode, for security the alert of a new sign-in; the second factor's warnings, the
  old-address notice, the deletion confirmation, the registration decision and the transactional
  mails go out at once whatever the mode; a kind the human never set follows the current default.
