### Added

- Contract: an installation of the GitHub App on a GitHub organisation (§11.4, §6.26,
  not built yet). It is linked when the human completing the link is an active owner of
  that organisation on GitHub (role `admin`, the organisation's id the installation
  account's), otherwise `403 forbidden` with the new reason `not_organisation_admin`,
  decided before `installation_not_yours` and before `installation_linked`; another
  account kind stays `organisation_installation`. The link is that human's grant, never
  a Maity organisation's: it serves their projects and the Maity organisation projects
  whose repository they confirmed, and no organisation name is matched to a GitHub
  login. The hub keeps the GitHub user's id on the link (`forge_user_id`, in no answer).
- Contract: such a link serves a read only on an owner check that succeeded less than
  10 minutes before; the remaining window after an owner loses the role is stated as
  accepted. The hub re-checks in a fixed order (the installation, the user by the kept
  id, that user's membership, whose user id must match) on the source choice and on
  `GET /me/forge` at most every 10 minutes per link whatever the last outcome, and at
  once when a repository the link covers is confirmed or a project's source newly rests
  on it. A forge that does not answer, a rate-limit answer included, changes no status
  but leaves the link serving nothing once its last success is 10 minutes old. A failed
  check sets the new link status `not_admin`: the link serves nothing, shows no
  repositories on `GET /me/forge` and is re-checked there and on the source choice, so a
  restored role restores it; the human who confirmed the project sees the probe reason
  `installation_not_admin`, other project admins the new neutral reason
  `installation_link_invalid`, and the linking human gets the account record change
  `not_admin` as a `security` item. One human holds an installation's link at a time,
  but an owner's link replaces a `not_admin` one (the replaced human gets `unlinked`);
  no App webhook.

### Changed

- deploy: the instance's GitHub App asks for the organisation permission Members
  (read-only) beside its repository read permissions (§11.4), for the owner check of an
  organisation installation; a membership read the forge refuses for want of it counts
  as a failed owner check. Installations on user accounts need nothing new.
