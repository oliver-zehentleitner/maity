### Fixed

- hub: a landing page near its 64 KiB Markdown limit is no longer refused with 413
  (`docs/api.md` §16.7). `PATCH /admin/settings/landing` alone takes a request body of up to
  256 KiB, since JSON escaping grows the Markdown on the wire; the Markdown limit stays 64 KiB
  decoded, and every other endpoint keeps 64 KiB.
