### Added

- cli: `maity wait` reads its timeout from `MAITY_WAIT_TIMEOUT` when `--timeout` is not given, before
  the resume packet's hint (docs/api.md §13). Both accept 1–7200 whole seconds; anything else is a
  usage error naming its source. A hint beyond the cap is taken at the cap, and one that is not a
  positive whole number (a JSON `true` included) is ignored, which gives 600; each resume replaces
  the stored hint, so an invalid or missing one no longer leaves an earlier value in place.
- cli: `wait` names a `chat_unread` event as `#<seq> chat_unread: <n> unread in "<title>": maity chat
  <id>`.
