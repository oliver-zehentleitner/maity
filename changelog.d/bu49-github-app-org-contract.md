### Added

- Contract: an installation of the GitHub App on a GitHub organisation (§11.4, §6.26,
  not built yet). It is linked when the human completing the link is an active owner of
  that organisation on GitHub (role `admin`, the organisation's id the installation
  account's), otherwise `403 forbidden` with the new reason `not_organisation_admin`;
  another account kind stays `organisation_installation`. The link is that human's grant,
  never a Maity organisation's: it serves their projects and the Maity organisation
  projects whose repository they confirmed, and no organisation name is matched to a
  GitHub login. The hub keeps the GitHub user's id on the link and re-checks the
  ownership when it chooses a project's source and on `GET /me/forge`, in both cases at
  most every 10 minutes per link and at once after a refusal (a listing within 10 minutes
  of the last check makes no forge call and shows the last known status); a failed
  check sets the new link status `not_admin`, the probe reason `installation_not_admin`
  and the account record change `not_admin`. One human holds an installation's link at
  a time; no App webhook.

### Changed

- deploy: the instance's GitHub App asks for the organisation permission Members
  (read-only) beside its repository read permissions (§11.4), for the owner check of an
  organisation installation; an organisation that installed the App before accepts the
  new permission on GitHub. Installations on user accounts need nothing new.
