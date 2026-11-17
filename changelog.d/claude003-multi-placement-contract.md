### Changed

- contract: an agent may run on several runner placements at once, one per
  instance, within its `agent.max_instances`: two on one runner in two
  clones (`<handle>`, `<handle>-2`, …), or on several runners. A placement
  beyond the limit is refused at its creation with `instance_quota`; the
  placement view and the runner owner's line carry `instance`, and the member
  view gains `placements`, the list of where the agent runs. A runner's
  rate limit is recomputed from all of the agent's placements that should
  run, at each report, close or change of `desired`, and when a limit the
  agent set itself ends (at its `until`, by a resume or by `POST /me/limit`
  with `until: null`), so a rate limit still ahead takes over then; with one placement
  too, so a change to `desired: stopped` ends the limit at once, not at
  the later `stopped` report, and a resume no longer clears a limit the
  runner set. A recomputation never replaces or clears a limit the agent
  set itself (`POST /me/limit`); today a `rate_limited` report replaces
  it. Not built yet (tsk-rfa7fwa2sz5g).
- contract: the runner replacement of §15.14 is marked not built, and so
  is every place that names it: its routes and their limits (§1.7),
  `replace_open`, the handover conflict, `handover_requested`,
  `placement_replaced`, the closing reasons `replaced` and
  `replace_failed`, replacing in "Who may do what" and its caller table,
  the runner's `handover_key` (in the runner view's example too), and the placement's
  `replace`, `replaces`, `replaced_by`, `handover` and `kept_until`.
