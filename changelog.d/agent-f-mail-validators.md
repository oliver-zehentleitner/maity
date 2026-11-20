### Changed

- hub: the mail settings are checked by one set of validators in `mail/environment.py`
  (`tls_refused`, `ascii_secret`, `sender_ok`), for the environment, the instance admin's
  `PATCH /admin/settings/mail` and the settings in effect; before, each check was written
  two or three times. The answers, error codes and startup messages are unchanged.
  Nothing changes for users.
