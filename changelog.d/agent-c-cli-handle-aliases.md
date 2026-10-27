### Added

- cli: handle arguments resolve aliases (§6.24). `say <to>` (also `<handle>#<instance>`),
  `ask --to`, `takeover --to`, `answer --on-behalf-of` and the placement commands name a member
  by id, current handle, former handle or global name; several candidates are refused with
  their names, as the hub refuses a mention (§8.6); `maity resume` lists a member's former
  handles

### Fixed

- cli: `maity say <to> --type T "…"` takes the message after the options instead of failing
  with "unrecognized arguments"
