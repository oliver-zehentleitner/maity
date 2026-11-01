### Added

- hub: a card's optional `needs` says which role it is for: a built-in role or a project role, set and changed like `label`, shown on the card, filtered with `needs=` on `GET …/tasks`; it routes nothing, and an open card's `needs` keeps a project role in use (§2.3, §6.4).
