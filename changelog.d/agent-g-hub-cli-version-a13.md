### Changed

- hub: the hub names CLI 0.1.0a13 as the newest published CLI (`hints.cli_version` and `GET …/events`
  `cli_version`), so a CLI older than 0.1.0a13 prints its upgrade line (§5.2, §8.3). **Upgrade note:**
  that line also reaches runners; CLI 0.1.0a13 refuses a `runner.toml` with a `[harness.antigravity]`
  table, so remove that table before upgrading such a runner (0.1.0a14 is to offer antigravity again).
  A runner with `[harness.codex]` is accepted from this hub version on (#1872).
