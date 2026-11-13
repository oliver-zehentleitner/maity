### Changed

- deploy: `deploy/scripts/helm-upgrade.sh` verifies the image signature
  before it deploys: it renders the upgrade with the same arguments, and
  every image must be pinned by digest and pass `cosign verify` (v3 or later)
  with the identity from the chart README, or nothing is changed; an image
  key in a form the script does not read (a flow mapping, a block scalar)
  stops it too. A missing
  cosign stops it too; `NO_SIGNATURE_CHECK=1` skips the check for an image you
  built yourself. Upgrade note: install cosign v3 on the host that deploys
  (tsk-6zh891gy6cvz, point 3).
