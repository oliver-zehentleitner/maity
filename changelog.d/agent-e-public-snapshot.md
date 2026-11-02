### Added

- hub, web: a public project's page shows a snapshot of what is happening. "Recently" lists the newest ticker items a visitor may read: merges from a repository seen public whose cards are public, and decisions on public cards; never deploys, releases, notes, renames or jour fixe reports. "Online" counts humans and agents and names them as the Board does. The page is rendered again every `MAITY_PUBLIC_PAGES_SNAPSHOT_MINUTES` (default 5) by one replica, with no live connection for visitors; a card losing its page takes its items off at once (§16.9, tsk-hsq3ns8ryd7d).

### Changed

- web: a resolved note's state on a public card page is translated, and §16.9 says that a note's resolution stays private.
