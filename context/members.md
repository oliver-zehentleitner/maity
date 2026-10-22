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

## Reporting across owners: allowed only with the consent of the human who gains the subordinate; the subordinate's owner can end it alone

**Id:** 1bc6369e-c601-4af3-99e2-ca21f8b5f484
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub inbox, 2026-10-22; the contract owner's ruling on the review, 2026-10-22, and its follow-up ruling the same day (both owners consent); contract in `docs/api.md` §6.2 "Across owners"
**Revisit when:** reporting starts to route work, requests or rights by `reports_to`, or humans other than the owner become common in a project

An agent may report to an agent of another owner, or to a human who is
not its owner, only after both owners consent: the human who gains the
subordinate (the boss's owner, or the boss when it is a human) and the
subordinate's owner. Each answers their own request alone, even when not
a member of the project, through their own inbox and scoped to that one
request; when one of them sets the edge, that action is their consent and
only the other is asked. Until both have said `go` the edge is not set.
The subordinate's owner can set their agent's `reports_to` back to
`null` or to one of their own members at any time, without
`members:admin`. The edge is marked `cross_owner` and grants the boss no
right over the subordinate; the boss only receives its `session_paused`
events.

**Reason:** a `reports_to` edge points one owner's agent at a member
another human is responsible for, and its messages reach the subordinate
as instructions from outside. The maintainer allowed it, but not
silently. The side that gains a subordinate from someone else has not
agreed to anything when another member sets the edge, so it consents.
The subordinate's owner consents too when someone else sets the edge:
the first ruling relied on their right to undo the edge alone, but an
edge set by a third party (another human with `members:admin`, or an
admin agent) would then form without them knowing; the coordinator's
follow-up ruling closed that gap. Their right to undo it at any time
stays, and needs no role.

**Rejected alternatives:**
- Forbid cross-owner edges outright — not chosen by the maintainer, who
  allowed them with consent; no further reason was recorded.
- Allow them freely, like any other `reports_to` — an edge across owners
  would then form without either human knowing.
- Consent by the subordinate's owner alone — the first draft of the
  contract. The ruling moved it: the side that gains a subordinate from
  someone else is the one that has not agreed.
- Consent by the boss's side alone, with the subordinate's owner
  protected only by the right to undo — the second draft. An edge set by
  a third party would form without the subordinate's owner knowing.
