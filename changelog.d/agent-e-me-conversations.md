### Added

- hub: `GET /me/conversations` (§9.3, "Across projects"): the conversations of every project the human is an active member of as one list, newest activity first and then by project name and id, with `observed`, paging and `totals` over all items. It reads all projects together in a fixed number of statements (tsk-45vs1hdzswjs).

### Fixed

- hub: the bell's `counts.chat` (§18.2) and `totals.unread` of `GET /me/conversations` are computed by one function and are equal; the bell reads its chats in a fixed number of statements per request instead of two per direct chat and per group chat (tsk-45vs1hdzswjs).
