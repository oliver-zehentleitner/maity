### Added

- hub: `policy.spawn_consent_by` (`docs/api.md` §6.1, §15.6, #137) — `human` (the
  default, and what existing projects get) lets only humans holding `requests:answer`
  answer a placement's consent request, an agent's answer is `forbidden` with
  `details.reason: humans_only` and the request is not in its `to_answer`; `role`
  lets every holder answer, agents included, never the proposer. Set by a human
  with `members:admin`; a preset change keeps it (migration `0011_spawn_consent_by`)
