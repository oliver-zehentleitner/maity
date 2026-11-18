### Changed

- contract: `policy.own_agents` `{"owners_of": [...]}` names human members of the project only, as
  §2.3 "Own approvals" already counts no agent of an owner who is no member as own (`docs/api.md`
  §6.1, §6.30, not built). The value is sent whole; at the write, a handle for a person the stored
  `owners_of` does not hold yet is `invalid` with `details.fields.own_agents` when it names no
  person or a person who is no human member. A handle for a person the stored list already holds
  (matched through §6.24 handles and aliases) is accepted as it is, so a list read and sent back,
  or an edit that keeps a member who has left, passes, as for `settings.restricted_access`. A
  picked member who later leaves stays in `owners_of` and counts nothing while not a member; the
  hub does not remove the handle, and a rejoin counts again. A write of `owners` or `members` drops
  the stored list, and a later `owners_of` checks every handle as new. The §6.30 summary now names
  an outside agent (trust `outside`, or an owner who is no member) as never own, as §2.3 does.
