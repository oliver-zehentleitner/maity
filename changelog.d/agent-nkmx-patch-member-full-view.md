### Changed

- hub: a `200` of `PATCH /projects/{owner}/{slug}/members/{id}` is the member view exactly as `GET …/members/{id}` gives it to the same caller (§6.2): with `owner`, `credentials`, `manages`, `owner_preferences` and `shared_environment` where that caller's `GET` has them, so a client need not read the member again after a change. The briefing is in the answer only where that caller's `GET` shows it (the member itself and `members:admin`), so a manager or an admin agent no longer gets it there; a replay of the same `Idempotency-Key` answers the view as `GET` gives it then.
- web: the fixtures answer a member `PATCH` as their member list reads the member, and give the list's details `shared_environment` and the owner's `avatar_url`.
