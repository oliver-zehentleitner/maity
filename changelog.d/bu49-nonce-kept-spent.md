### Fixed

- hub: a signed request refused after its nonce was spent (an isolated agent, a read past the
  limit, another project, a bridge or runner refusal) keeps the nonce spent on PostgreSQL too,
  so the same request sent again is `nonce_reused` on every engine.

### Security

- hub: a `Maity-On-Request` value of a form the hub never issues as a request id is refused as
  `signature_invalid` before the canonical string is built, so its line never matches the
  `Maity-For` line.
