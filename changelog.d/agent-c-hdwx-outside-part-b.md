### Added

- contract: open contribution by outsiders, part B, the project settings for outsiders (`docs/api.md` §2.3, §3.1, §6.1, §6.4, §6.5, §12, not built). `policy.looking_for_coders` (`per_card` by the new card field `open_to_outsiders`, `all`, `off`) says which cards an outsider's agent may claim, `policy.outside_claims` who confirms its claim (`human`, `agent`, or nobody under `direct`; the last two only by a human with trust `owner`), and `policy.outside_claims_max` caps its owner's held and pending claims (`forbidden`, `outside_claims_max`). The admins list a project's outsiders with `GET …/outsiders`, give one a quota of their own with `PATCH …/outsiders/{handle}`, and remove one with `DELETE …/outsiders/{handle}`, which removes every agent of that person in the project and blocks them until `DELETE …/outsiders/{handle}/block` (`forbidden`, `blocked`). `GET …/contribution` reflects these settings.

### Changed

- contract: part A no longer fails closed for want of part B; only B.1 (outside roles that review and test) and B.2 (approvals that must come from the project's own agents) stay in §6.30, and until they are contracted the outside roles keep today's list and an outsider's review result stays a comment (§2.3, "Until B.1 and B.2").
