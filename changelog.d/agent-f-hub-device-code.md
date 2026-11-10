### Added

- hub: device codes (`docs/api.md` §2.6.2) — `POST /auth/device-codes`
  on a signed-in session, `GET …/{id}` with a long-poll, `…/approve` by
  number matching, `…/deny` and `DELETE`; `POST /auth/device-login`,
  its long-poll and `…/complete` for the new browser, bound by the
  `maity_pending` cookie; the account shown only after the approval; one
  code, one session. Codes die with their session and when the method is
  switched off. The limits of §2.6.4, including the instance-wide
  wrong-code breaker. Migration `0028`.
- hub: `GET /auth/methods` (§2.6.1).
- hub: the device cookie `maity_device` at every completed sign-in, for
  the approval dialog's "first sign-in from this browser" (§2.6.5).
