### Fixed

- cli: `maity memory add -` reads the entry from stdin, as `say` does; it
  stored a literal `-` before.

### Added

- cli: `maity memory delete <id> [--reason R]` deletes an entry of your
  team's or role's memory.
