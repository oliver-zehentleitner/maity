### Changed

- contract: `policy.own_agents` `{"owners_of": [...]}` names human members of the project only, as
  §2.3 "Own approvals" already counts no agent of an owner who is no member as own (`docs/api.md`
  §6.1, §6.30, not built). A handle that names no person, or a person who is no human member, is
  `invalid` with `details.fields.own_agents`; the agents of a picked human who has since left count
  no more. The §6.30 summary now names an outside agent (trust `outside`, or an owner who is no
  member) as never own, as §2.3 does.
