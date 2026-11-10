### Changed

- web: memberships show and choose trust and role separately (docs/api.md
  §2.3): the member form, invitations and join lines offer trust owner or
  admin and the role proxy only to an owner, proxy only with trust admin; a
  guest is never offered as an assignee or as whom someone reports to, and a
  human guest gets no new group chat. The interim mapping of trust and role
  to single-role names at the API boundary is gone.
