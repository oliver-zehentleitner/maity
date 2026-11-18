### Changed

- contract: a member picked in `policy.own_agents` `owners_of` who leaves and rejoins makes
  their agents count as own again only where the hub did not isolate them: an agent the hub
  isolated when its owner left (every such agent under `policy.agent_owners: members`, one
  beyond the outside limits under `anyone`) counts once an admin lifts that isolation, since
  §6.2 lifts none by itself and §2.3 counts no approval of an isolated agent (`docs/api.md`
  §6.1, not built). This narrows the rejoin sentence of the earlier `owners_of` entry.
