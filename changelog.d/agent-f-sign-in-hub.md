### Changed

- hub: `POST /auth/login` takes the verified address (`email`) instead of a handle (docs/api.md
  §2.1). Wrong passwords count per account, 5 in 15 minutes; past that, only a source the account
  completed a sign-in from in the last 30 days keeps the password, and every other source is told
  `email_link` or `password_paused`. The hub keeps a keyed fingerprint of such a source in the new
  table `known_source`, never the address; an hourly sweep deletes it 30 days after its last
  sign-in, and it goes with the account. The
  password change, the re-authentication and the address change count wrong passwords in buckets
  of their own, and every bucket takes its place before the password is compared. A second-factor
  check counts its attempt before comparing the code (§2.8.6).
- hub: `maity-hub owner create` needs `--email` and stores it as the account's verified address;
  `maity-hub quickstart` asks for it, or takes `--email`. A hub whose instance admin has no
  verified address logs a warning at start, and the instance admin's verified address is replaced,
  never removed (`409 admin_address_required`, §18.4).
