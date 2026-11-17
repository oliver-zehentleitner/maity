### Changed

- contract: an agent may run on several runner placements at once, one per
  instance, within its `agent.max_instances`: two on one runner in two
  clones (`<handle>`, `<handle>-2`, …), or on several runners. A placement
  beyond the limit is refused at its creation with `instance_quota`; the
  placement view and the runner owner's line carry `instance`, and the member
  view gains `placements`, the list of where the agent runs. Not built yet
  (tsk-rfa7fwa2sz5g).
