### Removed

- web: the dashboard no longer asks the hub's machine form what it serves (`M.api.hubHas`,
  `M.api.hubBody`) and no longer treats a 404 or 405 as "not on this hub" (`M.api.missingRoute`,
  `M.api.absent`, `M.dom.notOnHub`); a missing route is an error like any other. The fallback for a
  hub without notifications (`M.notify.state.available`, the bell as a plain link, the inbox's
  "Nothing waits for you.") is gone, as are the per-project chat reads for a hub without
  `GET /me/conversations`, the admin sections left out for a hub without them, and the "this hub
  does not order cards / take pictures yet" readings of a 404. Fields the hub always sends are no
  longer tested for presence (the Why tab, the signing, badge, Keep the Why, swarm, member-agents,
  onboarding and image forms, a card's subtask editor, /me's project logos without the
  `GET /projects` fallback, the coordinator before trust × role).
- web e2e: the invitations, images, Why, signing, users and briefing steps no longer skip a hub
  without the feature.
