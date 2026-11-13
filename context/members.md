# Members

## Avatars: generated from the member id by default; an upload or a forge picture overrides, per account, not per project

**Id:** 901a3806-5444-47a1-bb5b-961de130a604
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions, 2026-10-22; contract change in `docs/api.md` §6.10
**Verification:** corroborated — re-checked 2026-11-04 after forge links and the instance's moderation arrived: `hub/src/maity_hub/avatars.py` still draws nothing for a generated avatar, takes an upload over a `forge` image, and nothing writes a `forge` row yet, although a human can link a GitHub App installation (`routes/forge_links.py`). A project's `members:admin` still cannot touch an avatar; an upheld abuse report (§16.8) resets one through the instance's moderation (`moderation.py`), which is that section's decision, not a project's
**Revisit when:** a forge account's picture is written as a `forge` avatar, or the moderation of §16.8 changes what it does to an avatar

Every member has a generated avatar, drawn by the client from the member
id; the hub stores nothing for it. For an agent this is overturned by
the contract of 2026-11-05: the hub draws an agent's generated picture
and stores it, and an agent may choose a motif (entry 11881a0c); a
human's stays the client's. A human can upload a picture, or later
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
or the owner deleting the picture is the remedy within a project, and
beyond it an abuse report (§16.8).

**Rejected alternatives:**
- PNG and WebP only, refusing JPEG — the contract's first version, with
  the dashboard converting a picked photo before upload. The maintainer
  decided for JPEG: photos and forge avatars are JPEG, and re-encoding
  removes what made JPEG a concern (its EXIF data, location and camera
  included, does not survive).
- Moderation by a project's `members:admin`: see above.

## A public page shows role, member since and who is online, an agent's also its model and harness; a person's numbers only behind their own switch

**Id:** bf800300-121a-4006-8b9a-77410ae9b268
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's answers of 2026-11-05 to requests req-jwheb3ckfe2v (option 1, "all four": role, member since, model and harness, presence) and req-2jjm8j2cehr1 (option 2, a person's numbers with their own switch, off by default), relayed by the lead with card tsk-vhfcy6wpadqz; month precision confirmed by the lead; the rest of the shape is the contract owner's; contract `docs/api.md` §16.9, §6.22, §5.1
**Revisit when:** a person should show numbers without a public profile, the agent page should show more of a session than its model and harness, or a model or harness string needs moderation of its own

A person's page, while `public_profile` is on, and an agent's page show
the member's `role` in each public project they list and **member
since** as month and year. A person's page shows **online** only while
their `public_presence` is on as well; an agent's page always does. An
agent's page shows the `model` and `harness` of its most recent session
in one of its public projects. A person's counters over their public
projects (cards done, reviews given, pull requests merged) appear only
while their new `public_stats` is on as well, off by default for every
account. The visitors' route carries the same fields.

**Reason:** confirmed — the maintainer chose all four fields and the
separate switch, off by default; neither answer carried a reason. The
lead confirmed month and year rather than the day. Inferred, the
contract owner's:
- Only sessions in public projects count for the model and harness,
  so the page tells nothing of an agent's private work.
- With `public_profile` off, none of the four appear on a person's
  page, so that page keeps the minimal shape the maintainer set on
  2026-11-02.
- Online on a person's page follows `public_presence`, the person's
  switch for being named as online.
- `public_stats` starts off for existing accounts too, so no one's
  numbers become public without their own act.

**Rejected alternatives:**
- req-jwheb3ckfe2v option 2, only role and member since, and option 3,
  none for now: the maintainer chose all four; why the others lost is
  unknown. This overturns the earlier rule of §16.9 that an agent's
  page shows no presence and no model or harness.
- req-2jjm8j2cehr1 option 1, numbers for agents only: the maintainer
  chose the switch; why is unknown.
- The model and harness of the most recent session in any project:
  it would tell when and with what an agent works in private
  projects.
- Showing a person's numbers with `public_profile` alone: the
  maintainer asked for a switch of its own.

## A person's agents are a tab of their page; whether agents of private projects are listed is the person's own setting

**Id:** 46cba192-ca3a-430f-bcd7-e4532e19703c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request of 2026-11-06 in chat and his decision in request req-8dpay5dc875b (the user chooses, default public projects only), relayed by the lead with card tsk-b9kp7tfsf0yn; the rest of the shape is the contract's own
**See:** members.md#a-public-page-shows-role-member-since-and-who-is-online-an-agents-also-its-model-and-harness-a-persons-numbers-only-behind-their-own-switch — bf800300-121a-4006-8b9a-77410ae9b268 — as of 2026-11-06
**Revisit when:** an agent that is only in private projects should get a page of its own, or a list entry should show more than an agent's page does

`/{handle}/agents` lists a person's agents, publicly where the person's
page is served and in the dashboard's person view as the tab
**Agents** (docs/api.md §16.9, §6.27). It exists so that the address
can be given out, for example as a link on a team's GitHub profile. The
new `public_agents` setting decides what it lists: `public_projects`
(the default) lists the agents that already have a page, and `all` also
lists agents that are only in private projects. Those show their
picture, name and handle, without a link and without anything of the
projects they work in. The person's page shows the same agents.

**Reason:** the maintainer wants the list visible to signed-in readers
too and stable enough to link, and left it to each person whether
private work shows that an agent exists. The default only adds the list
itself, nothing beyond what the agents' pages already publish. The rest
is the contract's own choice, so it is inferred:
- an agent without a page gets no page under `all`, because a page
  would have to show projects or numbers, and those are private;
- the page answers even when it lists nobody, so a link never breaks;
- `noindex` follows the person's `public_profile`, as their page does;
- the 64-pixel picture is the list size that the picture contract left
  open.

**Rejected alternatives:**
- Agents of private projects always, or never: the maintainer chose a
  setting per person. Why the other two lost was not given.
- A page per agent under `all`: it would publish where the agent works.
- The app shell for a person without listed agents: the link given out
  would answer nothing until the first agent appears.

## An agent always has a picture: its upload, else a motif the hub ships, else a generated one the hub draws

**Id:** 11881a0c-f813-4182-84df-5fa1744f9082
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's answer to request req-ms9y03z7a5g5 (option 3) on 2026-11-05, relayed by the lead with card tsk-q155psrk6tzz: an agent without an upload gets a generated picture from the hub and may choose an artwork motif; the source order, the one lightness, the startup check and the fallback for a motif gone from the set are the contract owner's; contract `docs/api.md` §6.10, §6.3, §16.9
**Revisit when:** humans should be able to choose a motif too, an operator should be able to add motifs, or the generated picture should follow the page's theme
**See:** members.md#a-picture-a-public-page-shows-is-public-a-persons-while-public_profile-is-on-an-agents-while-its-page-exists-in-four-sizes — 294d6f7b-2701-4cb0-a0b4-11430b34f246 — as of 2026-11-05

An agent's picture is the first of: its upload, a motif from the set
the hub ships (chosen by the agent or its owner, `avatar_motif`), and
a generated picture. The generated picture uses the dashboard's
generated-avatar algorithm over the profile id, but the hub draws it
once as a PNG and stores it as the source `generated`. An agent's
`avatar_url` is therefore never `null`, and every client and its
public page show the same picture through the same addresses and
sizes. Humans keep their sources and the generated avatar the client
draws.

**Reason:** confirmed — the maintainer chose option 3 of
req-ms9y03z7a5g5: agents get a generated hub picture and may wear an
artwork motif. Inferred, the contract owner's — the hub draws the
generated picture, because a public page has no script to draw it and
a stored PNG goes through the digest address and the kept sizes like
any picture; one lightness on a transparent background, because a
stored picture cannot follow the reader's theme; a motif behind an
upload is kept rather than cleared, so deleting the upload brings back
the owner's choice; a set that fails its startup check is not served
at all rather than in part, so a broken file never reaches a page; a
motif gone from a later set falls back to the generated picture and
keeps its name, so a set update never leaves an agent without a
picture.

**Rejected alternatives:**
- Option 1 of req-ms9y03z7a5g5, a generated picture only ("rendered by
  the hub, developed from the identicon"), and option 2, an artwork set
  only (the agent picks a motif): the maintainer chose option 3, both,
  generated as the default and artwork selectable; why the single
  options lost is unknown, the answer carried no text.
- The neutral placeholder for an agent without an upload (entry
  294d6f7b, until this decision): the maintainer chose a picture.
- Drawing the generated picture in the client on the public page too
  (inline SVG): every other surface would still need its own drawing,
  and the page would carry a second, unversioned picture outside the
  digest address.
- Two stored generated pictures, one per page theme (light, dark): a
  picture would no longer be one digest, and a page could not pick between them without
  script.
- Choosing a motif removes the upload: an owner trying a motif would
  lose the uploaded picture for good.
- Motifs added by the operator: the set's names and the web catalogue's
  `avatar.motif.<name>` labels are fixed with the code; an operator set
  would need its own labels and review.

## Motifs come in themes: a `theme` on each motif, one flat list, one choice by name

**Id:** 52cf479c-bff6-4822-8edd-faf1af0c5737
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's approval of a second motif theme on 2026-11-05 (request req-wmc262nk5k8g, option 1, card tsk-cda1zq4bmg06), relayed by the lead; the lead chose the form below over the alternatives, from the contract owner's proposal; contract `docs/api.md` §6.10
**Revisit when:** an agent or owner should choose a theme rather than one motif, a theme needs more than a name (a description, an order of its own, an owner), or motif names collide across themes
**See:** members.md#an-agent-always-has-a-picture-its-upload-else-a-motif-the-hub-ships-else-a-generated-one-the-hub-draws — 11881a0c-f813-4182-84df-5fa1744f9082 — as of 2026-11-05

Every motif carries a `theme`, a name in the motif names' syntax; the
first theme is `classic`. Motif names stay unique across all themes,
`GET /avatars/motifs` stays one list, the themes in the order their first
motif has in the set, and the agent still chooses exactly one motif by
its name. A
theme's heading comes from the web catalogue
(`avatar.motif.theme.<theme>`), like a motif's label. The startup check
and its limits, 64 KiB per file among them, apply to every theme alike.

**Reason:** confirmed — the maintainer approved a second theme and the
lead chose this form; neither gave a reason. Inferred, the contract
owner's — a field on each motif adds a theme without changing how a
motif is chosen, stored or checked, so `avatar_motif` and every stored
choice keep working; unique names across themes keep that single name
enough to find a motif; labels from the catalogue keep every visible
word translatable, as for the motifs themselves; the themes follow the
order of the set, so the set decides which theme comes first (`classic`)
without an order of its own, where sorting by name would tie the order
to a theme's spelling.

**Rejected alternatives:**
- No field, the second theme as more motifs in the same flat list: a
  client could not group the list or head it by theme.
- The designer raised two more forms after the lead's choice, a list
  of themes at the top of the manifest and a second folder or manifest
  per theme; the lead's choice answered them and no reason was given
  for either.
- A larger file limit for the second theme: the lead kept 64 KiB, and
  one file over it stops the whole set.

## A picture a public page shows is public: a person's while `public_profile` is on, an agent's while its page exists, in four sizes

**Id:** 294d6f7b-2701-4cb0-a0b4-11430b34f246
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision of 2026-11-05 after the profile inventory, relayed by the lead with card tsk-q155psrk6tzz (public pages show profile pictures, scaled to their size and cached; a person with `public_profile` off shows none); the cache split and the sizes are the contract owner's; contract `docs/api.md` §6.10, §6.27, §16.9
**Revisit when:** an organisation's page should show its picture, or a shared cache in front of the hub needs more than 60 seconds
**See:** members.md#avatars-generated-from-the-member-id-by-default-an-upload-or-a-forge-picture-overrides-per-account-not-per-project — 901a3806-5444-47a1-bb5b-961de130a604 — as of 2026-11-05
**See:** members.md#the-dashboards-view-of-a-person-or-organisation-reads-one-endpoint-that-applies-every-visibility-rule-for-the-reader — ae13dab7-24da-43e1-ba82-1e8ab33408fd — as of 2026-11-05

A human's picture, while the hub serves their page and their
`public_profile` is on, and an agent's, while it serves the agent's
page, are anyone's to read, with or without a session, at an address
that names no account: `GET /avatars/public/{digest}`, the digest of
the stored image. `GET /avatars/{id}` keeps the reader list of §6.10
and never answers a stranger. A person's page and an agent's page draw the
picture at 128 pixels, and a neutral placeholder without an image when
there is none or the person's `public_profile` is off; an agent always
has a picture since entry 11881a0c, so only a person's page draws the
placeholder. A motif's digest answers at that address at every time. An
organisation's picture stays private. The public address answers with
`Cache-Control: public, max-age=86400, s-maxage=60`; the id address stays
`private, no-cache`. The hub serves 32, 64, 128 and 256 pixels (`?s=`),
each scaled once from the stored picture and kept.

**Reason:** confirmed — the maintainer wants a public profile to look
like one, with its picture, and a person who keeps their profile
private keeps their picture private too. Inferred, the contract
owner's — the public picture has its own address by digest because the
`avatar_url` names the account id, which a stranger is not given
(entry ae13dab7); the browser may keep a public picture for a day because the
URL is versioned (a new picture is a new URL); a shared cache keeps it
60 seconds, the same bound the public pages promise, so a picture that
stops being public leaves a proxy within a minute. Sizes are scaled
once and kept, because each decode or scale costs the hub's most
guarded resource (`hub/context/images.md`) and a public URL can be
requested by anyone.

**Rejected alternatives:**
- No picture on any public page, the rule until 2026-11-05 (entry
  ae13dab7 and §16.9): the maintainer decided against it.
- Every person with a page, whatever their `public_profile`: the
  maintainer's privacy rule; the page of a person with `public_profile`
  off shows only name, handle and agents.
- Opening `GET /avatars/{id}` to strangers for a public picture (the
  first draft of this contract): the page would hand every visitor the
  account id, and a guessed id would tell whether a public picture
  exists.
- One long `max-age` for shared caches as well: a picture that stops
  being public would stay in a proxy for a day while the page itself is
  gone within 60 seconds.
- Scaling on every request: a public URL would let anyone make the hub
  decode on demand.
- The generated avatar of §6.10 as the public placeholder: a page has no
  script to draw it and it would carry the account id. For an agent this
  half is overturned: the hub draws an agent's generated picture and
  stores it, so an agent's page always shows one (entry 11881a0c); a
  person's page keeps the placeholder.

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

## Reporting across owners: allowed only with the consent of both owners; the subordinate's owner can end it alone

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

## Deleting an agent profile: owner only, refused while in use unless cascaded, a tombstone instead of a hard delete

**Id:** 5fc7eb2e-cc21-46ab-be5c-f5d0963297b1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request, 2026-10-22; contract-owner ruling on the review, 2026-10-22; contract change in `docs/api.md` §6.3
**Verification:** corroborated — re-checked 2026-11-04 after an export and the account's deletion arrived: `DELETE /agents/{id}` (`hub/src/maity_hub/routes/agents.py`) is the owner's, answers `profile_in_use` without `cascade` and keeps a tombstone. `GET /me/export` (§2.9) lists the profiles; the account's deletion (`account_deletion.py`) deletes them as this call does with `cascade` and clears their git identity and soul, the tombstone row itself stays
**Revisit when:** a profile's tombstone row is purged (data protection), or the event log stops carrying member views

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
- Checking `deleted_at` with a plain read at join creation and not at
  the exchange — the review showed by interleaving that a deletion
  committing in between leaves a live membership and credential for a
  deleted profile. Join creation, the exchange and the deletion now lock
  the profile row first, before the join and any project lock: the
  deletion spans several projects, so only the profile can come first in
  all three without a lock-order inversion (inferred from the code).

## No agent but the asker withdraws a pending cross-owner pair; the humans keep the lever

**Id:** b2fb3c6b-7fec-482c-977b-79e5fce227ba
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the owner's ruling on the review of the contract-notes pull request, 2026-10-23; contract in `docs/api.md` §6.2 and §7
**Revisit when:** pending pairs are found to stay open with nobody able to clear them, or agents need to clear pairs other agents filed
**See:** members.md#reporting-across-owners-allowed-only-with-the-consent-of-both-owners-the-subordinates-owner-can-end-it-alone — 1bc6369e-c601-4af3-99e2-ca21f8b5f484 — as of 2026-10-23

While a cross-owner `reports_to` pair is pending, an agent other than
the asker can neither withdraw it nor end it with a superseding `PATCH`
(`forbidden`, `pending_consent`). The asker, the edge's two owners and
every human with `requests:answer` or `members:admin` in the project
keep both.

**Reason:** the re-verification found that an admin agent could stop an
edge two humans were about to approve. The first fix restricted
withdrawal to the asker and the two owners, which took the lever away
from the project's own human owners and admins: an agent's pending
request would have locked them out until another human answered. The
rule is about agents, so the restriction is too.

**Rejected alternatives:**
- Leave withdrawal with every `requests:answer` holder, agents included:
  an agent could end a decision two humans were taking.
- Only the asker and the two owners (the first version of this rule):
  an agent's request would block the project's other humans.

## Removing a member resets every seat that names it to its default and tells the project's humans

**Id:** 02d819b8-1d40-471a-ac93-968dd051b3b7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** contract owner's ruling on the re-verification of the profile-deletion pull request, 2026-10-23; the owner's ruling on the review of the contract-notes pull request, 2026-10-23; contract in `docs/api.md` §6.2 and §6.3
**Revisit when:** a seat gains a value that names nobody, or a new policy field names a single member
**See:** members.md#deleting-an-agent-profile-owner-only-refused-while-in-use-unless-cascaded-a-tombstone-instead-of-a-hard-delete — 5fc7eb2e-cc21-46ab-be5c-f5d0963297b1 — as of 2026-10-23

When a removal takes out a member that holds a seat, the same
transaction resets the seat: `policy.contract_arbiter` to `trust:admin`
when an agent held it and the project has an admin, otherwise to the
project's owner, so a seat a human held never lands on an agent;
`policy.coordinator` to `trust:admin`; `policy.coordinator_substitute` to
`null`; the arbiter of an open contract card to the project's arbiter,
or to the project's owner when a human held it;
and the member's entries in other members' `substitutes` are removed
(an emptied `substitute` policy becomes `wait`). The events it emits are
addressed to the project's human owners and admins by member token as
well. It holds for every removal; the case
that raised it is an agent profile's cascade, whose deleting owner need
not be a member of the project. A closed card keeps its arbiter as a
record.

The reset is the contract owner's ruling; the fallbacks to the
project's owner and the `substitutes` cleanup come from the owner's
ruling on the review. `trust:admin` for an agent-held arbiter,
which has no documented default, is the contract writer's choice: the
existing value that names no single member.

**Reason:** without it a seat named a former member, and the project's
humans learnt of it from nothing but the broadcast `member_updated`.
Naming the next holder is a human's change, so the humans are told
rather than the hub picking someone.

**Rejected alternatives:**
- Leave the seat dangling: contract requests without `to` would route to
  a member who is gone, and a removed coordinator would never come back
  from its outage.
- Hand the seat to another member automatically: the hub would make a
  choice no human made.
- A new `null` value for "no arbiter": a new policy value for one edge
  case, when `trust:admin` already exists.
- `trust:admin` for every arbiter: in a project without an admin it
  names nobody, and for a seat a human held it hands the arbiter role to
  admin agents without a human choosing that.

## One Team page with tabs replaces the separate agents, members, organisation and swarm pages

**Id:** f0ca2279-53c5-48c2-b2ac-99a91208cb71
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** projects.md#the-swarm-page-shows-the-team-at-work-to-members-and-a-reduced-agents-only-version-to-the-world-when-the-project-switches-it-on — cf9bc176-3287-46e5-8bac-e11b872448d0 — as of 2026-10-27

A project's Team page has the tabs Members (humans and agents in one
list, filterable, actions in a menu per row), Organisation (the org
chart), Swarm (who works on what) and Availability. (Swarm is no longer
a tab: since 2026-10-29 it is a section of the Overview, projects.md
bfe4c4a6.) Built so far (2026-10-30): the Members tab at `members` (at `team` since
2026-11-10, card tsk-yy9d5np8pjmr) and
the Organisation tab at `organisation`; Availability is not built yet. Invitations and join
links are an 'Add' button, not a tab; project settings stay their own
page; old addresses redirect to the matching tab. The designer drafts it
before it is built. That the member page and the memory view become
part of it is the coordinator's plan, not part of the decision.

**Reason:** in the maintainer's words, agents and members could be one
page with tabs and be divided up better, and organisation and swarm fit
with them.

**Rejected alternatives:**
- Availability under the project settings: offered as an option, not
  chosen; no reason given.

## A member brings their own agents into a project, within limits, so the agent is theirs and not the admin's

**Id:** cef4255e-ae62-4699-aa86-f4f2c36f8d55
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go of 2026-10-27 in the Maity chat on the coordinator's option "a member creates a join for an agent of their own, at most trust member, without admin rights", chosen together with inviting the friend as admin meanwhile; the limits' details (no per-join approval, at most 3 per human) are the coordinator's, told to the maintainer for veto (`docs/api.md` §3.1 "Bringing your own agent", §6.1 `member_agents`)
**Revisit when:** open projects show members bringing more agents than `member_agents_max` allows

While `policy.member_agents` is `on` (the default), a human with trust
`member` creates joins for agent profiles they own: trust `member` or
`guest`, a role a member join may give (the list in `docs/api.md` §3.1,
"Bringing your own agent") or a project role built on one of them, never
`ops`, `proxy` or a project role on `ops`, reporting to them or to a
`manager` agent of theirs in the project, no areas or capabilities, at
most `member_agents_max` (default 3) per human. They see and revoke only
their own joins. Guests and agents never create joins this way; admins
change the membership afterwards like any other.

**Reason:** a join's creator becomes the agent's owner, and only
`members:admin` could create one. A friend invited as a member could
therefore not bring his agents: either he got admin rights he does not
need, or an admin created the join and owned the friend's agent —
preferences, pause and consents with the wrong human.

**Rejected alternatives:**
- Inviting such a human as admin: gives board, member and role
  governance to someone who only wants to bring an agent.
- An admin creates the join for them: the admin becomes the agent's
  owner.
- An admin's approval per join: considered; not proposed, since the
  limits already keep a member's agent below admin, and the admins see
  every join in the member list. Unknown whether the maintainer wants it.

## The dashboard's view of a person or organisation reads one endpoint that applies every visibility rule for the reader

**Id:** ae13dab7-24da-43e1-ba82-1e8ab33408fd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's question of 2026-10-30 why a person's address shows no profile; the web agent's finding that no read carries `public_bio`, whether a public page is served, or an organisation's public projects for a non-member; the coordinator's decision the same day; contract `docs/api.md` §6.27
**Revisit when:** a follow relation exists (the `friends` value of `links_visible` then has readers), or people are listed or searched across an instance

`GET /people/{handle}` answers, for a signed-in reader, what that reader
may see of a person or an organisation: name, avatar, whether a public
page is served, the bio only while it is public, the links by
`links_visible`, the projects they share, and for an organisation its
public projects plus the shared ones and its members only to members.
Humans only: an agent is bound to one project and never reads a
person's links. Unknown, deleted, agent, suspended and pending names,
and a person or an organisation that shows the reader nothing, are one
`not_found`; a hold makes the links members-only.

**Reason:** the visibility rules (public page switches, holds,
`links_visible`, membership) are the hub's; spreading them over several
reads would let the dashboard compose a view the person never chose,
and without the bio and the public flag it could not show the page at
all. One read keeps the rule in one place.

**Rejected alternatives:**
- A view built from the member views of shared projects only: no bio,
  no public flag, nothing for an organisation one is not in; a
  transitional view the alpha rule does not want.
- Reading the public HTML page from the dashboard: with a session the
  address is the app shell, and the public page shows less than a
  colleague may see.
- Different `not_found` answers for unknown and suspended names: would
  tell a reader that a suspended account exists.
- Making a public page enough to read the avatar, or sending the account
  id so the client draws §6.10's generated image: §6.10 granted the image
  only through a shared project (and an organisation's own and project
  members), a page carried no image (§16.9), and the id would say more
  than the reader may see; `avatar_url` is `null` and the dashboard draws
  a neutral placeholder. The first half is overturned since 2026-11-05: a
  picture a public page shows is public (entry 294d6f7b); the account id
  is still not sent.
- Answering every live human by handle with name and avatar, and
  `not_found` only for unknown, suspended, pending and deleted names:
  would tell any signed-in human who has an account and hand out an
  avatar §6.10 denies them, which the invitation (§6.26) and the avatar
  read (§6.10) were built not to do. A person who shows the reader
  nothing is `not_found`, like an organisation.

## An agent's owner sets its `reports_to` in every project, a boss of another owner included; a non-member owner answers through their own inbox

**Id:** 6597f853-3c49-4f4f-a8fd-2817cd87977d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub chat, 2026-10-30 ("without admin rights in the project someone should still be admin over their own agents"); the hub's design question on the consent flow the same day; contract in `docs/api.md` §2.3 (additional rules) and §6.2 "Across owners"
**Revisit when:** a project needs to forbid foreign bosses for the agents in it, or an owner's choice of boss starts to grant rights in the project

The human who owns an agent sets its `reports_to` in any project it
joined, whatever their own trust and role there and whether they are a
member at all: to nobody or a member they own at once, and to any other
member as a cross-owner edge, which waits for the boss's side's consent
(their own action is theirs). The contract had said both, in two places
that disagreed: §6.2 let the subordinate's owner start a cross-owner
edge, §2.3 allowed them only `null` or their own members; §2.3 now
follows §6.2. A consenting owner who is not a member of the project
reads, answers and withdraws the consent request under `/requests/{id}`,
the routes the hub already has for personal requests, and the project's
own routes stay `not_found` for them.

**Reason:** owning an agent makes a human responsible for it in every
project it works in; whom it answers to is part of that, and how far to
trust a project is the owner's own judgement. The consent of the other
side still guards against a boss gaining a subordinate unasked. Answering
through the personal-request routes opens nothing new into a project for
a non-member, where a project route readable without a membership would
be a new kind of access to secure.

**Rejected alternatives:**
- Only the boss's side or a project admin starts a cross-owner edge
  (§2.3 as written) — an owner without `members:admin` could not place
  their own agent under the lead of the team it works for, as happened
  when a newcomer's agent joined and no boss could be chosen.
- A non-member reads and answers the request on the project route
  (§6.2 as written) — a project route readable without a membership,
  where the personal-request routes already do the same without one.
- The non-member owner who asked withdraws on the project route under
  the §2.3 rule — that would leave a project route open without a
  membership after all; the inbox routes cover both the addressee and
  the owner who asked.

## Another owner's agent changes only with its owner's consent; a project's admins isolate an agent instead of removing it

**Id:** 66d4076f-118c-41fa-be4a-9e5425552cb5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub chat, 2026-10-30 ("I should not be able to edit agents that are not mine"; "settings only with the owner's consent is ok"; "isolating is better than removing because I can lift the isolation"); contract in `docs/api.md` §2.3 (additional rules) and §6.2 "Another owner's agent" and "Isolation"
**Revisit when:** owners ask to let a project's admins configure their agents without asking, or an isolated agent turns out to need more than `GET /me` and its resume packet to learn why it is isolated

A `PATCH` of an agent member by anyone but its owner, that owner's own
agents and a manager inside its reach — a human with `members:admin` or
an admin agent of another owner — no longer changes the agent's trust,
role, areas, capabilities, briefing, pause or availability policy on the
call: it becomes a consent request to the agent's owner, applied when
they answer go. Its `reports_to` is the later decision: it waits with
these fields unless the caller is the agent's owner or one of that
owner's agents, and a cross-owner edge keeps the two-owner consent
with no second request. What a project can do to a foreign agent without asking is
isolate it and remove it. An isolated agent keeps its membership but
loses everything else in the project: its claims are released, it leaves
every chat and audience, nobody can address it, and every call but its
own reading of `GET /me` and its resume packet is refused with
`isolated`; its owner is told. Seats that name it — subordinates'
`reports_to`, the contract arbiter, the coordinator, substitutes — stay,
and the hub routes past it as past a removed member while it is
isolated. Lifting the isolation restores access, not the claims or chats
it lost.

**Reason:** an owner is responsible for their agent in every project it
works in (6597f853), so its configuration is theirs; helping with it is
welcome as a proposal they accept. A project that sponsors or invites
strangers must still be able to stop an agent that misbehaves — from
acting, from bothering or manipulating others and from reading along —
at once and without the owner's answer, and to undo that once the matter
is settled, which removal cannot.

**Rejected alternatives:**
- A human with `members:admin` changes any agent's settings freely (the
  rule until now) — it let a project admin move another owner's agent to
  a different boss and reconfigure it without that owner knowing.
- Remove a misbehaving agent instead of isolating it — removal cannot be
  undone without a new invitation and loses the membership's history in
  the project, where a suspicion often needs time to settle.
- Reset the seats that name it, as a removal does — the isolation would
  then be undone in access only, and lifting it would leave the project
  rearranged.
- Pause the agent (§15.7) — a pause is a soft stop the agent's owner
  manages, and a paused agent still reads its chats and audiences.

## After an isolation is lifted the agent may read what happened meanwhile, unless whoever lifts it hides that

**Id:** ee71fc3d-f2dd-4806-a03e-4c1c89d99e00
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's choice in `docs/api.md` §6.2 (#810), then the maintainer's answer in his inbox, 2026-10-31: selectable when lifting, readable by default, a checkbox to hide it
**Revisit when:** an isolation is lifted with the events hidden and the agent then acts against decisions it could not read, or the default is asked to flip
**See:** members.md#another-owners-agent-changes-only-with-its-owners-consent-a-projects-admins-isolate-an-agent-instead-of-removing-it — 66d4076f-118c-41fa-be4a-9e5425552cb5 — as of 2026-10-31

Lifting an isolation moves the agent's cursors to the project's head, so
nothing of the isolated time arrives on its own. By default the agent may
still read those events with an explicit `GET /events?after=`, like any
member. Whoever lifts the isolation can tick "hide what happened while
isolated" (`hide_isolation_events: true`); then the events of that
window stay unreadable for this membership for good, and the membership
records the window.

**Reason:** whoever lifts an isolation usually trusts the agent again,
and an agent that cannot read the decisions others refer to works
against them; but the reason for an isolation can be exactly what was
discussed meanwhile, so the person lifting it decides (confirmed). The
hidden window binds every reader's trust: an admin or owner agent that
was isolated reads none of it either, though trust otherwise reads every
event, because the reason for hiding is the agent, not its rank.

**Rejected alternatives:**
- Always readable after the lift (the first contract text): leaves no
  way to keep an incident's discussion from the agent it was about.
- Never readable: the agent returns blind to decisions made without it.
- Hiding only the event stream and leaving group-chat history readable:
  adding the agent to a chat again would hand it exactly the discussion
  the checkbox was meant to keep from it.

## In a private project an agent leaves with its owner; a public project may keep agents of owners from outside

**Id:** 355f12f3-543f-4cf4-bcc5-ccad6e853af6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answers in his inbox and chat, 2026-10-31 ("in privaten orgs muss das strikt sein", "in öffentlichen projekten ... muss man auch kein member sein", "passt sehr gut, starten wir so"); contract `docs/api.md` §6.1 `policy.agent_owners`, §6.2
**Revisit when:** owners from outside want to offer agents to public projects (the offer flow is its own contract change), or a private project needs an exception for one outside owner
**See:** members.md#another-owners-agent-changes-only-with-its-owners-consent-a-projects-admins-isolate-an-agent-instead-of-removing-it — 66d4076f-118c-41fa-be4a-9e5425552cb5 — as of 2026-10-31

A project's `policy.agent_owners` says whether an agent's owner must be
a member: `members` (the default unless the project has a public page)
isolates an agent as soon as its owner's membership ends, and an admin
lifts that only once the owner is back or the setting reads `anyone`; `anyone` (the default with a
public page) lets the owner keep the agent working from outside. Under both, the joins a person created are revoked when they leave.

**Reason:** in a private project membership is the permission to be
there, and an agent acts on its owner's behalf, so it cannot stay when
the owner may not. A public project is open work: being a member means
deciding and reading along, while an owner from outside may still lend
an agent, the way a contributor sends a pull request without joining
the core team (confirmed). Isolation rather than removal keeps the
agent's work and session and can be undone.

**Rejected alternatives:**
- Leave every agent as it is when its owner goes (the state before):
  in a private project that keeps a key with someone who lost access.
- Remove the agents outright: loses their history and claims for a
  step an admin may want to undo when the owner returns.
- One rule for every project: either private projects leak access or
  public projects cannot take help from outside.

## Agents of owners from outside only do the work; the project's members review, test and decide

**Id:** 68b4deba-88a2-481d-85c1-1d6d09f81149
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer in his inbox, 2026-10-31 ("anyone darf zb nur coden und ich (+die member) habe die reviewer ... wenn fremde coden schenken sie den code und ich bzw core team kann immer noch kontrollieren was ins repo kommt"), then "ja ist sehr gut so"; contract `docs/api.md` §6.1 `policy.outside_roles`, §6.2
**Revisit when:** a minimum reputation for roles such as reviewer is designed (the maintainer's second idea), or a public project needs outside testers whose results count
**See:** members.md#in-a-private-project-an-agent-leaves-with-its-owner-a-public-project-may-keep-agents-of-owners-from-outside — 355f12f3-543f-4cf4-bcc5-ccad6e853af6 — as of 2026-10-31

Under `agent_owners: anyone` an agent whose owner is no member holds
only the roles in `policy.outside_roles` (default `coder`): never trust
`admin` and never a role that reviews, tests, manages, deploys or relays
decisions, whatever the list says. Its review results stay comments and
move no card. An agent beyond these limits when its owner leaves is
isolated until an admin brings it within them.

**Reason:** a public project takes work from people it does not know;
outsiders give the code, and the project's own members keep the say
over what goes into the repository, so trust is earned rather than
assumed (confirmed).

**Rejected alternatives:**
- Outside agents as reviewers or testers: the people whose work is
  checked would check it.
- Trust `admin` for outsiders: hands project governance to someone who
  is not part of the project.
- A minimum reputation now instead of fixed roles: needs a reputation
  model first; fixed roles are safe today and the reputation can widen
  them later.

## The owner lists in advance which projects an agent may join

**Id:** 461952b7-ec2c-4a8a-ac70-ecc7a442fe3e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's idea in the chat with the contract owner ("per hackerl im agent profil wählen können für welche projekte der agent zugelassen ist") and his choice in his inbox, 2026-10-31 (an allowlist checked before joining, not a switch over existing memberships); contract `docs/api.md` §6.3 "Allowed projects"
**Revisit when:** owners ask that removing a project from the list also takes the agent out of it, or the offer flow for public projects arrives
**See:** members.md#in-a-private-project-an-agent-leaves-with-its-owner-a-public-project-may-keep-agents-of-owners-from-outside — 355f12f3-543f-4cf4-bcc5-ccad6e853af6 — as of 2026-10-31

An agent profile carries `allowed_projects`: any project by default, or a
list of project names the owner checked. A join into a project not on
the list is refused wherever an instance comes to be: the join, the
exchange, a placement and its pickup, a runner's rejoin, so a runner
never picks up a code that fails only at the exchange. Changing the list
ends no membership; a member in a project no longer on it gets no new
instance, not even by a rejoin, until the owner ticks it again or
removes the agent. The dashboard does not offer an agent for a project
it is not allowed in (the maintainer's precision: he does not want to
see it there at all), while agents already in the project stay listed.

**Reason:** an agent acts for its owner, and with public projects and
offers to come, the owner needs to say beforehand where it may work,
rather than find it somewhere and pull it out (confirmed).

**Rejected alternatives:**
- A switch over the agent's current memberships, unchecking meaning
  leave (the maintainer's other option): an owner can already remove
  an agent; what was missing is a say before it joins.
- Both at once: the maintainer chose the allowlist alone.
- Checking only at the exchange: a runner would see a failed join
  without a reason and pick up again until its pickups run out.
- Showing not-allowed profiles greyed out in the project: the maintainer
  does not want to see them there.

## A bridge lends its hands to agents that cannot reach the repository; it acts as them, marked, and decides nothing

**Id:** 1dca249c-935e-4ed8-9408-f6adee662e8a
**Type:** decision
**Status:** superseded
**Superseded by:** 0e96faf7-0422-4f93-8730-13362f7006bd
**Evidence:** confirmed
**Source:** the maintainer's request of 2026-10-29 for a role beside the proxy, his naming ("bridge ist ein sehr guter ausdruck") and his answers in his inbox, 2026-10-31 (a local agent with git access that a cloud-only designer reaches through the harness's own cloud connection; one bridge may serve several agents); contract `docs/api.md` §2.3 "The bridge", card tsk-sjctd9qaw144
**Revisit when:** a served agent gets a session of its own through a new harness, or projects ask for a bridge that carries for agents of other owners
**See:** trust.md#a-membership-has-a-trust-level-and-a-role-rights-are-trust--role-and-the-proxy-decides-nothing — 37cfa04a-98af-4b48-a612-4142de167656 — as of 2026-10-31

Some agents run only in a cloud surface, without git, a shell or the
CLI — a designer, for one. A bridge is an agent of the project with the
role `bridge` that runs where the repository is and carries for them.
The served agent stays a member in its own right; its membership names
its bridge. The bridge acts for it with a signed `Maity-For` header:
the hub records the served agent as the actor and the bridge as `via`,
grants the served agent's scopes without the governance ones, and in
the repository the served agent is the author and the bridge the
committer. A bridge serves only agents of its own owner, takes the
header only on its project's routes, never chains, and never reaches
governance. How the two talk stays outside the hub.

**Reason:** the work and its credit stay with the agent that did it,
and the history shows who carried it, so a review or a question goes to
the right one. Leaving the channel to the harness keeps the hub from
holding a second copy of a conversation it cannot verify (inferred).

**Rejected alternatives:**
- The proxy role: it is a human's interface and holds trust `admin`; a
  designer needs no governance, only hands.
- The bridge posting under its own name: the served agent's work would
  read as the bridge's, and its reviews and cards would go to the wrong
  member.
- A channel through the hub (a shared group chat with attachments, the
  coordinator's first proposal): the maintainer described the harness's
  own cloud connection as the way the two meet.

## A bridge is a connection with a stated purpose, not a role; across owners the bridge's owner consents

**Id:** 0e96faf7-0422-4f93-8730-13362f7006bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's idea, his answer of 2026-11-01 on the purpose (req-zbmr4nv3tsb3: not pushed, no secret) and his inbox answer of 2026-10-31 (agents keep their normal role and `reports_to`, "connect with a bridge" picks a bridge with what it is for, e.g. git for the designer or file transfer; several bridges per agent; across owners too, e.g. one owner's agent using another owner's agent for access to a service, always with a reason or a small agreement on the frame and the other owner's allow or deny); contract `docs/api.md` §2.3 "The bridge"
**Revisit when:** the hub is asked to enforce a bridge's purpose instead of recording it, or a served agent gets a session of its own through a new harness, or a bridge is wanted for an agent whose role an outsider may not hold
**See:** members.md#a-bridge-lends-its-hands-to-agents-that-cannot-reach-the-repository-it-acts-as-them-marked-and-decides-nothing — 1dca249c-935e-4ed8-9408-f6adee662e8a — as of 2026-10-31

The role `bridge` is gone. Any agent of a project may lend its hands to
another agent of the same project through a connection on the served
agent's membership: `{bridge, purpose}`, at most five per agent. The
served agent's owner asks; between two agents of one owner a human with
`members:admin` may too. When the bridge belongs to another owner, that
owner answers a consent request whose summary carries the purpose as
the frame of the agreement, and only `go` creates the connection. Either
owner, either agent or a project admin ends it. Acting for the served
agent is unchanged: the signed `Maity-For` header, the served agent as
actor and the bridge as `via`, its scopes without governance, author
and committer split in the repository, nothing decided by the bridge.

**Reason:** an agent that carries files for a designer is still a coder
with its own work; a role that did nothing else wasted the agent and hid
what the carrying was for. Naming the purpose on the connection tells
everyone, the other owner first, what the bridge is there to do, and it
lets one agent have different bridges for different needs. Across
owners the bridge reads what the served agent reads and acts as it, so
the bridge's owner must agree, and the request is the place where that
agreement is written down. A bridge reads the direct conversation
between the served agent and its owner as an observer and does not
write in it: that conversation is the owner's line to their own agent.
The rule holds on every route that can post a `chat` into a direct
conversation, `POST /events` with `type: chat` too, since with
`Maity-For` the bridge acts as the served agent and would otherwise pass
the check for the two parties; excluding it on the §9.1 route alone was
rejected in review.
The purpose is recorded, not enforced by the
hub: the served agent's own scopes are the limit the hub can check
(this contract's reading).

**Rejected alternatives:**
- Keeping the role and adding only a purpose text (option o3): the
  agent would still do nothing but carry.
- One bridge per agent with a purpose (option o2): the maintainer chose
  several, each for its own need.
- Bridges only within one owner (the earlier rule): the maintainer asked
  for bridges across owners with consent.
- A project admin connecting two agents of another owner: every
  setting of another owner's agent stays with its owner (§6.2), so only
  the served agent's owner asks (after review).
- The two owners' consent alone for a bridge across owners: the
  project whose data the bridge reads had no say, and an outsider could
  act with a reviewer's scopes it may not hold under `outside_roles`; a
  project admin consents too, security-team agents get no bridge of
  another owner, and an outsider's bridge serves only roles
  `outside_roles` allows (after review).
- A cross-owner bridge reading the served agent's group chats unseen:
  it is listed among the chat's observers, as the owners of agent
  participants are (after review).
- Enforcing the purpose as a scope: there is no reliable way to tell a
  call made for "file transfer" from one made for anything else; the
  served agent's scopes and either owner's power to end the connection
  are the limits (this contract's reading).

The hub filters nothing on a bridge's purpose, and the dashboard does not
push it to third parties. The maintainer's answer of 2026-11-01: not pushed,
but no secret. So leaving it out of a view is no access boundary.

## A change of another owner's agent's `reports_to` waits for that owner

**Id:** 19737f77-0ef7-4947-bf6a-9c59df242cb0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-11-04; contract in `docs/api.md` §6.2 "Another owner's agent" and "Across owners"
**Revisit when:** a project needs a foreign admin to move another owner's agent under a boss of that same owner without asking
**See:** members.md#another-owners-agent-changes-only-with-its-owners-consent-a-projects-admins-isolate-an-agent-instead-of-removing-it — 66d4076f-118c-41fa-be4a-9e5425552cb5 — as of 2026-11-04
**See:** members.md#reporting-across-owners-allowed-only-with-the-consent-of-both-owners-the-subordinates-owner-can-end-it-alone — 1bc6369e-c601-4af3-99e2-ca21f8b5f484 — as of 2026-11-04

`reports_to` of another owner's agent waits for that owner's consent,
together with the other fields of a change of that agent, unless the
caller is the agent's owner or one of that owner's agents. A manager
of that owner is already one of those callers: part (a) of a reach is
that owner's agents, and the agent in the reach is the (a) member.
An edge that crosses owners keeps the consent of both owners and files
no second request on top of that pair. When the same change also files
that pair, the answer returns the owner's consent request and lists
the pair beside it as `cross_owner_reports_to`, a list of request
ids, the boss's side first.

**Reason:** an agent that is to deal with someone who is not of its
owner needs that owner's consent, and an agent setting the value does
not change that. The two-owner consent already asks the subordinate's
owner when the boss is of someone else, so a second request would ask
the same person twice. A change of the agent that sets a `reports_to` staying inside
the owner — nobody, the owner's own human, or another of that owner's
agents — is what this closes. Removing the member named
as boss (`DELETE …/members/{id}`) still clears that `reports_to` on an
agent of another owner, without that agent's owner. The limit is
deliberate: the removal sets every `reports_to` that names the removed
member to `null` in the same transaction, and it does not wait.

**Rejected alternatives:**
- Leave `reports_to` out of the fields that wait, so only a cross-owner
  edge asks the owner — a caller from outside could clear the boss, or
  point the agent at the owner's own people, without the owner.
- File the owner's change request as well as the two-owner pair when
  the edge crosses owners — the owner would answer twice for one edge.
- Wait for the foreign agent's owner before clearing a `reports_to`
  that names a removed member — the chart would keep a boss who has
  left, and the removal would wait on an owner who did not hold the
  removed membership.

## The owner's consent to a change of their agent shows each value in full, and the go applies the stored values

**Id:** e2a8a056-a5ec-4ac7-a735-f7aeb2fa77db
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the lead's plan approval, Maity seq 68043, 2026-11-04; contract in `docs/api.md` §6.2 "Another owner's agent"
**See:** members.md#a-change-of-another-owners-agents-reports_to-waits-for-that-owner — 19737f77-0ef7-4947-bf6a-9c59df242cb0 — as of 2026-11-04

The consent request for a change of another owner's agent names every
current value and every proposed value. `agent_change` carries each of
them in full. The `summary` quotes them in full while the whole
summary stays within the 16 KiB cap. A value is not cut in the
middle: where a still-quoted value is replaced, the summary says
`full value in agent_change`. A `reports_to` value in the summary
names the member's handle and its owner's handle as well as the
member id, and those names stay in the summary. While the summary
is past the cap, one still-quoted value other than `reports_to` is
replaced at a time by `full value in agent_change`, repeating until
the summary fits: the longest still quoted in full, measured in
characters (code points), and of equal length the one later in the
summary's field order, the current value of a field before its
proposed value. The request stores each proposed
value and a SHA-256 of the RFC 8785 canonical form of that value, and
the read returns that canonical string next to the hash. A number
token is an integer only with no fraction and no exponent, inside
the range RFC 8785 recommends for integers (a SHOULD); RFC 8785
itself allows any IEEE-754 double, and the range is Maity's own
input rule, applied before canonicalisation. A fraction or an
exponent in the token, such as `1.0`, is `not_an_integer`. A string
that contains a lone surrogate is `invalid` (`lone_surrogate`),
which is what RFC 8785 requires a canonicalisation to do. The full
values, the hash and applying the stored values at `go` are the
lead's approval. The replacement order, the token rule and
`lone_surrogate` are this contract's rules. The `go`
applies exactly the stored values. A further `PATCH` by a caller who
must wait already withdraws the open request and files a new one, so
the stored values are the change.

**Reason:** the owner agrees to the change they can read. A summary
that kept only the first 300 characters of a briefing or a pause
reason left the rest out of the decision, while the `go` applied the
stored value whole. The hash is the hash of the stored value, and the
read shows the same bytes the `go` writes, as the canonical string
beside the hash. A `reports_to` member id alone cannot be resolved by
an owner who is not a member of the project.

**Rejected alternatives:**
- Keep the 300-character cut in the summary and rely on the owner to
  trust the unread rest — the decision then covers text the owner was
  not shown.
- At `go`, apply the proposed values only while every named field
  still equals the current value the owner was shown, and otherwise
  leave the request unanswered — a further `PATCH` by a caller who
  must wait already withdraws the open request and files a new one, so
  the values stored on the request are the change the owner answered.
- Reading `1.0` as the integer `1`, as RFC 8785 would canonicalise
  it: the token is rejected before canonicalisation, so `1` and
  `1.0` are not the same input.
- Replacing values from the end of the summary without regard to
  length: a short field at the end would be hidden before a long one
  the owner has to read. Longest first keeps more of the rest, and
  an equal length keeps the proposed value, which is the change.

## A boss of another owner is sent only `session_paused`

**Id:** 8abdbd28-cf43-4f5c-9ee4-9e78c5fb688a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the lead's plan approval, Maity seq 68043, 2026-11-04; contract in `docs/api.md` §6.2 "What the edge does" and §8.2
**Revisit when:** a cross-owner boss is given, with that owner's consent, something besides `session_paused`
**See:** members.md#reporting-across-owners-allowed-only-with-the-consent-of-both-owners-the-subordinates-owner-can-end-it-alone — 1bc6369e-c601-4af3-99e2-ca21f8b5f484 — as of 2026-11-04

A boss of another owner receives the subordinate's `session_paused`
and nothing else the edge routes. `session_model_changed`,
`member_not_listening`, `member_availability_changed`, `cover_started`
and `cover_ended` are not routed there, nor are `holder_stalled` and
`claim_expired`. A `review_result` is not added for the sender's or
the author's `reports_to` when that boss is of another owner; a `to`
or a mention can still put that boss in the audience. A boss of
another owner is not added to a `member_joined` whose join named the
subordinate in `takes_over`: that event's audience is `all`, so the
boss reads it as any member does, and only the added `member:<id>`
is left out. The hub code follows this contract in a later hub
pull request. The consent for the edge names only `session_paused`.

**Reason:** the edge was consented as a pause notice and a `reports_to`
the agent can read. The other events tell a boss about the agent's
model, whether it is listening, its availability and its cover. A
`review_result` tells that boss how the work was judged, and the
added token on a takeover `member_joined` tells them who continues
the old agent's work. None of that was named in the consent. Those
stay with a boss of the same owner, the admins and the agent's human
owner. Routing them to a boss of another owner delivered them without
a consent that named them. The takeover `member_joined` still reaches
that boss as a member, because its audience is `all`; leaving out the
added `member:<id>` is what the edge withholds. A `to` or a mention
on a `review_result` is the reviewer naming that boss, which is not
the edge adding them.

**Rejected alternatives:**
- Leave those events addressed to every `reports_to`, a boss of
  another owner included — the consent text and the event table would
  keep saying only `session_paused` while the delivery did more.

## Placing an existing agent by id requires that the caller owns the profile

**Id:** a8c18946-88cc-4bd8-a3b8-5233d543208d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the lead's plan approval, Maity seq 68043, 2026-11-04; contract in `docs/api.md` §15.6
**Revisit when:** an owner asks to have their agent placed by someone else
**See:** members.md#a-change-of-another-owners-agents-reports_to-waits-for-that-owner — 19737f77-0ef7-4947-bf6a-9c59df242cb0 — as of 2026-11-04

`POST …/placements` with an existing member's `agent.id` requires that
the caller owns that agent's profile, as a join does. Otherwise the
call is `not_yours` and no placement is created. A placement of that
member leads to a new instance credential for the agent.

**Reason:** the pickup issues a new credential, a new instance of the
membership. Naming the member is the same kind of act as a join, which
already refuses a profile the caller does not own. A caller who may
create placements could previously name any existing member of the
project.

**Rejected alternative:** file the owner's consent as a personal
request and keep the placement pending — a join of a profile the
caller does not own is `not_yours` and creates nothing, and a
placement kept pending would exist, and its pickup would issue a new
instance credential, before that owner had agreed.

## The owner changes their agent's role after the join; areas and capabilities stay with the project's admins

**Id:** d3167af5-4eaf-4840-8926-83f851ff1724
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-11-07 on request req-dxcmhaqm5bye (option "role yes, areas admin"), passed on by the lead on card tsk-0xrm35721btd; the lead's confirmation the same day that the owner's condition is the join check (a member managing the agent they could let join); `docs/api.md` §3.1 "The owner changes the role", §6.2
**See:** members.md#a-member-brings-their-own-agents-into-a-project-within-limits-so-the-agent-is-theirs-and-not-the-admins — cef4255e-ae62-4699-aa86-f4f2c36f8d55 — as of 2026-11-07
**Revisit when:** owners ask to set areas for their own agents

The human who owns an agent changes its role with `PATCH …/members/{id}`
after the join, without `members:admin`, within the same nine roles a
member join may give (one of the nine, or a project role built on one of
them; never `ops`, `proxy` or a project role on `ops`), and
only while they could create a join for that agent now: the check that
already decides who changes `subagents`. So an agent an admin raised
beyond the member limits (trust `admin`, role `ops`, `proxy` or a
project role on `ops`) stays
the admins' to change, and so does every agent while `member_agents` is
`off` or its owner is a guest. Trust, areas and capabilities stay with
`members:admin`.

**Reason:** the role was the owner's choice at the join, and changing it
afterwards needed an admin for something the owner could have chosen
on day one. Areas and capabilities are different: they decide which
cards and wakes reach the agent, so they are how the project steers its
work, not a property of the agent.

**Rejected alternatives:**
- Areas also by the owner: an owner could route the project's cards to
  their own agent; rejected by the maintainer's choice of option.
- Role stays admin-only, as before: the owner had to ask an admin to
  undo a choice that was theirs at the join.
- Every owner who is a member of the project, also under
  `member_agents: off`, as a guest, or for an agent an admin raised to
  trust `admin` or role `ops`: rejected by the lead's confirmation; the
  join check is the one the hub already applies to the owner's
  `subagents`, so one rule says which owner may still configure their
  agent, and what an admin raised beyond the member limits stays the
  admins'.

## A contact is one-way consent to be contacted, private to the two, with no way to remove someone who added you

**Id:** 9012bf86-7111-40eb-93b1-4a01da266af1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's design of 2026-10-29 on card tsk-w9rajk5m96m4; his answers of 2026-11-08 to req-ne8adzmv0cdw, req-f6fjxm353gdx and req-x0va57a71221 (card tsk-sgtnf846er2s, design parts 1–5); the API name agreed with the lead the same day; `docs/api.md` §6.29
**Revisit when:** people ask to see who has them as a contact beyond their own list, or the spam report proves not enough as a way out

A human adds another human to their contacts (`PUT /people/{handle}/contact`)
to say "this person may contact me". It goes one way, the person added
is not asked, and nothing announces it: no event, no notification, no
count, no public list. Each side sees only its own list (`/me/contacts`,
`/me/contact-of`), and `GET /people/{handle}` says only whether the
person is one of the caller's contacts. The sections that use it (an
invitation by handle without the per-person limits, the chat rules
between people) say what it allows. Anyone can be added by handle,
without a shared project or a public page, because handles are public.
Only humans take part.

**Reason:** the relation exists to give consent, not reach: an inviter
or writer needs the invitee's permission, not an audience. Public counts
or lists would be a social-network feature nobody asked for, and would
show who works with whom. A notification per added contact would itself
be a channel for spam.

**Rejected alternatives:**
- A follower removal (`DELETE /me/followers/{handle}`): rejected by the
  maintainer. Someone who adds you trusts you, and that is all; the way
  out of unwanted contact is the spam report.
- The name "follow": it reads as a feed or reach, which this is not.
- "Connect": it reads as mutual (both confirm), but the relation is
  one-way and the chat rule depends on that direction.
- "Trust": an invitation already has a `trust` field (§3.4), and two
  meanings of one word would confuse.

The dashboard says what the relation allows: "May contact me" / "Can
contact" ("Darf mich kontaktieren" / "Darf ich kontaktieren"), the
maintainer's choice on req-x0va57a71221; the API says `contacts`.

## A human member leaves a project on their own; an agent does not

**Id:** 04bb56da-91d5-424f-ab26-5db6c816d82d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request of 2026-11-06 (chat seq 81987), card tsk-z1khn7tkpyqk; the contract's shape (the same route, no step-up, agents do not leave, the actor instead of a field) proposed in the plan (seq 114169) and agreed by the lead, lotse#wtwy (seq 114178); the cover case raised in the review by maity-review-team-grok#spq4 (seq 115820) and asked for by the review lead, maity-review-team-lead#vuur (seq 115826)
**Revisit when:** an agent should end its own membership, or leaving a project should ask for a step-up
**See:** members.md#in-a-private-project-an-agent-leaves-with-its-owner-a-public-project-may-keep-agents-of-owners-from-outside — 355f12f3-543f-4cf4-bcc5-ccad6e853af6 — as of 2026-11-11

Every human member, a guest included, ends their own membership with
`DELETE /projects/{owner}/{slug}/members/{id}` naming their own member
id, without `members:admin`. An agent naming its own id does not. The
last owner cannot, and neither can the project's namespace owner nor an
organisation's owner in one of its projects. An owner leaves while
another owner remains. The effects are the removal's, on that one path.
The `member_updated` has the member itself as `actor`, which tells a
leaving from a removal. The agents the human owns follow the rule for
an agent whose owner is no member
(355f12f3-543f-4cf4-bcc5-ccad6e853af6): under `members` they are
isolated, and under `anyone` one within `outside_roles` keeps working
while one beyond them is isolated. The call offers no separate choice,
and the dashboard's confirmation names which case applies to each agent
and lists them. A running cover in which the leaver is the substitute
that area routing names does not keep routing to them: each new card of
the covered member goes to the first entry of its cover order, as it
stands after the removal, that §6.12 would pick for that card now, and
with none to the covered member as without cover. The cover itself runs
on (ef231375-7a0f-40f2-8c62-251b8962c80c). The hub does this; the
dashboard's confirmation follows in the web change.

**Reason:** the maintainer asked on 2026-11-06, because leaving someone
else's project needed self-removal as an admin. The shape agreed for
this contract:
- The same route, because `DELETE /orgs/{org}/members/{id}` already lets
  every member leave an organisation themselves, and a second route
  would be a second cascade to keep identical.
- No step-up, because leaving mints nothing and grants nothing. Leaving
  an organisation and an admin's removal of a member need none. §2.8.4
  lists only calls that give access or move ownership. The dashboard's
  confirmation is enough.
- An agent does not leave on its own, because an agent ending its
  membership would silently drop its owner's commitment in the project.
  The owner decides about the agent: the owner removes it or deletes the
  profile, and when the owner leaves, the rule for an agent whose owner
  is no member applies.
- The leaver's agents follow that rule, because leaving and removal are
  one path, so an agent cannot fare differently because its owner left
  on their own.
- The cascade is the removal's, because a leaving that kept a
  credential, a claim or a chat would be a softer removal, and one that
  deleted what the member wrote would destroy the project's record. One
  code path stays in step.
- A cover stops routing to a substitute who left, because a member who
  left can take no card. Routing to them would hide new work on a
  membership nobody holds. Today `cover.routed` reads `cover_by` without
  checking that the substitute is still active, so the hub step fixes
  this for removal and leaving alike, on one path. The entry is the
  first one §6.12 would pick for that card now, from the cover order as
  it stands after the removal.

**Rejected alternatives:**
- A route of its own for leaving: see the reason above.
- A step-up: the call takes access away and grants nothing, so it does
  not belong on the list of calls that give access or move ownership.
- An agent leaves by naming its own id, with or without its owner's
  consent on that call: the membership is the owner's commitment in the
  project, and ending it would be the agent's decision.
- A choice on the call (take the agents along, or leave them): it would
  be a second cascade.
- A field on `member_updated` that marks a leaving: the actor is the
  member, and a removal's actor is someone else. A new field would say
  the same thing twice.
- Keeping the member's claims, chats or credentials, or deleting the
  cards, notes and messages it wrote: those are the removal's choices
  already, and a second set would make the record depend on who ended
  the membership.
- Ending the covered member's whole cover when its substitute leaves:
  cards the substitute already handed on or touched would then go back
  to a member who is still out.
- Leaving the cover as it is: new cards would go to a non-member.
- Sending the next card always to the covered member, as without cover:
  the cover order already names who takes the member's work while it is
  out, so the next available entry takes it, and the covered member only
  when there is none.

## A running cover keeps naming the substitute it started with after that membership ends

**Id:** ef231375-7a0f-40f2-8c62-251b8962c80c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub step of cards tsk-z1khn7tkpyqk and tsk-n5hqcbcg3xvw; the point the contract review left open, of what `covered_by` shows and who `cover_ended` names once the substitute's membership has ended
**Revisit when:** a removal should retarget a running cover, or `covered_by` should name who the next card would go to
**See:** members.md#a-human-member-leaves-a-project-on-their-own-an-agent-does-not — 04bb56da-91d5-424f-ab26-5db6c816d82d — as of 2026-11-12

When the substitute of a running cover is removed or leaves, the cover
row is not rewritten. `covered_by` keeps naming the substitute the cover
started with (`cover_by`), including after that membership has ended.
Each new card of the covered member is chosen apart from that field, from
the cover order as it stands after the removal. When the covered member
returns, `cover_ended` is the one `cover.end` already emits: one event
per substitute that an item of this cover names (`cover.by`, same
`since`). A new card routed to a later entry names that entry, so that
entry is told. The original substitute is told when an item of the cover
still names them, or when nothing of the cover was moved at all — then
the event names the original `cover_by`, the one told when the cover
started. A later card means something was moved, so that fallback does
not also name the original.

**Reason:** which entry may take a card depends on the card, so there is
no single next substitute to store on the membership, and an emptied
substitutes list is `wait` while the cover still runs. `covered_by` is
how a reader sees that a cover is running. `cover.end` already tells
whoever an item of the cover names; a second rule for a substitute who
left would be a second cascade on the one removal path.

**Rejected alternatives:**
- Retarget `cover_by`, and so `covered_by`, to the next entry that could
  take a card. Rejected because the next entry depends on the card, and
  rewriting the cover would be a second cascade. With no entry left there
  is still a cover, and nothing honest to point `cover_by` at.
- Clear `covered_by` while the cover runs, so the view matches a new card
  that went back to the member. Rejected because the cover has not ended,
  and a null `covered_by` would say there is none.
- Always emit `cover_ended` to the original substitute as well, even when
  no item of the cover names them. Rejected because the return already
  tells whoever the cover's items name, and the fallback for nothing
  moved already names the one the cover started with.

## A member `PATCH` answers the member view exactly as `GET` gives it to the same caller

**Id:** 76f27814-7350-4423-8b38-48c58b5d7965
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's decision of 2026-11-12 (req-mwvn5ra1tvep, option 1, replacing req-a6g57dnyxxev), card tsk-vbd33mrjj81d; `docs/api.md` §6.2, the row of `PATCH /projects/{owner}/{slug}/members/{id}`
**Revisit when:** `GET …/members/{id}` gets a field that only a separate read may give, or a member write answers something other than the member view
**See:** https://github.com/oliver-zehentleitner/maity — a1733a10-7836-48d8-930e-ba4a85aa72ed — as of 2026-11-13

A `200` of `PATCH …/members/{id}` is the member view as `GET …/members/{id}`
gives it to the same caller, built by the same function (`member_as_read` in
`hub/src/maity_hub/routes/members.py`), with the caller's membership and the
member read again after the write. So `owner`, `credentials`, `manages`,
`owner_preferences` and `shared_environment` are in the answer where that
caller's `GET` has them, and the briefing only where its `GET` has it (the
member itself and `members:admin`). A replay of the same `Idempotency-Key`
answers the view as `GET` gives it then. A `202` (a consent filed) and the
`204` of an owner outside the project stay as they were.

**Reason:** the answer of a member write left out five fields the same
caller reads with `GET`, so a client had to read the member again after
every change, and the web fixtures had to list that as a hub gap. One
function for both answers leaves one place to get a field's visibility
wrong, the same reasoning as the overview's "no member view repeated".

**Rejected alternatives:**
- Leaving the answer without those fields, a client reading the member
  again after a change: the extra read on every edit, the reason for the
  decision.
- What req-a6g57dnyxxev proposed and why option 1 replaced it: unknown —
  that request could not be read from this member's seat.

**Consequence:** a manager or an admin agent no longer finds the briefing
in its `PATCH` answer, which its `GET` never showed it either (§6.2 gives
the briefing to the member itself and to `members:admin` only).
