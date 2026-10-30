### Added

- docs/api.md §1.1, §3.4, §16.11: a person's invitation goes out over the join host too. Its link
  there is `https://<join host>/i/<token>`, a `302` to the public host's `/invite/<token>` that does
  not look the token up; `via` picks the host per invitation, as for join links, and defaults to the
  join host when one is configured.
