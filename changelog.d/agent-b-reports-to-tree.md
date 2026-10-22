### Changed

- hub: `reports_to` forms a tree — naming the member itself or someone already reporting up to
  it is `invalid` with `details.fields.reports_to: "cycle"` on `PATCH …/members/{id}`; a join
  adds no edge, since one for an existing member must name its current `reports_to`
  (`docs/api.md` §6.2)
- hub: removing a member clears `reports_to` on everyone who reported to it, one
  `member_updated` each, and on join links not yet used
