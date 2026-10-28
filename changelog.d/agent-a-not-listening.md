### Added

- docs: §5.3 "Not listening": an agent session with a waking event unread for 10 minutes and no read of `/events` in that time is marked `not_listening_since`; per episode the hub emits `member_not_listening` to the lead and files a personal `info` request to the agent's owner, withdrawn when it reads again.
