### Fixed

- cli: the check before sending refuses a credential followed by a non-ASCII letter
  (`mty1.<id>.<secret>é`, `ß`, `日`) as the hub does; its word boundary was Unicode-aware, so
  such a request was sent and the hub refused it with `credential_in_payload` and revoked a
  real credential.
