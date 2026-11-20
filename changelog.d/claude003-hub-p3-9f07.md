### Fixed

- hub: the app shell sends `Referrer-Policy: no-referrer` at every address the
  dashboard draws as an invitation, also with empty or escaped segments such as
  `//invite/{token}` and `/%69nvite/{token}`; before, only a path starting with
  `/invite/` got it.
- hub: the input edges on the hub's own door pages (such as the registration
  link page and the join page) have 3:1 contrast in the light theme:
  the fallback edge colour is the dashboard's light `--field` (#7d8691) instead
  of #8a939d (2.89:1 on white).
