### Changed

- hub: the single-use rows of the sign-in link and the password reset (issue, use, void)
  and their request limits are implemented once, in `auth/single_use.py`, with the table
  as a parameter; `auth/email_links.py` and `auth/password_resets.py` keep their names as
  thin wrappers. The statements, locks and limiter names are unchanged, so no count starts
  again. Nothing changes for users.
