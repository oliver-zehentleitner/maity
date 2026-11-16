### Fixed

- hub: a person's or project's website with a Unicode host is refused
  (`format`) before the host is lower-cased; a host with U+212A (KELVIN SIGN)
  was accepted as its ASCII lower-case, `k` (docs/api.md §16.9).
