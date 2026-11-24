### Fixed

- hub: `GET /api/v1/auth/methods` needs TLS like the rest of the sign-in endpoints. Over plain
  HTTP from an address that is not loopback, without `MAITY_ALLOW_PLAIN_HTTP`, it answers
  `insecure_transport`.
- hub: changing the password voids every open device code of the person, including one the
  current browser started.
- hub: while sign-in by email link is turned off, a sign-in link page and its form answer
  `method_disabled`, the same answer for every token.
