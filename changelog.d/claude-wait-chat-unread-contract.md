### Added

- docs/api.md §9.2, §8.2, §9.4: the unread nudge (not built yet). An agent in a group chat gets one
  `chat_unread` per chat and read cycle for human messages that did not mention it, sent 10 minutes
  (`chat_unread.delay`) after the oldest of them and only while one of its instances listens. Agents'
  messages never count.
- docs/api.md §13, §5.2: `maity wait` reads its timeout from `MAITY_WAIT_TIMEOUT` when `--timeout` is
  not given, before the hub's hint, and accepts 1–7200 seconds (not built yet).
