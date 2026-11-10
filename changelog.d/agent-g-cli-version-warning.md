### Added

- hub: the resume packet (`hints.cli_version`) and each answer of `GET …/events` (`cli_version`)
  name the newest published CLI (§5.2, §8.3).
- cli: `maity resume` and `maity wait` say on stderr when the CLI is older than that, with
  `pipx upgrade maity`; nothing is refused.
