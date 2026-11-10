### Changed

- hub: a `PATCH /projects/…` whose policy change is `badge` alone takes `reason`
  optionally, and its `policy_changed` carries `reason: null` then; every other policy
  field, and a state change, keeps the reason rule (§6.1, §6.20)
- web: the README badge form in Project settings no longer asks for a reason; the
  fixture hub takes a badge-only change without one
