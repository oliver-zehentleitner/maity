### Fixed

- cli: on Windows a `./maity-files/` others can reach is refused, and stdin in another encoding is refused instead of reaching the hub altered. `--join-file` takes a byte order mark and says when a file is not UTF-8.
