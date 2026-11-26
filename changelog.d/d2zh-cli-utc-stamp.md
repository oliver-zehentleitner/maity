### Changed

- cli: one shared `stamp` formatter and `parse_stamp` parser in `maity.stamp` replace the
  copies in `cli.py` (`_utc`, `_parse_utc`, `cli_time`), `hub.py` (`_parse_server_time`), and
  the runner (`keeper`, `scratch`, `supervisor`, `serve`, `install`, and `watch`, the last
  found on current main and not in the audit's list). Format is still whole seconds with a
  trailing `Z`. `parse_stamp` uses `fromisoformat` directly (Python 3.11 accepts `Z`; the
  `.replace("Z", "+00:00")` workaround is gone). `parse_stamp(..., strict=True)` keeps the
  wire form only, as `watch.parse_stamp` and `keeper._age` already required. `stamp(None)` is
  now; `supervisor.stamp(None)` is still None. Behaviour stays the same, except: `hub`'s
  `server_time` parser now returns None for a timestamp with no offset (it used to treat a
  naive `fromisoformat` result as local time).
