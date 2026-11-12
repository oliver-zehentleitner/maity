### Changed

- docs: a human member of any trust, a guest included, leaves a project
  with `DELETE /projects/{owner}/{slug}/members/{id}` of their own member
  id, without `members:admin` (§6.2). An agent does not. The last owner,
  the namespace owner and an organisation's owner in one of its projects
  cannot. It is the removal's cascade, needs no step-up, and a repeat
  without the same `Idempotency-Key` is `not_found`. The hub's route
  still requires `members:admin` until its own change.
- docs: a running cover no longer routes a new card to a substitute
  whose membership has ended (removed or left): the card goes to the next
  available entry of the cover order, and with none to the covered member
  as without cover (§6.2, §6.12). The hub follows in its own change.
