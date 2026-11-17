### Changed

- contract: an agent may run on several runner placements at once, one per
  instance, within its `agent.max_instances`: two on one runner in two
  clones (`<handle>`, `<handle>-2`, …), or on several runners. A placement
  beyond the limit is refused at its creation with `instance_quota`; the
  placement view and the runner owner's line carry `instance`, and the member
  view gains `placements`, the list of where the agent runs. A runner's
  rate limit is recomputed from all of the agent's placements that should
  run, and a resume no longer clears a limit the runner set, with one
  placement too. Not built yet (tsk-rfa7fwa2sz5g).
- contract: the replacement of §15.14 and everything that names it
  (routes, `replace_open`, `handover_requested`, the placement's
  `replace`) are marked not built.
