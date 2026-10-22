### Added

- hub: contract for `reports_to` across owners (`docs/api.md` §6.2 "Across owners") — an
  agent reports to another owner's agent, or to a human who is not its owner, only after the
  human who gains the subordinate answers a `consent` request addressed to them alone, member
  of the project or not; the edge is marked `cross_owner` in every member view and grants the
  boss nothing but the subordinate's `session_paused` events; joins and new-profile placements
  carrying such a `reports_to` pass the same consent
- hub: contract — the owner of an agent may always set its `reports_to` to `null` or to a
  member they own, and withdraw a pending cross-owner request, without `members:admin`
  (`docs/api.md` §2.3)
