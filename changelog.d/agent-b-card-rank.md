### Added

- hub: card order within a status column (`docs/api.md` §6.4, #135) — a card's `rank`, set by
  the hub only; `POST …/tasks/{id}/move` (`before`, `after`, or `to: top|bottom`, for
  `tasks:admin`, allowed in `freeze` and `fixes-only`, `project_closed` when accepted or
  archived) ranks only the cards the move needs and announces each with `task_updated`
  (`fields: ["rank"]`); `GET …/tasks` lists in the board's order (columns, rank, creation;
  closed cards by `closed_at`), paged after the last card shown, `order=updated` for the old order; the
  resume packet lists assigned cards in that order (migration `0014_card_rank`)

### Fixed

- hub: a `GET …/tasks` cursor holds only for the filters and the order of the page that
  gave it (`docs/api.md` §1.4); another filter set answers `invalid` (`cursor`)
