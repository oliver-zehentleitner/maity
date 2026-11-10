### Added

- deploy: `deploy/scripts/helm-upgrade.sh` runs `helm upgrade` with the hub stopped, so a
  migration that alters busy tables no longer deadlocks against the serving pod (0060 did on
  PostgreSQL), and scales the hub back on any exit. The chart README says when to use it.
