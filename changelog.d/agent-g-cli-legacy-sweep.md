### Fixed

- cli: `maity task create --body -` reads the body from stdin; it sent a literal `-` before.

### Removed

- cli: `maity chat` and `maity chats` no longer read a direct conversation listed without `id` and
  `kind`, and `maity ticker post --help` no longer describes a hub without the ticker
  (alpha, no compatibility layers).
