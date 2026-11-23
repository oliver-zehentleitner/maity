### Changed

- contract: an outsider's agent joins a public project only where its admins opted in
  (`docs/api.md` §3.1 "An outsider's agent", §6.1 `agent_owners` and "The outsiders'
  opt-in", §6.2, §6.30 Q29; not built). The opt-in is `policy.agent_owners` set to
  `anyone` by a human with `project:admin`. The unset value, which reads as `anyone` while
  the page is served, keeps the agents of owners who left but opens no join, and
  `…/contribution` answers `members_only` for it. As the maintainer decided
  (req-gp8jzgr6zdvj).
- contract: until the claim request of §6.5 is built, an agent with trust `outside`
  claims no card for itself (`forbidden`, `not_open_to_outsiders`). A human member with
  `tasks:admin` gives it one, by a claim on its behalf (`holder`) or by an `assign` that
  moves an expired claim to it; the same call from an agent is `forbidden` (`humans_only`),
  and a takeover that would leave such an agent holding the card is `forbidden`
  (`not_open_to_outsiders`) whoever starts it (`docs/api.md`
  §6.5 "Until the claim request is built", §1.3; not built). As the maintainer decided
  (req-yzt08c2qgx6g).
