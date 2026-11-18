### Changed

- web: the browser end-to-end test (`web/tools/e2e.py`) runs every `maity-hub` command
  through one helper, and opens a watched page and fills the sign-in form through shared
  helpers instead of copies; what it does is unchanged.
