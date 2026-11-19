### Fixed

- ci: `tools/upgrade_page.py check` ends a line only at a line feed, a
  carriage return or both, as CommonMark does. It split with Python's
  `str.splitlines()`, which also breaks at U+2028, U+2029, U+0085 and a few
  control characters, so a fence after such a character could hide a
  duplicate section and the page passed (tsk-dest4a10zfw9).
- tools: `tools/overlap.sh` and `tools/coverage.sh` read an origin URL's
  `file://` scheme in any case: `FILE://localhost/...` named the loopback
  proxy and so github.com, where it names no server and stops the check
  (tsk-dest4a10zfw9).
- ci: `tools/upgrade_page.py check` refuses a fence line with one to three
  leading spaces; four or more (or a tab) is an indented code block and
  passes. The entry from tsk-tzknz9zzy1m2 said "a fence line with leading
  spaces" (tsk-dest4a10zfw9).
