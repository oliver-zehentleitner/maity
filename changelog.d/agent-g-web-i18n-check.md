### Added

- `web/tools/check.py` checks translated catalogs: placeholders in both directions, plural forms per language, keys English lacks. It keeps which English text each translation follows, `--missing <lang>` lists what is missing or out of date, and `make release-check` fails on either.
