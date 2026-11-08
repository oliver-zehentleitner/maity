### Added

- cli: `maity wait` reads its timeout from `MAITY_WAIT_TIMEOUT` when `--timeout` is not given, before
  the resume packet's hint (docs/api.md §13). Both accept 1–7200 whole seconds; anything else is a
  usage error naming its source. A hint beyond the cap is taken at the cap.
- cli: `wait` names a `chat_unread` event as `#<seq> chat_unread: <n> unread in "<title>": maity chat
  <id>`.
