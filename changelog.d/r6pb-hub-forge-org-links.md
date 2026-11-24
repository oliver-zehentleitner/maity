### Security

- hub: an installation of the GitHub App on a GitHub organisation can be linked (§11.4).
  Only an active owner of the organisation can link it, read with their own one-time
  user token; anyone else gets `403 not_organisation_admin`. Without a definite answer
  from GitHub, nothing is linked and the call answers `forge_unavailable`. The link is that
  human's grant. It serves a read only on an owner check that succeeded less than 10
  minutes before. The hub checks again at most every 10 minutes, and one process claims
  each check. The check reads the installation, the GitHub user by the id kept with the
  link, and that user's membership. A definite "no owner" sets the link `not_admin`:
  it serves nothing, its tokens are dropped, and its human gets one `security` item.
  Every other refusal leaves the status as it is, but the link serves nothing once its
  last success is 10 minutes old. A `suspended` link comes back only through its owner
  check. A link that serves nothing is not the project's source: the owner's own token
  and the instance token are tried next. When nothing covers, the human who confirmed
  the repository gets the specific reason (or `probe_unavailable`, `ktw_unavailable`
  from the Keep the Why reads), other admins `installation_link_invalid`, everyone else
  no reason. The Keep the Why export (§11.3) checks such a link on every call.
  Another owner's link replaces an existing one only after that link's own check says
  its human is no owner. A link that changes during that check answers
  `forge_unavailable` with nothing written.
- hub: a `suspended` link to an installation on a user account is minted for at most
  every 10 minutes, as §11.4 says, and no longer on every listing or source choice.

### Changed

- deploy: migration `20261124170513_org_link_check` adds `forge_link.forge_user_id` and
  `forge_link.owner_ok_at`. Its downgrade deletes the links to installations on GitHub
  organisations, which only this release writes. The GitHub App is to ask for the
  organisation permission Members (read-only); without it, every owner check has no
  answer and an organisation's installation can be neither linked nor served.
