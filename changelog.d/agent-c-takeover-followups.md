### Changed

- cli: `maity resume` stores the session's `me.instance` when the hub sends one, and
  `takeover accept`/`object` then refuse a takeover another instance of the team holds. The
  local refusal after a human's objection applies only while the takeover is `objected` or
  `escalated`, so the holder answers again after a retract. The help's exit code 4 reads
  "refused locally, nothing sent".
