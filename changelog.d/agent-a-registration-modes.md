### Added

- docs: registration in the API contract (`docs/api.md` §2.7, §16.4) — the instance setting
  `registration` (`closed` by default, `allowlist` by domain and exact address, `open`), set by the
  instance admin or the environment, the environment winning; opening needs complete mail
  (`mail_required`). `POST /auth/register` with address and password answers the same `202` for every
  address and creates no account: a signed link (24 hours) leads to completion with the chosen
  password, handle, display name and optional terms (`{url, version}`, recorded). Approval
  `automatic` or `operator` (default): a pending account sees only that it is pending; the instance
  admin lists, approves and rejects with a reason (`/admin/registrations`), notified by the new
  `registration` kind. Rate limits per source, per address and source, per address, an instance
  breaker, a mail budget of its own and a cap on new accounts per hour. Plans and limits follow in
  a separate change.
