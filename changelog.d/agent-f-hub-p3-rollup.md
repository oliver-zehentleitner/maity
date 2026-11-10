### Changed

- hub: the product line's pages under the hub's `default-src 'self'` policy (the mail link
  pages, the sign-in link page, the join page and the `503` maintenance page) allow its one
  style block by its hash in `style-src`, never `'unsafe-inline'`; the `503` page answers with
  that policy and `Referrer-Policy: no-referrer` too, since it can stand in for a path with a
  token in it. This came with the product line (#1291), whose entry did not name it.
