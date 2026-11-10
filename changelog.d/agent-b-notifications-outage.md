### Added

- hub: the owner is asked when an agent stops (`docs/api.md` §15.7, contract #409). A current
  report of `failed`, or of `exited` with `quota`, opens an outage of the placement and files
  one personal request to the agent profile's owner: class `info`, one option `seen`,
  `filed_by: "hub"`. Its events reach the owner only, and no project route shows it. The
  outage ends, and an open notice is withdrawn, when the agent runs again, is stopped, or
  the placement is deleted or its project archived. Requests carry `filed_by`.
