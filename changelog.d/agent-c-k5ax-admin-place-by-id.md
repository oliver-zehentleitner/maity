### Changed

- web: a project admin starts an agent of their own that is not in the project yet on a runner
  of their own from **Join an agent**, its part **On a runner**, without a join line first. The
  start sends the profile's id with the fields an admin's join takes (trust, role, whom it reports
  to, areas, briefing), which the hub stores for the first join its pickup makes. The form offers
  only the admin's own profiles, so another owner's agent is never offered by id; agents already
  in the project and new profiles start as before (`docs/api.md` §15.6; tsk-rmvgtab6rae8).
- docs: the user pages say an admin starts such an agent without a join line first
  (`docs/humans.md`, `docs/runners.md`, `docs/how/tools.md`).
