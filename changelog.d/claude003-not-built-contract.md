### Changed

- docs: the contract marks what the hub does not build yet (tsk-m80nbn1k7axh). §6.19
  "Between two owners" now states that the hub refuses every cross-owner takeover with
  403 `forbidden`, `details.reason: cross_owner`, on `POST …/takeover` and on an agent's
  move after the lease, and keeps the owner's notice and objection as the target; the
  error table names `cross_owner`. The notice and consent for a change of another
  owner's project texts (§6.28) and the profile's `project_texts` (§6.3) are marked not
  built, as are the matching entries of §7. No hub change.
