### Added

- hub: `GET /me/conversations` (§9.3, "Across projects"): the conversations of every project the human is an active member of as one list, newest activity first and then by project name and id, with `observed`, paging and `totals` over all items. It reads all projects together in a fixed number of statements (tsk-45vs1hdzswjs).

### Fixed

- hub: the bell's `counts.chat` (§18.2) counted only direct conversations; it now counts the unread messages of the group chats the human takes part in as well (observers nothing), by the same function as `totals.unread` of `GET /me/conversations`, so the two are equal (tsk-45vs1hdzswjs).
