### Fixed

- deploy: the backup Job fails when `pg_dump` fails (it reported "Complete" and left an empty `.part`): one command per line, up to five tries, a non-empty
  file required, leftovers removed. `helm-upgrade.sh` also stops when the dump Job's log contains `pg_dump: error`.
