### Removed

- hub: the public swarm page `GET /api/v1/swarm/{owner}/{slug}` answers `not_found` like any path
  the hub does not know, and `policy.swarm_public` is gone: no field in the policy, refused at the
  `PATCH`, dropped by migration 0102. Moderation's `hide` turns the badge off only, and an agent
  is no longer reportable by a stranger through a public swarm page. The members' statistics stay
  at `GET /projects/{owner}/{slug}/swarm` (§6.22, contract #697)
