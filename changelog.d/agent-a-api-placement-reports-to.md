### Changed

- docs/api.md §6.2, §15.6: removing a member clears every `reports_to` that names it — on
  members (`member_updated`), on unused join links, and in the join fields of an active
  placement that creates a profile (no event, no `generation` bump); the exchange applies a
  join's `reports_to` only while it names an active member, so no membership is ever created
  reporting to a former member.
