### Changed

- hub: a human member of any trust, a guest included, leaves a project
  with `DELETE /projects/{owner}/{slug}/members/{id}` naming their own
  member id, without `members:admin`, without `owner_only` and without a
  step-up (tsk-z1khn7tkpyqk). The last owner, the namespace owner and an
  organisation's owner in one of its projects cannot. An agent naming its
  own id does not. The call is the removal's cascade. A `member_updated`
  with `removed_at` from a leaving is also addressed to every active human
  member with trust `owner` or `admin`. A repeat without the same
  `Idempotency-Key` is `not_found`; the same key replays the stored 200.
- docs: Contract change. §6.2 and §6.12 now say each new card of the
  covered member goes to the first entry of its cover order, as it stands
  after the removal, that §6.12 would pick for that card now
  (`available`, not itself covered, and may take it). The cover itself
  runs on, and `covered_by` keeps naming the substitute the cover started
  with. Only the dashboard's confirmation remains for the web change of
  tsk-z1khn7tkpyqk.

### Fixed

- hub: a substitute whose membership has ended, removed or left, gets no
  new card of the member it covers (tsk-n5hqcbcg3xvw). Each new card goes
  to the first entry of the cover order, as it stands after the removal,
  that may take it now, and with none to the covered member.
