### Changed

- hub: an outsider's agent (trust `outside`) keeps no areas or capabilities
  and reports only to its owner, or to no one, also after a member change:
  `PATCH …/members/{id}` that names anything else is refused as the join
  refuses it (`forbidden`, `member_join_limit`, `details.field`), whoever
  asks, and a consent answered `go` on such a change writes nothing.
