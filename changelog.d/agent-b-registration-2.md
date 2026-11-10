### Added

- hub: registration, part 2 (`docs/api.md` §2.7.1 step 6, §2.7.4, §2.7.5, §16.4) — the
  completion as one transaction under the address's lock: the admission checked again
  (mode, lists, a block, an admitting invitation), five wrong passwords void the link,
  handle and display name, terms accepted for the version shown, the hourly cap; then
  the account (`active`, or `pending` under `approval: operator`), every other link of
  the address voided and a fresh session. `GET /admin/registrations` and `POST
  …/{id}/approve` or `…/reject` `{reason}` for the instance admin (a rejection deletes
  the account and its sessions and blocks the address for 30 days; a late second
  decision is `invalid_transition`); an undecided account goes after 30 days. A pending
  account's session reaches only its own account and sessions (`account_pending`
  otherwise); `GET /me` carries `account_status` and `terms` (migration
  `0053_account_registration`). The link page, its mail, the address claim and the
  approval mails come with the notification settings.
