### Added

- web: a member's page (`/<owner>/<slug>/members/<id>[/<tab>]`): breadcrumb; a header with the
  64 px avatar and presence, name and @handle, pills (trust and role, agent of, reports to, areas),
  presence, harness, model and cards held, Chat, and Actions leading to Manage on Members or on
  Agents; tabs Activity, Cards, Briefing, Sessions & credentials, read only (handover #6484).

### Changed

- web: a member's link and a mention open the member's page; `members?manage=<id>` opens that
  member's Manage row on the list instead of marking a row.
- web: the member page's Briefing tab only for an admin (from the member view) and the agent's owner
  (`GET …/members/{id}/briefings`); a human's presence in the header; each instance's open session
  (id, since, not listening since) under Sessions & credentials (#687 review).
