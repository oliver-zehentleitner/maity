### Fixed

- cli: `maity note add CARD -` reads the note from standard input instead
  of posting a literal `-`; `--body-file FILE` reads a UTF-8 file, using
  the same text-input checks as `say`, `ask` and `report`.
