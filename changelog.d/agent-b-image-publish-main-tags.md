### Changed

- Image publishing (`publish-image.yml`): only a `v*` tag or `main` builds and pushes, in the
  `ghcr` environment; a manual run from another branch stops before it builds. Each pushed digest is
  signed with cosign, keyless, in a job of its own that alone may request an OIDC token, and the
  chart README shows how to check the signature with `cosign verify` (v3 or later) before pinning a
  digest.
