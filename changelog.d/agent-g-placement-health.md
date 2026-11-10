### Added

- docs/api.md §15.14: placement health. The hub asks a silent agent to check in after
  `hang_after_minutes` and nudges it after `reply_within_minutes`. These are owner settings with
  a per-profile override, and the nudge is also `POST …/placements/{id}/nudge`. The runner wakes
  or resumes the agent on the same session, or leaves it running when it has produced output
  recently or a person may be at the pane. A placement can be replaced on another runner with a
  handover (`none`, `summary`, `full`); a full transcript travels end-to-end encrypted between
  runners. New run-end reasons are `hung`, `network`, `context_full`, `auth` and
  `harness_config`. Six restarts in an hour mark a placement `flapping` and hold it until a person
  or an admin agent acts on it (a restart, a nudge, a change of the spec or a replacement).
