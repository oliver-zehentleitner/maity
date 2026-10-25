### Changed

- hub: the mail outbox claims each row before it sends it (one
  conditional UPDATE, a two-minute claim that lapses if the process dies),
  and the notification mailer writes its state insert-if-absent, so two
  hub processes never send a mail twice; rows being sent count towards
  the budgets and are never forgotten by the clean-up.
