### Fixed

- hub: an item of a role rule's `checklist` now refuses every character the plain-text rule
  refuses (§1.7.1), a lone surrogate, a private-use character and an unassigned code point
  included, with the reason it gave before, `multiline`; a lone surrogate there was a 500
  (docs/api.md §6.1, tsk-381tbxvqydg3). A checklist stored before is kept as it is.
