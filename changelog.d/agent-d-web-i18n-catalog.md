### Added

- Dashboard: a text catalog, `i18n/en.json` read with `Maity.t(key, values)` (one key per
  sentence, placeholders, plural forms through `Intl.PluralRules`), and `Maity.fmt` for dates and
  numbers through `Intl`; English only, built into `i18n/en.js` by `make fixtures`. `make check`
  checks the catalog's keys and their use, and holds each view's prose string literals at
  `tools/strings-baseline.json`, so new text goes through the catalog. The chat's instance choice
  is the first text read from it.
