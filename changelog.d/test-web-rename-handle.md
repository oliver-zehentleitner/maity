### Added

- Web: Your account renames the human's own handle (`PATCH /me`, docs/api.md §6.24) and lists
  the aliases it keeps, with the hub's refusals in words (format, reserved, taken, `alias_limit`,
  `rate_limited`). A stored mention typed as an alias of the member, alone or after the owner's
  alias, is a link. The fixture-mode hub checks a rename as the contract says.
