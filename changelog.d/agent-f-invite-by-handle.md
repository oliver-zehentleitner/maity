### Added

- hub: a project invitation can name a person by `handle` instead of an address (§3.4). It is
  bound to that account, answered in the person's inbox as a personal consent request (`go`
  accepts, `no` declines with the new `declined_at` and `invitation_declined`), and has no link.
  Any approved, active person qualifies, as for a contact (§6.29); every other handle is refused
  (`unknown`, `not_a_person`, `member`, `invited`, `with_address`, `format`), each refusal counts
  against the project's invitation rate, and a person gets at most ten such invitations a day. The invitation list shows
  `handle` and `declined_at`, and the invitation events say `handle_bound`.
