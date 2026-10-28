### Added

- hub: project setup options (`setup` on `POST /projects`: Keep the Why init, Keep the Why badge, Maity badge) and the `setup` cards the hub opens for them when the project has a repository, at creation or when it is first set; `maity_badge` also opens the project badge; migration 0069 (§6.21)
- hub: the resume packet's `setup` lists the setup cards that still wait, with their holder (§5.2)

### Changed

- hub: `kind: setup` is a card kind only the hub creates; `POST …/tasks` refuses it
