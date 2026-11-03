### Added

- hub: the owner's hourly digest lists stalled holders, agent instances that hold cards and have
  made no call for `not_listening.minutes`, a crashed harness or a revoked session included, with
  their cards, last call and reason (§5.3); the bell's `agents_not_listening` record counts them
  in `holding`, and the bell's title says "away" when one is among them.

### Changed

- hub: the digest request is no longer rewritten in place: when what it shows changes it is
  withdrawn and a new one filed, so an answer from a page that has not seen the change is
  `request_not_open`. Answering `seen` records what the request showed, per owner and instance,
  and silences an instance while it has made no call since, or while the seen episode runs; a new
  owner of a profile starts without the old owner's records.
- docs/api.md §5.3, §7: the cost of refiling names the mail and the bell entry; a hub-filed
  digest's withdrawal is listed under "Withdrawing".
- hub: a new index on `agent_session` (credential, start) for each credential's latest session.
