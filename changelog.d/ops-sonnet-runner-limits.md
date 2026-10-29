### Changed

- ci: the self-hosted runner services are capped: `CPUQuota=150%`, `Nice=10`, low CPU/I-O weight, `MemoryMax=4G`,
  `PYTEST_ARGS=-n 2` per instance, and a drop-in for the runner user's slice (4 of 8 cores, 8 GB, no swap) that also
  limits the rootless Docker. The first run of three uncapped services took the machine down. The README says to
  start with one service.
