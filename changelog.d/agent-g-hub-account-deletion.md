### Added

- hub: a human deletes their own account (§2.9): `POST /me/deletion` with the password
  proof and the step-up records the request and mails a confirmation link (24 hours, single
  use, bound to the request) and a link to the export on the dashboard's account page;
  `DELETE /me/deletion` withdraws it, as do a newer request, a password change and a change
  or removal of the verified address; `GET /me` carries `deletion`. The link's page
  (`/mail/account-deletion/{token}`) asks once more and its button deletes the account in one
  transaction, or says why not (`namespace_owner`, `last_instance_admin`).
- hub: what a deletion does: every session and device code ends, the second factor and
  recovery codes go, pending mail to the account is dropped; the address, name, picture,
  settings and the account's records go; memberships end as removals do, the account's agent
  profiles are deleted as §6.3 deletes one (with git identity and soul), its runners removed
  with `agents: stop`, its open joins, enrollments and invitations revoked or voided, its
  pending placements closed, its personal requests withdrawn and a decision it held handed
  back to the admins. The account row stays with `deleted_at` and its handle stays taken.
- hub: a deleted account shows as `{"display_name": "Deleted account", "handle": null,
  "avatar_url": null, "deleted": true}` in member views, `asked_by`, a human event actor, a
  history entry's actor and a chat participant; `GET /admin/statistics` counts
  `totals.humans_deleted`, and `GET /admin/users` no longer lists a deleted account.
- hub: migration 0076, `human.deleted_at` and the table `account_deletion`.

### Changed

- hub: in an archived project whose last owner deleted the account, a seat that fell to the
  owner falls to `trust:admin` instead.
