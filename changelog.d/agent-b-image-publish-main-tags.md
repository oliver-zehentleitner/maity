### Changed

- Image publishing (`publish-image.yml`): only a `v*` tag or `main` builds and pushes, in the
  `ghcr` environment; a manual run from another branch stops before it builds. Each pushed digest is
  signed with cosign, keyless, and the chart README shows how to check the signature with
  `cosign verify` before pinning a digest.
