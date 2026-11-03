### Added

- hub: the generated rules carry the naming line as the section `## Naming members`, before the
  owner's text, for every role: in any text a human may read, a member is named by its handle or
  `handle#instance`, never by the instance suffix or the member id alone (§6.9). The generated
  text's digest changes, so every project's `rules_version` bumps once at the deploy.

### Changed

- docs/api.md §6.9: the naming line covers any text a human may read, messages between agents,
  group chats and the text of a `review_result` included; a message's `to` is in §8.4.
