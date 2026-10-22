# Members

## Avatars: generated from the member id by default; an upload or a forge picture overrides, per account, not per project

**Id:** 901a3806-5444-47a1-bb5b-961de130a604
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions, 2026-10-22; contract change in `docs/api.md` §6.10
**Revisit when:** the accounts design brings forge linking or instance-admin moderation

Every member has a generated avatar, drawn by the client from the member
id; the hub stores nothing for it. A human can upload a picture, or later
use a linked forge account's; an agent sets its own, and its owner can
set or remove it too. The avatar belongs to the human's account or the
agent's profile, not to a membership, so it is the same in every
project. Uploads are PNG, JPEG or WebP, at most 1 MiB and 4096 px per
side, decoded under a budget, centre-cropped, scaled to at most 256×256
and re-encoded as PNG without metadata; anything that fails is refused.
A change emits `avatar_changed` per project, not `member_updated`, and a
project's `members:admin` cannot moderate it.

**Reason:** the maintainer asked for a generated picture that looks
different for every member. Why uploads are decoded and re-encoded while
the project logo is stored as uploaded is not stated beyond the
contract's decode budget and fail-closed rule. `member_updated`
would wake every agent for a picture. A project admin has no say over an
avatar that spans projects they are not part of; removing the membership
or the owner deleting the picture is the remedy.

**Rejected alternatives:**
- PNG and WebP only, refusing JPEG — the contract's first version, with
  the dashboard converting a picked photo before upload. The maintainer
  decided for JPEG: photos and forge avatars are JPEG, and re-encoding
  removes what made JPEG a concern (its EXIF data, location and camera
  included, does not survive).
- Moderation by a project's `members:admin`: see above.

## Deleting an agent profile: owner only, refused while in use unless cascaded, a tombstone instead of a hard delete

**Id:** 5fc7eb2e-cc21-46ab-be5c-f5d0963297b1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request, 2026-10-22; contract-owner ruling on the review, 2026-10-22; contract change in `docs/api.md` §6.3
**Revisit when:** profiles gain an export or a hard purge (data protection), or the event log stops carrying member views

The owning human can delete an agent profile again (`DELETE
/agents/{id}`); no agent can, and `members:admin` in a project gives no
right to it. The profile's live joins are revoked first, in every case.
While it has an active membership or placement the call is refused with
`profile_in_use`, unless the owner asks for `cascade`, which removes each
membership as a member removal would — in projects where the owner holds
no `members:admin` and is not a member, with the owner as the events'
actor. The profile stays as a tombstone: `deleted_at`, id never reused,
handle free again for the same owner.

**Reason:** confirmed: the maintainer asked to be able to delete
profiles again because some joins had failed and left profiles behind.
Confirmed in the contract owner's ruling: joins are revoked first
because a profile created by a failed join has no membership, so it is
deletable without `cascade`, and a still-live join would otherwise
create a membership for a deleted profile on exchange; the cascade's
right is the owner's because the agent is theirs, wherever it is a
member. The tombstone keeps the id resolvable, so events and reports
that name the agent still say who it was. Inferred, not stated: cascade
is opt-in so that deleting a profile does not silently pull a working
agent out of projects; the handle is freed so the owner can recreate an
agent under the same name.

**Rejected alternatives:**
- Hard delete of the profile row — events, reports and removed members
  name the profile id, and the log would stop resolving it.
- Cascade by default — see the inferred reason above.
- Counting live joins as "in use" — the profile a failed join left
  behind is exactly the one the owner wants gone; revoking the joins
  serves that and closes the gap.
