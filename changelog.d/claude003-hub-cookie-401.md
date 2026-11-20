### Fixed

- hub: a `maity_session` cookie with a non-ASCII character is answered
  `401 unauthenticated`, as any unknown session is, instead of `500`; a
  sign-in (password, mail link or code, device code, registration) or a
  mail-link request that presents such a cookie treats it as no session
  instead of failing with `500`.
- hub: a malformed `maity_device` cookie (control characters, a tab or
  non-ASCII bytes in a value) no longer makes a sign-in answer `500` or
  comes back in the new device cookie; only values of the form the hub
  issues are kept.
