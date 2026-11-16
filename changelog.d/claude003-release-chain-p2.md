### Changed

- ci: a hand-started publish-image build from `main` runs the same release
  gate as a `v*` tag build (`tools/release_gate.py`: ci-ok and hub-mariadb on
  that commit), and the image is built only after the gate passed
  (tsk-6zh891gy6cvz, point 2).
