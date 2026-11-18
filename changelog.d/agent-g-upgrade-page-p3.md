### Fixed

- ci: `tools/upgrade_page.py check` reads an upgrade page as CommonMark does
  for headings and text: a byte order mark is dropped, `~~~` fences are
  fences, and a fence closes only with a run of the same character at least
  as long as the one that opened it, so a four-backtick block around a
  three-backtick one no longer turns the rest of the page inside out. A fence
  line with leading spaces makes the page refused: write code fences at the
  start of the line. A section that holds only an HTML comment
  counts as empty, and a heading inside a comment is no section; a comment in
  an indented code block (four spaces or a tab) is shown, so it counts as text
  (tsk-tzknz9zzy1m2).

### Added

- docs: `docs/upgrade/README.md` lists and links every version page, oldest
  first; each release pull request adds its line, and
  `tools/upgrade_page.py check` refuses a version page the list does not link.
  A page counts as linked only by a list line `- [version](version.md)` at
  the start of a line (also with `./` or a `#fragment`), not one in a code
  example or a comment;
  the error names the line to add (tsk-tzknz9zzy1m2).
