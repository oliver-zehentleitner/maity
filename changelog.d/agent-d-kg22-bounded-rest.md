### Changed

- hub: a mail's defanged text (docs/api.md §18.5) and the browser named from a `User-Agent`
  (§2.6.5) are read in time bounded by the text's length, with the same result as before.
- web: the Markdown renderer reads a long line in time bounded by its length: inline code finds
  each closing backtick run once per line, and a link's target holds no `[`, as in the hub's
  renderer (§16.7).
