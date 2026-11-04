### Changed

- hub: tests: `NOT_ROUTED` in `test_contract_routes.py` lists one entry per line, sorted by method
  and path, with its reason as a comment on the same line, so parallel pull requests that add or
  remove an entry conflict there only when they change neighbouring lines; the entries themselves
  are unchanged.
