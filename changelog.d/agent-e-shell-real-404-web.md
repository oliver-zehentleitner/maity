### Changed

- web: an address that can never be a page (docs/api.md §16.11) shows "not found" to a
  visitor and to a signed-in reader alike, where a visitor got the sign-in form before. A
  word under the dashboard's own first words still keeps the sign-in.

### Fixed

- web: an address with an escape that does not decode shows "not found" instead of the
  page that could not load.
