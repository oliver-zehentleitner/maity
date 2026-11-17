### Security

- hub: mails for the second factor have a budget of their own (`second_factor_max_per_hour`,
  `MAITY_MAIL_SECOND_FACTOR_MAX_PER_HOUR`, default 60), with `second_factor_sent_last_hour` and
  `second_factor_dropped_last_hour` in the admin view; the web admin shows the setting
- web: the mail settings show a second last-hour line for the kinds with a budget of their own:
  verification, invitation and second-factor mails sent, second-factor mails dropped, and
  verification or invitation mails waiting
- hub: a per-recipient cap on sign-in, reset and registration mails, counted in source networks
  (IPv4 address, IPv6 /64): 5 networks per hour and 20 per day per address, each network's
  further mails held by its pair limit, and at most 50 mails in any hour and 200 in any day per
  address; one to four networks cannot stop the owner's mail (but for the moment two first
  requests of one network run at once), and the answer stays the same
- hub: rate limits per source address count an IPv6 client by its /64
- hub: the in-process rate limiter forgets idle keys without scanning them all
- hub: address verification mails have a budget of their own (`verification_max_per_hour`,
  `MAITY_MAIL_VERIFICATION_MAX_PER_HOUR`, default 60), so security mail never waits behind them;
  a human asks for at most 3 an hour and 10 a day, and one address has places for 3 asking
  accounts an hour and 10 a day and gets at most 9 in any hour and 100 in any day
- hub: invitation mails have a budget of their own (`invitation_max_per_hour`,
  `MAITY_MAIL_INVITATION_MAX_PER_HOUR`, default 60), queued over it like security mail
- hub: `POST /me/deletion` takes at most 3 requests per human an hour; a fourth answers
  `rate_limited`
