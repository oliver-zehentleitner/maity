### Changed

- cli: the runner logs a warning for every refused join: a refused pickup
  gives `<placement>: warning: join pickup refused: <code> (reason …, why …)`,
  so a `pickup_not_allowed` names its cause (`credential_issued`,
  `handle_taken`, `creator_lacks_authority`, …), and a refused exchange gives
  the code alone. Values not in the form of a code are shown as `-`. The
  placement's report is unchanged (`join_failed` with the code).
