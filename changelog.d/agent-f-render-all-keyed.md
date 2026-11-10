### Changed

- docs/api.md §16.9: the cleanup of a full render pass decides each page whose target went with a
  read of that one target, by the same rule as the list of targets. Before, it read every target
  of the kind again for each such page, so a backlog of removed targets cost candidates × targets.
