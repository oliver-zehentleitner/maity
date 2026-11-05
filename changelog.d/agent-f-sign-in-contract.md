### Changed

- docs/api.md §2.1, §2.6.7, §2.8.6, §18.4, §1.3: `POST /auth/login` takes the verified address
  (`{email, password, next?}`) instead of a handle. Only wrong passwords count, 5 in 15 minutes per
  account. Past that, the password signs in only from a known source of the account; elsewhere
  login answers `unauthenticated` with `details.reason` `email_link` or `password_paused`.
  The password change, the re-authentication and the address change count in buckets of their own.
  `maity-hub owner create --email` stores a verified address. The instance admin's verified address
  is not removed (`409 admin_address_required`). A second-factor check counts its attempt before
  comparing the code.
- web: words for `admin_address_required` and the reasons `email_link` and `password_paused`.
