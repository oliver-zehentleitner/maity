### Added

- docs: §5.3 "Not listening": an agent session for which a waiting event (by the team's wake rule) is 10 minutes old above its acknowledged cursor, with no `/events` call and no resume in that time, is marked `not_listening_since`; the episode ends when the cursor passes the event. Per episode the hub emits `member_not_listening` (start and end) and files a personal `info` request to the agent's owner, withdrawn at the end. Supervised, paused and unavailable sessions are never flagged.
