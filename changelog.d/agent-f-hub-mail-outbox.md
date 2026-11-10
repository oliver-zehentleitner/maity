### Added

- hub: the mail outbox (`docs/api.md` §16.2, §18.5, §18.7) — a mail is a row in
  `mail_outbox`, written in the transaction that decides it, and a worker thread sends
  what is due with the settings in effect. Each outcome is counted in `mail_delivery`
  under its budget kind; security mail over its budget waits for the next hour, a
  sign-in answer over its budget is dropped, a failure of the instance's own setting is
  retried with backoff for 24 hours. A row is claimed by one conditional update that
  lapses after two minutes, so two processes never send the same mail. Rows that left
  the queue are deleted after seven days. `security_queued` in the mail settings counts
  the security mail waiting in the outbox. Migration `0062`.
