### Added

- docs: the README in German, Spanish, French, Italian, Japanese, Korean, Dutch,
  Portuguese and Simplified Chinese (`README.<lang>.md`), with a language line
  in every version.
- ci: `tools/readme_sync.py` fails when a translation of the README is missing
  or lacks a heading of `README.md`, so a new section does not go stale in the
  translations unnoticed.
