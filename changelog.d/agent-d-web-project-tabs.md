### Added

- web: a project's **Agents** tab (`/<owner>/<slug>/agents`, before Runners and Why): one's own
  agents in the project, each as its card on Your agents, with the preferences switch, the team's
  rulebook and the credentials under it, and with members:admin its pause and removal; the join
  panel (`…/agents/join[?agent=<id>]`), the open joins, where the agents run and the earlier joins.
  `…/agents/<id>/rulebook` focuses the limit; a new project opens there.
- web: a **Chat** button on every entry of Members: one's own agent's direct chat, anyone else a
  new group chat with them chosen (`chat/new?with=<id>`).

### Changed

- web: **Members** is a neutral list for every viewer; the credentials summary left the list, and
  **Manage** stays for members:admin. The organisation tree is a section of the **Overview**,
  redrawn on a member event.
- docs: §16.11 names `/agents`, `/agents/<id>` and the project view `agents/<id>…`; `agents` is
  no longer a word held back for later.
- hub: `agents` is a project view a slug may not take; `org` is not. A project whose slug is
  `agents` must be renamed before the release starts (§16.11, "When the list grows").

### Removed

- web: the **Organisation** tab and `/<owner>/<slug>/org`, the owner's **Details** on Members,
  `…/members/join` and `…/members/<id>/rulebook` and `/picture` (alpha: no redirect).
