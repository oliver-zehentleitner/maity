### Changed

- docs/api.md §6.4, §8.2, §8.4: agents may watch cards; watchers are woken by a status change, a
  report, or a message of the new type `update` on the card; a dependency watches its prerequisite
  automatically; watchers are reached through the read-time token `watchers:<task id>`.
