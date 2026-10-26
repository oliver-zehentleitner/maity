### Added

- web: **inviting a person** (docs/api.md §3.4): on Members for a human with members:admin, the
  role, an optional address, the validity and a note, the link shown once with Copy, and the
  invitations with their state and Revoke; the invitation page `#/invite/<token>` says who invites
  to what and leads in by signing in or registering and back, then Join, with the hub's refusals

- web: **registration** (`#/register`, docs/api.md §2.7.1): address and password, then "check your
  mail", offered where the instance registers or an invitation admits; the login page offers
  **Create an account** there; an account waiting for approval sees that page alone
- web: signing in keeps a `next` (`#/login?next=…`, §2.6.5) through the password, the mail link and
  a device code, and goes on to it
