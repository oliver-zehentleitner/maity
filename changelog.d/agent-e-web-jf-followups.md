### Fixed

- web: the jour fixe's statement and report forms stack their labels over the fields, as the other forms do (they ran inline before; the layout guard in `smoke.js` no longer exempts them); the inbox reads `GET /agents` only across projects or for a personal request, not inside a project (tsk-39sjeqre25gw, follow-up of the reviews of #940 and #960).

### Changed

- web: the jour fixe series part drops the map form of `own_agents` and the plain-id form of `report_recipients`: the hub sends `own_agents: [{member_id, opted_out, report_recipient}]` and `report_recipients: [{member_id}]` only (§20.2); the fixture hub refuses a second owner series with the same topic (`topic: taken`), a start of an owner series whose owner left (`circle_owner_gone`) or with fewer than two in the circle (`too_few`), and its series delete answers the series as a reader sees it.
