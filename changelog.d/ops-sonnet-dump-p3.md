
### Changed

- deploy: `helm-upgrade.sh` takes `DUMP_TIMEOUT` (seconds, default 300) for the dump Job, the stub test pins that a failed Job is noticed at once, and the install guide reads the log of the pod that succeeded.
