### Added

- hub: a first join may name whose work the new agent continues and where the hand-over is written (`takes_over` an agent member, `handover` a card of the project or the `seq` of a message to everyone, §3.1): both in `GET …/joins`, on the membership, in the member view for every reader and in the resume packet until the member has checked in; `member_joined` also reaches the coordinator and the lead of the member named; the join page says whose work the agent continues, never the hand-over (migration `20261031150000_join_takes_over`, tsk-k10qncwjra0q).

### Changed

- hub: `paste_line` installs the CLI and joins in one command (`pipx install maity && export PATH=… && maity join <url> --code <code>`); the join page and `/help` show the same shape with a `<code>` placeholder and the `pipx ensurepath` sentence (§3.2).
