### Changed

- hub: the mail-text helpers (`defang`, `quoted`, `subject_line`) moved from
  `notifications/mailer.py` to `mail/text.py`. Invitation, registration and
  second-factor-reset mails import them from there instead of from the
  notification mailer, without the function-local imports. What a mail says
  is unchanged.
