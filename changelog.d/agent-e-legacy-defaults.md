### Changed

- hub: the policy of a project reads `badge`, `subtasks`, `swarm_public` and `merged_closes` from the row as it is, and onboarding reads `coordinator` from the policy without a default: the fallbacks only covered rows without those columns, which no schema has (tsk-wgg2t8ngx9xg).
