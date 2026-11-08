### Changed

- hub: a request's `while_open` defaults to the class: `wait` for a `consent`,
  `proceed_provisionally` for every other class (docs/api.md §7). A question with `task_id` no
  longer blocks the asker's card unless it says `while_open: wait` or is a consent. API callers
  that relied on the old default `wait` to block their card now send `while_open: wait`.

### Added

- cli: `maity ask --wait` sends `while_open: wait`, which blocks the card you hold with `--task`
  until the request is answered or withdrawn; without it, `ask --task` leaves the card as it is,
  except for a consent, which always waits.
