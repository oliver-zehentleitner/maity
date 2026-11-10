### Fixed

- web: an upload the hub refuses as too large says the hub's own message and the file's size,
  not a fixed "larger than 10 MiB" (a 300 KB picture refused by a hub's 64 KiB body cap read as
  over 10 MiB)
