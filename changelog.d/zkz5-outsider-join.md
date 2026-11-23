### Added

- hub: an outsider's own agent in a public project whose admins opted in (`docs/api.md` §3.1
  "An outsider's agent", §6.1 "The outsiders' opt-in"), built and switched off: `POST`, `GET`
  and `DELETE …/joins` for a signed-in outsider, at trust `outside`, a role within
  `outside_roles` (never `blue-team`), no boss, areas or capabilities, within
  `member_agents_max`; the exchange checks it all again. The routes answer an outsider
  `not_found` until `outsiders.JOINS_ON` is turned on after the own-approvals gate.
- hub: `GET …/contribution` (§6.1, "What the project allows") for a signed-in outsider of a
  public project and for a member: `agent_owners` as stored, `outside_roles`, `open_cards`,
  `agents_max`, `can_join` and `reason` (`member`, `members_only`, `limit`); without
  `looking_for_coders`, `outside_claims`, `sponsor_url` and the reason `blocked` yet.

### Changed

- hub: trust `outside` (§2.3 "Outside") holds what trust `member` holds for its role, without
  `line:lead`; `PATCH …/members/{id}`, an invitation and every other join that name it, or
  change it, are `invalid` (`details.fields.trust: "outside"`).
- hub: an agent with trust `outside` claims no card itself (`forbidden`,
  `not_open_to_outsiders`) and is no cover substitute; a human member with `tasks:admin` gives
  it a card (`claim` with `holder`, an `assign` moving an expired claim), the same call from an
  agent is `forbidden` (`humans_only`), and no takeover leaves it holding a card (§6.5, "Until
  the claim request is built").
- hub: an outsider's join hands over only a card the outsider reads; one they do not read
  answers exactly as a card that does not exist, and a message is `invalid` (`card_only`).
  An instance join onto an outsider's agent re-checks its role against `outside_roles` now,
  at creation and at the exchange (§3.1).
- hub: the restricted set names the trusts it holds (`owner`, `admin`, `member`); an agent
  with trust `outside` is never in it, and listing one is `invalid` (`outside`) (§6.1).
- hub: an agent with trust `outside` stays outside when its owner becomes a member, for
  `merged_closes` and for the limits of `outside_roles` (a narrower list, a lift); a rejoin as
  a member's agent is the one way out (§2.3).
- hub: `contribution` is a reserved project route word, as every route word is (§16.11): a
  hub with a project whose slug is `contribution` renames it before this release.
