### Added

- hub: the counting of landing variants and campaigns (§16.7.2): daily sums of views, registrations and first agent exchanges (`activations`) per variant and campaign, no record of a visit; the origin of a registration is kept with the account until its first exchange or 30 days; `GET /admin/statistics/campaigns` (JSON or `?format=csv`, `days` up to 400, the admin's alone); the sums are deleted after 400 days (tsk-tk10nnqdh8h1).
