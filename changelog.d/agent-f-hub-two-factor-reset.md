### Added

- hub: the reset of a human's second factor without a recovery code (`docs/api.md` §2.8.3):
  `POST /admin/users/{id}/second-factor/reset {reason}` mails the human's verified address a link
  (24 hours, once, naming the factor's generation), and the page `/mail/second-factor-reset/{token}`
  resets it when the human presses its button, which deletes the enrolment and the recovery codes,
  ends every session and sends the next sign-in into enrolment. An admin alone never strips a
  factor; the admin's own account is `own_account`; no mail is `mail_not_configured`, no verified
  address `address_unverified`; the request needs the admin's own step-up. The operator has
  `maity-hub second-factor reset --handle` for the same effect at once.
