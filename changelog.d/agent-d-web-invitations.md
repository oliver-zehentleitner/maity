### Added

- web: **registration** (`#/register`, docs/api.md §2.7.1): address and password, then "check your
  mail", offered where the instance registers or an invitation admits; the login page offers
  **Create an account** there; an account waiting for approval sees that page alone
- web: signing in keeps a `next` (`#/login?next=…`, §2.6.5) through the password, the mail link and
  a device code, and goes on to it
