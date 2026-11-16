### Changed

- deploy: `deploy/runner/install-python.sh` installs uv from its release
  tarball, checked against the pinned `UV_SHA256`, instead of piping the
  installer into a shell; a different `UV_VERSION` needs its own checksum
  (tsk-6zh891gy6cvz, point 5).
- deploy: the k3s install guide takes the k3s installer from its release tag
  and checks its checksum, and installs cert-manager from the pulled chart
  archive after checking its checksum, with its five images pinned by
  digest; the images k3s bundles stay pinned by tag only
  (tsk-6zh891gy6cvz, point 5).
