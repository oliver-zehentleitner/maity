### Changed

- deploy: the chart README's `cosign verify` accepts only an image signed by
  a `v*` tag's publish-image run; `refs/heads/main` is no longer in the
  identity, since every deploy is a release. An image built by hand from
  `main` still passes the release gate and is signed, but is not deployed
  (tsk-6zh891gy6cvz, point 2). A digest pinned from a hand-started run on
  `main` no longer passes the check: pin a release digest before the next
  upgrade.
