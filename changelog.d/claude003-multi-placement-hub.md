### Added

- hub: an agent runs on several runner placements at once, one per instance:
  a member that already runs is placed again instead of refused with
  `placement_exists`, on the same runner in a clone of its own (`<handle>-2`,
  …) or on another runner (tsk-rfa7fwa2sz5g).
- hub: the placement view and the runner owner's line carry `instance`; the
  member view gains `placements`, every active placement with its instance.
- cli: `maity placement stop|restart <agent>#<instance>` names one of an
  agent's placements; an agent with several is refused with their ids, and
  `maity placement list` shows `<handle>#<instance>`.

### Changed

- hub: a placement beyond the agent's `max_instances` is refused when it is
  created or proposed (`instance_quota`), no longer only at the runner's
  pickup.
- hub: a runner's rate limit makes the agent `limited` only while every
  running placement of it is rate-limited: each report recomputes it from
  all of them, and a resume no longer clears a limit the runner set.
