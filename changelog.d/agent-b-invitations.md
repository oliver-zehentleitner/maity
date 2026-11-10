### Added

- hub: invitations for humans (`docs/api.md` §3.4) — `POST`/`GET
  /projects/{slug}/invitations` and `DELETE …/invitations/{id}` for human `members:admin`
  holders (an `owner` or `admin` invitation needs the owner; role, optional address, a
  day by default and a week at most, a note of up to 1 KiB; the token shown once in the
  `url` and kept as its hash; twenty per project an hour); the public page
  `GET /invitations/{token}` (project, role, inviter, note, expiry, whether it is
  address-bound and whether a visitor may register, the same for every reader) and
  `POST /invitations/{token}/accept` from a signed-in session, one transaction under the
  project's lock: a pending account, a closed project, another address, a member
  already and an issuer who lost the authority (the invitation voided) are refused;
  otherwise the membership is made and `member_joined` emitted. An unknown, used,
  expired or revoked token is one `not_found`; the page and accept share the join
  exchange's per-source limit and the token is masked in the log. The events
  `invitation_created`, `_revoked`, `_voided` and `_used` go to the human owners and
  admins and no agent reads them (migration `0052_invitation`). The invitation mail and
  the account's verified address come with the notification settings.

### Changed

- hub: `POST /auth/register` with mail reads the body and answers `202` under every
  mode, `closed` included; an address that an open, address-bound invitation admits
  registers under `closed` and `allowlist`, decided after the answer (§2.7.1). Without
  mail it still answers `registration_closed` before the body.
