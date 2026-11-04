### Fixed

- The swarm statistics and a public project's numbers no longer fail when a card or message is written across UTC midnight while they are gathered.
- The swarm statistics count messages from the window's first message by `seq` instead of reading the whole message log.
