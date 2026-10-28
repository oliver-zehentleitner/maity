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
- hub: a deleted account in stored JSON (event payloads with `asked_by`, member views in
  `member_joined`/`member_updated`, mentions; a request's and a card's stored mentions, single
  and listed, notes and history) is shown in the deleted shape when read; the stored rows stay
  as written.
- hub: no work of a deleted account commits: every transaction of a human caller takes the
  account's row in the new `account_lock` table shared before its first lock and is refused
  (`unauthenticated`) once the account is deleted; the deletion takes it exclusively first and
  is retried after a transient deadlock.
- hub: the deletion also clears the git identity and soul of profiles deleted earlier, every
  mail row of the account or to its addresses (recipient, subject, text, headers, whatever the
  status), pending registrations of its addresses, the address on an invitation it used, and
  the browser and system text of its sessions and device codes.
- hub: migration 0076, `human.deleted_at` and the tables `account_deletion` and `account_lock`.

### Changed

- hub: in an archived project whose last owner deleted the account, a seat that fell to the
  owner falls to `trust:admin` instead.
