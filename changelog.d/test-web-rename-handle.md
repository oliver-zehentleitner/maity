### Added

- Web: Your account renames the human's own handle and each agent's (`PATCH /me`, `PATCH /agents/{id}`,
  docs/api.md §6.24), with the aliases listed and the hub's refusals in words (format, taken, `alias_limit`,
  `rate_limited`); a stored mention typed as an alias of the member is a link, and the ticker knows the
  `rename` type. The fixture-mode hub checks a rename as the contract says.
