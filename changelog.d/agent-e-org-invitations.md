### Added

- hub: organisations (§6.26), part 2: invitations by consent. `GET`, `POST /orgs/{org}/members/invitations` and `DELETE …/{id}`; the invitation is a personal `consent` request with `project: null` and `org: {id, handle}` that reaches the human through the inbox and the bell, `go` makes them a member with the offered role, `no` or withdrawing it ends the invitation, and an invitation expires after 14 days, when the inviter loses the role, the organisation is deleted or either account is deleted. At most 20 invitations per organisation per 24 hours; the export lists the invitations a human sent (tsk-whe4wv1jpsae).

### Changed

- hub: `request.project_id` and `request.asked_by` may be empty for such a request (migration `0088`); a personal request's own withdrawal now settles its proposal.
