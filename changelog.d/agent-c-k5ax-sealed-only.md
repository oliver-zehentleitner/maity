### Added

- hub: `MAITY_SEALED_VERIFIERS_ONLY` (default off; needs `MAITY_SEAL_VERIFIERS=1`)
  refuses a plain credential verifier: the credential answers as one whose sealed
  verifier the key does not open (401 `unauthenticated` or `signature_invalid`), and the
  hub does not start while a live plain verifier is left, naming the count and
  `maity-hub seal-verifiers`. Helm: `secretKey.sealedVerifiersOnly`, default `false`.
- hub: `maity-hub seal-verifiers --dry-run` counts and writes nothing, with or without
  the setting and the key.

### Changed

- hub: `maity-hub seal-verifiers` prints `sealed N, already sealed M, plain left K` per
  table and in all, and exits 1 while a plain verifier is left after the run.

### Security

- hub: with `MAITY_SEAL_VERIFIERS=1`, a plain verifier that verifies a call is sealed in
  that call's own update of the credential's last use (reseal on use). Operator note:
  both settings stay off on upgrade. To refuse plain verifiers, switch
  `MAITY_SEAL_VERIFIERS=1` on and roll it out, run `maity-hub seal-verifiers` (again after
  adding the key and after every rolling deploy) until it prints `plain left 0`, then set
  `MAITY_SEALED_VERIFIERS_ONLY=1` in a rollout of its own (docs/install/README.md,
  Backups).
