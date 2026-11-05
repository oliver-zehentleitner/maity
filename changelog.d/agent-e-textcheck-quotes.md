### Changed

- cli: `maity say --type review_result` also refuses a quote that is not at the head: four words
  or more in `"…"`, `“…”` or `„…“`, tied to one file by a file and line right next to it or by a
  section about that file, must stand verbatim in that file (docs/api.md §8.4, form 4).
