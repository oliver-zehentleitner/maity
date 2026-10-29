### Changed

- hub: the forge's rate limit is kept per source, the token's digest, from every answer's `X-RateLimit-*` and `Retry-After`. A spent budget, or one under 5 % of its limit, stops every read with that source until the reset; nothing is sent meanwhile. `GET …/probe` and the contract text answer `probe_unavailable` with `details.retry_at` instead of trying. The probe worker schedules its next sweep and merge round no earlier than the reset, and each round starts at another project.
