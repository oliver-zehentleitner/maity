"""How old a stored `last_seen_at` may be against the call it stands for (docs/api.md §2.4).

The hub writes `last_seen_at` (a member's, a human's, a session's) and a human session's `ip` at
most once every `SEEN_EVERY`: a call within it of the last write leaves them as they are
(`auth/caller`), so the latest call lies anywhere from the stored time to `SEEN_EVERY` after it.
Every reader that turns a stored `last_seen_at` into a state (presence, a session's idle end,
the not-listening digest's stalled holder) reads it from `latest_call`, the latest the caller
may have called, so that a caller that calls is never shown away, expired or stalled early; the
state may then hold up to `SEEN_EVERY` longer after the last call (hub/context/auth.md)."""

from __future__ import annotations

from datetime import datetime, timedelta

# The maintainer's decision, seq 109161 (tsk-wa3aqmrj8v1b): presence reads against 120 s and
# longer, and writing two or three rows on every call cost the database a row lock and a write
# per request.
SEEN_EVERY = timedelta(seconds=60)

# The presence windows of §5.3, for members, instances, runners and the landing's counts.
ONLINE = timedelta(seconds=120)
AWAY = timedelta(hours=2)


def latest_call(last_seen: datetime) -> datetime:
    """The latest moment a caller whose stored `last_seen_at` is `last_seen` may have called."""
    return last_seen + SEEN_EVERY


def presence_by_age(age: timedelta) -> str:
    """`online`, `away` or `offline` by the time since the latest call (§5.3). The caller picks
    that call: `latest_call` of a throttled `last_seen_at` (a member's, a human's), the stored
    time itself where every call writes it (a credential's `last_used_at`, a runner's)."""
    if age <= ONLINE:
        return "online"
    if age <= AWAY:
        return "away"
    return "offline"
