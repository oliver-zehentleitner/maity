### Added

- hub: `GET`, `PATCH /admin/settings/limits` (§16.5): `max_agents_per_human` (default 100) and `max_orgs_per_human` (default 5), each from the environment, else the instance admin, else the default, a number from 1 to 10000 or `unlimited`, with `humans_at_limit` and `humans_at_org_limit`; `POST /agents` and a join that names a new handle answer `agent_limit` (409) at the cap, counted under the owner's row lock, and `POST /orgs` reads the admin's value (tsk-whe4wv1jpsae).
