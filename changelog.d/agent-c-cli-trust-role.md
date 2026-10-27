### Added

- cli: trust × role (§2.3). `maity ask --action "METHOD PATH[?QUERY]" [--action-body FILE|-]`
  asks the owner's go for one call; `--on-request ID` on `maity api` and on the commands that
  make admin calls sends it as the signed `Maity-On-Request` header on their writes, and
  `maity api` then sends `--json FILE` byte for byte; `maity answer --on-behalf-of MEMBER`
  relays an owner's answer; `maity memory --role` and `maity memory add --role` read and
  write the role's memory (§19.2); `maity resume` shows trust and role for the agent and
  each member, and role memory; `trust:owner` and `trust:admin` in the help of `say` and `ask`

### Changed

- cli: the canonical string carries the `Maity-On-Request` line only when the header is sent,
  so every call without it is signed as before (§2.2, contract PR #425)
