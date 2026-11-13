### Changed

- deploy: `deploy/runner/install-python.sh` installs uv from its release
  tarball, checked against the pinned `UV_SHA256`, instead of piping the
  installer into a shell; a different `UV_VERSION` needs its own checksum
  (tsk-6zh891gy6cvz, point 5).
- deploy: the k3s install guide takes the k3s installer from its release tag
  and checks its checksum, and installs cert-manager from the pulled chart
  archive after checking its checksum (tsk-6zh891gy6cvz, point 5).
- ci: `kind-smoke.sh` runs PostgreSQL by the digest `ci.yml` pins, not by the
  tag `postgres:17` (tsk-6zh891gy6cvz, point 5).
