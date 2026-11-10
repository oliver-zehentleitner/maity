### Changed

- Hub: project states are `plan`, `build`, `review`, `launch` and `archived` (§6.1). Migration
  0094 maps `freeze` and `fixes-only` to `review` and `accepted` to `archived` once, without a
  `state_changed` event; the old names are `invalid` (`state: unknown`). `plan` and `review`
  ask for a `reason` on new cards, claims and placements, `archived` refuses them, and only a
  human with trust `owner` moves a project to `launch` (`forbidden` for anyone else).
