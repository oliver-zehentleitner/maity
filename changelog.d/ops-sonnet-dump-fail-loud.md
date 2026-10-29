### Fixed

- deploy: the backup Job fails when `pg_dump` fails (it reported "Complete" and left an empty `.part`): one command per line, up to five tries, a non-empty
  file required, leftovers removed. The script ends with `dump ok: <file> <bytes>`, and `helm-upgrade.sh` goes on only when the log of the succeeded pod has that line.
