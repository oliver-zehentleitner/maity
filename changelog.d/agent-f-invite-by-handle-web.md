### Added

- web: the invite form (Members → Invite user, `/invite`) takes a person's handle (§3.4), in a
  **Handle** field before the address. An invitation by handle is sent without an address and
  without a link: the form names the person, who answers in their inbox. The hub's refusals of
  a handle (no such person, an organisation's handle, already a member, already invited, not a
  handle) are said in words. The list shows the handle each invitation is for and a declined one
  as declined.
- web: the notification settings show the kind `invitation` with its browser switch and mail
  mode (§18.4), labelled "Invitations to a project".

### Changed

- web: the invite form's address field is labelled "Email address" in every language, no longer
  "Address".

### Fixed

- contract: §18.1 names who a project request's bell title shows (`<who> asks: …` is the member
  whose event it is, for `request_forwarded` the one who forwarded it, `Maity` for the hub's
  own), and words the account records' `invitation` item plainly.
