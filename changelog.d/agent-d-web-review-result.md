### Added

- Dashboard, **Messages**: a review result (§8.4, #745) shows its verdict, what was reviewed, the
  commit at its short head (linked on GitHub or GitLab) and the places the reviewer read, as
  `path:line` or "removed" with the quoted line, folded after five. The fixture hub checks a review
  result's `review` as §8.4 says.

### Removed

- Dashboard, **Message the project**: "A review's result" as a type; a review result carries cites
  against the diff and comes from `maity say --type review_result --review-file`.

### Fixed

- Dashboard: the fixture hub takes an `opensource` section without `links`, as the hub does (§16.7);
  the header-links docs say Gitea gets a branch mark, as the code does.
