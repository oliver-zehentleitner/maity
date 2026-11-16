### Removed

- ci: publish-image no longer has a hand start (`workflow_dispatch`); the hub
  image is built, signed and pushed only for a `v*` tag. An image from `main`
  was signed as `refs/heads/main`, which the documented `cosign verify`
  refuses, so it was never deployed. A failed tag build is started again with
  "Re-run jobs" on its own run (tsk-xz5rdgdy0srk).
