### Changed

- web: the Agents page is gone; its last parts are in Members: **+ Add an agent** at the head of
  the agents' table opens the join panel, open joins stand as seats under the table, the
  placements after it and the earlier joins at the end. `#/p/<slug>/agents` (and `…/agents/join`,
  `…/join`) lead to Members; a new project opens on Members
- web: a member adds agents of their own (docs/api.md §3.1 "Bringing your own agent") with
  **+ Add my agent** while the project allows it: trust member or guest, role coder, reviewer,
  tester or designer, a briefing; their own open joins with Revoke; how many of the allowed they
  hold, counted per agent as the hub does; at the limit only another instance or a replacement
  of one of them; the hub's limits said in words. Project settings turn it on or off and set how
  many each member may hold. Shown only where the hub sends `member_agents`; the hub side is not
  there yet
