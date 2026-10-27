### Changed

- docs/api.md §6.4, §8.2, §8.4: agents may watch cards; watchers are woken by a status change or a
  message of the new type `update` on the card; a dependency watches its prerequisite
  automatically; watchers are reached through `watchers:<task id>`, fixed when the event is written and never served.
