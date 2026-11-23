### Fixed

- cli: `maity report` works in a placement that reaches GitHub only through a proxy. Under
  a placement, maity's own git now keeps the session's proxy variables (`HTTPS_PROXY`,
  `HTTP_PROXY`, `ALL_PROXY`, `NO_PROXY`, either case), and still no trust-root or other git
  variable. A `git ls-remote` that runs and fails no longer aborts the report: the card's
  linked pull request with the local head, read through the hub's probe, stands in, and
  without one the failure stays an error.
