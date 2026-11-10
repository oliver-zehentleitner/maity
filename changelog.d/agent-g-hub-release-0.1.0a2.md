### Changed

- hub: version 0.1.0a2, the release for deploy 6. From now on every deploy of maity.team is a
  release: a version bump as the last merge, then the maintainer's `v*` tag publishes the
  package on PyPI and the image (`hub/README.md` § Releases).
- deploy: Helm chart 0.1.1; its `appVersion`, the default image tag, is now `0.1.0a2` instead
  of the never-published `0.1.0.dev0`. A deploy that sets `image.digest` or `image.tag` is
  unaffected.
