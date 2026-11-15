### Added

- hub: `MAITY_SEAL_VERIFIERS` (default off) makes sealing the verifiers of agent and runner
  credentials at rest opt-in; it is switched on later in a separate step (`docs/api.md` §2.2).
  With it on and `MAITY_SECRET_KEY` set the hub seals new verifiers as 0.1.0a6 did; off, new
  verifiers are stored plain as before 0.1.0a6. Sealed verifiers are read either way while the
  key is set, so switching it off again locks no one out. On without the key the hub does not
  start. The startup log line that counts plain verifiers says whether sealing is on.
- hub: `maity-hub seal-verifiers` seals the verifiers stored before sealing was switched on.
  It runs only with `MAITY_SEAL_VERIFIERS=1` and the key set, leaves sealed rows as they are
  (a second run seals nothing) and prints how many it sealed.
- deploy: the Helm value `secretKey.sealVerifiers` (default `false`) sets
  `MAITY_SEAL_VERIFIERS`; it needs `secretKey.existingSecret`.

### Changed

- hub: the migration `20261114020000_sealed_verifiers` only widens the verifier columns; it no
  longer seals stored verifiers when run with the key. Revision ID and down_revision are
  unchanged. This is safe: the deploy of 0.1.0a6 was cancelled, so the instances move from
  0.1.0a5 to 0.1.0a7 and run only this form. A database that already ran the 0.1.0a6 form has
  the revision recorded and does not run it again, and its sealed rows keep working because
  the hub reads sealed verifiers whether sealing is on or off.
