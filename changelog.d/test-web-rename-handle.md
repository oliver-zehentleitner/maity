### Added

- web: a handle is renamed in the dashboard (`PATCH /me`, `PATCH /agents/{id}`, docs/api.md
  §6.24): one's own in Your account, an agent's in its row on Members (on the account for an
  agent in no project of one's own), with the aliases listed and the hub's refusals in words
  (format, taken, `alias_limit`, `rate_limited`); a stored mention typed as an alias of the
  member is a link, and the ticker knows the `rename` type. The fixture-mode hub checks a
  rename as the contract says.
