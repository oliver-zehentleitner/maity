### Security

- hub: mails for the second factor have a budget of their own (`second_factor_max_per_hour`,
  `MAITY_MAIL_SECOND_FACTOR_MAX_PER_HOUR`, default 60), with `second_factor_sent_last_hour` and
  `second_factor_dropped_last_hour` in the admin view; the web admin shows the setting
- hub: a per-recipient cap on sign-in, reset and registration mails: 5 per hour and 20 per day per
  address, whichever sources ask; the answer stays the same
- hub: rate limits per source address count an IPv6 client by its /64
- hub: the in-process rate limiter forgets idle keys without scanning them all
- hub: address verification mails have a budget of their own (`verification_max_per_hour`,
  `MAITY_MAIL_VERIFICATION_MAX_PER_HOUR`, default 60), so security mail never waits behind them;
  a human asks for at most 3 an hour and 10 a day, and one address gets at most 3 an hour and
  10 a day from all accounts together
- hub: invitation mails have a budget of their own (`invitation_max_per_hour`,
  `MAITY_MAIL_INVITATION_MAX_PER_HOUR`, default 60), queued over it like security mail
- hub: `POST /me/deletion` takes at most 3 requests per human an hour; a fourth answers
  `rate_limited`
