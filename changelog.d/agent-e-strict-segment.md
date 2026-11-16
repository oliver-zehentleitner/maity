### Fixed

- hub: a path segment with a valid escape beside a `%` that starts none (`%61b%zz`) stays
  whole as sent when the hub decides whether an address can never be a page, as the
  dashboard reads it (docs/api.md §16.11).
