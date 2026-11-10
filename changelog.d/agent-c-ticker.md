### Added

- cli: `maity ticker` (§13, §17) — one page of the change ticker in the text form of §17.9
  (`--mine`, `--type` repeated, `--area`, `--since` as RFC 3339 or a duration back,
  `--limit`, `--cursor`; a `more:` line names the next page with `--since` resolved);
  `ticker post` with every flag mapped to its field, `--to computed|all` alone, and the
  interim `maity say` line on a hub whose `openapi.json` has no ticker; `follow`, `mute`,
  `unfollow`, `unmute` as one `PATCH …/ticker/subscription` each; `maity resume` prints a
  `Ticker` section and leaves ticker items out of the missed events.
- cli: `note list` and `release list` stop with an error when the hub sends a page cursor
  they already followed.
