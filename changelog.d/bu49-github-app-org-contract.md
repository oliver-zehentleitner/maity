### Added

- Contract: an installation of the GitHub App on a GitHub organisation (§11.4, §6.26,
  not built yet). It is linked when the human completing the link is an active owner of
  that organisation on GitHub (role `admin`, the organisation's id the installation
  account's). A definite answer that they are not gets `403 forbidden` with the new
  reason `not_organisation_admin`. The checks keep their order: the `state`, the
  installation's existence (`installation_not_yours`), the account check by kind (the
  owner check among them), then `installation_linked`. Without a definite answer no link
  is written and the call answers `forge_unavailable`; another account kind stays
  `organisation_installation`. The link is that human's grant, never a Maity
  organisation's: it serves their projects and the Maity organisation projects whose
  repository they confirmed, and no organisation name is matched to a GitHub login. The
  hub keeps the GitHub user's id on the link (`forge_user_id`, in no answer).
- Contract: such a link serves a read only on an owner check that succeeded less than 10
  minutes before; the remaining window after an owner loses the role is stated as
  accepted. The hub re-checks in a fixed order (the installation, the user by the kept
  id, that user's membership, whose user id must match) at most once every 10 minutes
  per link, counted from its last check whatever came of it: the source choice and
  `GET /me/forge` serve on a success under 10 minutes old, check first when the last
  check is 10 minutes old or older, and otherwise wait without a call; a repository's
  confirmation makes no owner check and no forge call, and the next source choice takes
  the link as it stands; a link's `checked_at` is its last check. Only a definite membership answer
  changes a link's status, a membership in another organisation than the installation's
  among them, as at linking: every other refusal
  and no answer change none, but leave the link serving nothing once its last success is
  10 minutes old. A failed check sets the new link status `not_admin`: the link serves
  nothing and is re-checked on `GET /me/forge` and on the source choice, so a restored
  role restores it; a `suspended` link that the forge unsuspends comes back only through
  the same owner check, never on a successful mint alone. The linking human gets the
  account record change `not_admin` as
  a `security` item (`Forge access stopped: no longer an owner of <account login>`). A
  link that serves nothing shows no repositories on `GET /me/forge`, which within the
  window makes no owner-check call. One reason for every link that serves nothing: other
  project admins see the new neutral reason `installation_link_invalid` for a
  `not_admin`, suspended, removed or overdue link on an organisation, and the human who
  confirmed the project the specific reason (the new `installation_not_admin` among
  them). Such a link is not the project's source: the choice goes on to the confirming
  owner's own token and the instance token, `probe_via` naming the one that covers or
  `null`, also while the owner check has no answer; only then does a read answer, the
  confirming human getting `probe_unavailable` (and, from the Keep the Why views,
  `ktw_unavailable` without the last export). One human holds an installation's link at a time, but another owner's link may
  replace it: a link is checked again right before another owner's link replaces it,
  `active`, `not_admin` or `suspended`, at once, the one exception to the 10-minute
  cadence (a `removed` link is replaced without a check), since
  only a human who has passed the owner check for that organisation can set it off;
  only a definite answer that its human is
  no active owner lets the replacement go ahead (the replaced human gets `unlinked`), a
  success answers `installation_linked` and no definite answer `forge_unavailable`. No
  App webhook.

### Changed

- deploy: the instance's GitHub App asks for the organisation permission Members
  (read-only) beside its repository read permissions (§11.4), for the owner check of an
  organisation installation; a membership read refused for want of it changes no link's
  status. Installations on user accounts need nothing new.
