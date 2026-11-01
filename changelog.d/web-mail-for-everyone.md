### Added

- Web: Admin → Sign-in shows the sign-in methods with their sources and turns the second factor
  to Mail for everyone with the code the hub mails to the admin (docs/api.md §2.6.6, §2.8.8),
  offered only while mail is ready, and with the advice to set up an authenticator app. The e2e
  walks the whole round on a hub of its own: the switch, the link, the code and a step-up by mail.

### Fixed

- Web: after Ctrl/Cmd+Enter the `@` list closes, so that it no longer stands over the emptied field
  and swallows the next Enter.
