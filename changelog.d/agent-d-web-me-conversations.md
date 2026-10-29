### Changed

- web: `#/chats` reads every project's chats in one request (`GET
  /me/conversations`, docs/api.md §9.3) instead of one per project; a hub
  without it is read project by project as before.
