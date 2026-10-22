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

## Removing a member clears every reports_to naming it — on members, join links and profile-creating placements alike

**Id:** 6b54c13b-818a-42ac-96a2-1ed8db68332d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner, 2026-10-22; contract change in `docs/api.md` §6.2 and §15.6

A `reports_to` lives in three places: on a membership, on a join link not
yet used, and in the join fields a placement stores for a profile it will
create. Removing the member it names sets it to `null` in all three, in
the removal's transaction. Only the first emits an event
(`member_updated`); clearing a placement's stored field emits no
`placement_updated` and does not move its `generation`. The exchange
applies a join's `reports_to` only while it names an active member,
`null` otherwise.

**Reason:** inferred from the rule's purpose — the chain never names a
former member — which a later join or a later pickup would otherwise
break. The join link or placement is still wanted; only its boss is gone,
and the admin who removed the boss is the one who can pick a new one,
on the membership once it exists. A placement's stored join fields are
in neither the placement view nor any event payload, and the runner
never reads them, so `placement_updated` would wake the runner and every
reader for a change none of them can see; a `generation` bump would
restart a running agent for nothing.

**Rejected alternatives:**
- Emit `placement_updated` for the cleared placement — the change is
  invisible in its payload and in the view; it would only wake readers.
- Refuse the exchange or the pickup when the boss is gone — the agent or
  runner fails for something it cannot fix.
- Revoke the join link or close the placement — the join itself is still
  wanted.
- Move `reports_to` up to the removed member's own boss — guesses an
  organisation decision that belongs to the admin; the existing members'
  rule already clears rather than moves.
