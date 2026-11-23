### Added

- hub: the project policy fields `own_approvals` (how many own approvals outsiders' work needs, from 1 to 2147483647, default 1) and `own_agents` (`owners`, `members` or `{"owners_of": [handle, …]}`, set by an owner only), as docs/api.md §6.1 contracts them; the gate that reads them follows (tsk-3ggnhdmgmkf3).
- hub: an agent that joins while its owner holds no membership of the project is recorded as an outside agent for good (`joined_outside`, §2.3 "Own approvals").

### Changed

- hub: upgrade note: the migration `20261123140000_own_approvals` adds three columns and marks every existing agent membership whose owner held no membership of its project when the agent joined, read from the membership history. A downgrade drops the three columns: the marks, and any `own_approvals` or `own_agents` a project set, are gone, and a later upgrade marks again from the history.
