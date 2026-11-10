### Added

- hub: registration, part 1 (`docs/api.md` §2.7, §16.4) — `GET`/`PATCH
  /admin/settings/registration` (mode `closed`/`allowlist`/`open`, domain and address
  lists, approval, terms, `max_new_accounts_per_hour`; environment, admin, default;
  `effective_mode` and `missing`; `mail_required` without complete, enabled mail);
  `POST /auth/register` refuses a closed instance before it reads the body
  (`registration_closed`) and an agent credential (`humans_only`), checks the address and
  the password, limits per source (`429`) and across the instance (the breaker), hashes
  the password and answers `202` for every request; after the answer it drops an
  allowlist miss, a blocked address and what exceeds the per-address limits, and
  otherwise keeps a pending registration for 24 hours (a new request from the same
  source voids the earlier one, at most five per address);
  `DELETE /admin/registrations/blocks/{address}`; `human.account_status` and the terms
  columns (migration `0047_registration`). No mail is sent yet: the confirmation link,
  the completion page, approval and `/auth/methods` come with the mail outbox
