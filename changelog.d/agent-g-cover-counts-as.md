### Changed

- hub: a `role:<role>` entry in an availability policy's `substitutes`
  also takes the security team built on that role (`docs/api.md` §2.3,
  §6.12): `role:reviewer` the purple team, `role:tester` the red team,
  `role:coder` the blue team; `role:<team>` still names the team itself.
