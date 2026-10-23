### Fixed

- hub: no agent, whatever its role, assigns away or releases a card a human holds, lease or
  no lease (`docs/api.md` §2.3): `POST …/assign` to another member, `POST …/release` by
  someone other than the holder and `PATCH assigned_to` away from the human holder answer
  `403` with `details.reason: humans_only` before the scope and the lease are looked at;
  humans keep these rights, and an admin agent still moves an agent's expired claim
