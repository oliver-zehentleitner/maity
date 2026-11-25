# One UTC stamp formatter and parser

## `maity.stamp` is the one formatter and parser for the wire-form UTC timestamp

**Id:** efecde7d-2e4a-4ba4-8bb4-995b160de7a0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-d2zhcxhg10b5 (the lead's order); the clean-up audit, card tsk-hgnbapyw7hnh; the hub counterpart, card tsk-kfpz2m8we8f1, for naming
**Revisit when:** the hub card tsk-kfpz2m8we8f1 adds `clock.parse_rfc3339`, or `fromisoformat`'s handling of `Z` changes

The CLI and the runner each formatted `%Y-%m-%dT%H:%M:%SZ` and parsed it in several places, some still rewriting `Z` to `+00:00` for `fromisoformat`. Those copies now call `stamp` and `parse_stamp` in `maity.stamp`. The formatter takes a float (seconds since the epoch), a datetime, or None (now) and writes whole seconds with a trailing `Z`. The parser takes any value: a non-string, a value `fromisoformat` rejects, a naive result, or a time that overflows when converted to UTC is None; a success is in UTC. `strict=True` also requires the wire form `YYYY-MM-DDTHH:MM:SSZ` (no fraction, offset, space, or lowercase), which is what `watch.parse_stamp` and `keeper._age` already required. Python 3.11 already accepts a trailing `Z`, so the parser does not rewrite it.

The sites, re-checked against main 28248535 (the audit was at 588f911b; line numbers had moved): `cli._utc` and `cli._parse_utc`, `cli_time`, `hub._parse_server_time`, `keeper.stamp` and `keeper._age`, `scratch.log_removal`, `supervisor.stamp`, `serve.utc`, `install`'s `created_at`, and `watch.stamp` / `watch.parse_stamp`. The last pair was not in the audit's list; it already used these names and the same format, and is included so the runner does not keep a second copy. `#2237` was open and about to merge, but it does not change any of these files, so this work did not wait for it.

`supervisor.stamp(None)` is still None (a missing time), not now: the shared `stamp(None)` is now, and the supervisor keeps its own None check. `serve.utc(None)` and `scratch.log_removal(..., at=None)` still mean now. `watch.parse_stamp` still returns a float or None, still wire-form only. `cli_time` still uppercases the option before parsing, so a lowercase `t` or `z` is still accepted there, and it still refuses a time that overflows when converted to UTC (`0001-01-01T00:00:00+01:00`, `9999-12-31T23:59:59-01:00`).

The hub counterpart names the helpers `clock.rfc3339` and `clock.parse_rfc3339` in the hub package. This module stays `stamp` / `parse_stamp`, the names the CLI card asked for and that `watch.py` already used.

**Reason:** a fix to the format or to a parse edge (a trailing `Z`, a naive value, an overflow at the datetime range) had to be made in every copy, and the copies had already diverged: some used `strptime` and accepted only the wire form, some used `fromisoformat` and accepted an offset or a fraction, and `hub._parse_server_time` treated a naive result as local time.

**Rejected alternatives:**
- Putting the helpers in `proc.py`: that module is about locating and running git and gh, not about times.
- One parser that is only lenient, or only strict: the first would have `watch` and `keeper._age` accept an offset or a fraction, which they currently refuse; the second would have `cli_time` and the hub's `server_time` reject those forms.
- Using the hub card's `rfc3339` / `parse_rfc3339` names here: the helpers live in a different package, and `watch.py` already exported `stamp` and `parse_stamp`.
- Waiting for `#2237` to merge first: it changes `runner/adapters.py` and related tests, not any of the stamp sites.

**Known differences from the old code:** `hub._parse_server_time` now returns None for a timestamp with no offset. The old copy called `.timestamp()` on a naive `fromisoformat` result, which is local time. `parse_stamp` (and so `cli._parse_utc`) returns a datetime in UTC; the old `_parse_utc` left a non-UTC offset as it was. Outage stamps were always written with `Z`, so that change is not visible there. `cli_time` still converts to UTC before it formats.
