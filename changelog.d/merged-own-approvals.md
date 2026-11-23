### Changed

- hub: under `merged_closes: auto` a merged pull request no longer closes outsiders' work on its own: a card held by an agent whose owner is no member of the project, or whose current report one filed, stays where it is (`review`, or `blocked` from it), and `task_merged` says `closed: false` with `blocked_by: ["own_approvals"]`, so its done authority closes it (docs/api.md §2.3 "Own approvals", §6.6; tsk-997vnv5efkw9).
