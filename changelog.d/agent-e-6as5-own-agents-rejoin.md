### Changed

- contract: a member picked in `policy.own_agents` `owners_of` who leaves and rejoins makes
  their agents count as own again only where the hub did not isolate them: an agent the hub
  isolated while its owner was no member (when the owner left, every such agent under
  `policy.agent_owners: members` and one beyond the outside limits under `anyone`; or when the
  setting came to read `members`, an agent kept under `anyone` included) counts once an admin
  lifts that isolation, since
  §6.2 lifts none by itself and §2.3 counts no approval of an isolated agent (`docs/api.md`
  §6.1, not built). This narrows the rejoin sentence of the earlier `owners_of` entry.
