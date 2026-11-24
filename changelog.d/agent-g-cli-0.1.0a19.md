### Changed

- cli: version 0.1.0a19 for PyPI. It brings three runner fixes to PyPI: a Codex placement keeps
  listening across `maity wait` (`background_terminal_max_timeout`, #2150), sessions get
  `SHELL`, not the account's nologin shell (#2160), and `maity report` works in a placement
  behind a proxy (#2151); the other CLI changes since 0.1.0a18 are in their own entries.
