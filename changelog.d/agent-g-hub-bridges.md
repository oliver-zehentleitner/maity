### Added

- hub: bridges (§2.3): `POST`, `PATCH` and `DELETE …/members/{id}/bridges` connect an agent
  that lends its hands to another for a purpose, at once with one owner, across owners after
  the bridge owner's and the project's consent; member views carry `bridges` and
  `bridging_for`, the resume `membership.bridges` and `membership.bridging_for` and the
  bridge's guide in the rules (also from `GET …/rules`), a chat lists a bridge across owners
  among its `observers`. `DELETE` answers `200` with the connection in its final state
  (`ended_at`, `ended_by`, `end_reason`), also for the bridge's owner outside the project.
  Migration `20261031180000_bridges`.
