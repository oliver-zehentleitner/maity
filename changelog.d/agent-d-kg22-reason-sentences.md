### Changed

- web: a failure the dashboard reports is now one translatable sentence with the hub's reason where
  the language puts it, not a prefix with the reason glued after it; `make check` rejects a new
  prefix and a failure key without `{reason}`
