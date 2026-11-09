### Added

- hub: a project invitation can name a person by `handle` instead of an address (§3.4). It is
  bound to that account, answered in the person's inbox as a personal consent request (`go`
  accepts, `no` declines with the new `declined_at` and `invitation_declined`), and has no link.
  Every other handle is refused (`unknown`, `not_a_person`, `member`, `invited`, `with_address`,
  `format`), and a person gets at most ten such invitations a day. The invitation list shows
  `handle` and `declined_at`, and the invitation events say `handle_bound`.
