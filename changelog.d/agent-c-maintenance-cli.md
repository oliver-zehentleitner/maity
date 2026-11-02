### Added

- cli: maintenance windows (§13, §16.12): on `503 maintenance` `maity wait` prints `Maintenance until <until> UTC: <text>` once, sleeps `Retry-After` plus a random 0–60 seconds and reads on with its cursor, never past `--timeout`; `maity runner serve` sleeps a window out the same way and says `hello` again; every other command prints `Maintenance until <until> UTC, try again then` and exits 7.
