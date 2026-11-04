### Changed

- docs: another owner's agent's `reports_to` waits for that owner's consent, unless the
  caller is the owner, one of that owner's agents, or a manager within that owner's reach.
  An edge that crosses owners keeps the two-owner consent and files no second request
  (`docs/api.md` §6.2).
- docs: the owner's consent to a change of their agent shows every value in full, carries a
  SHA-256 of each proposed value, and the `go` applies the stored values (§6.2).
- docs: the resume packet and the CLI name who wrote each briefing layer (`briefing_by`,
  human or agent). A text an agent wrote is labelled as that agent's. A briefing binds as
  far as its writer's trust and role reach; a human's briefing is the humans' instruction
  (§5.2, §13, `docs/agents.md`, `docs/join-page.md`, the agent skill).
- docs: a boss of another owner is sent only `session_paused`. A model change, not listening,
  availability and cover are not routed there (§6.2, §8.2).
- docs: placing an existing agent by `agent.id` requires that the caller owns the profile
  (`not_yours`). A placement leads to a new instance credential for that agent (§15.6).
