# Memory

## A preference proposal is reviewed as an inline line diff; one on an older version is merged by hand, never accepted as is

**Id:** 8546c70b-d006-4913-9ae3-6aeac5a250d3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's wish for a review with current text, proposed text, diff, edit before accepting, accept or reject (tsk-qwamrxnd8vc3); docs/api.md §19.4 (no silent overwrite, the hub does not rebase); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the designer answers on the review layout, or the hub lists proposals with their texts

The review in the personal inbox shows the reason, then a line diff from
the human's current text to the proposed one, one line per row with − and
+ (said in words for screen readers), and both texts in full folded below.
Its own answers replace the plain Go and No: **Accept**, **Edit, then
accept** (the edit goes with the current version) and **Decline** with an
optional reason. A proposal written against an older version offers no
plain Accept, only **Merge by hand** or Decline. Because a list shows no
proposal, the inbox reads every open personal request on its own.

**Reason:** an inline diff reads the same at 390 px as at 1280, where two
columns of free text would wrap into each other. Withholding Accept on a
stale base keeps to the contract's rule that applying it would drop the
newer text unread: the hub would answer 409, so the page does not offer
what it knows fails. Personal requests are few, so reading each one costs
little and gives the review the human's current text at once.

**Rejected alternative:** a side-by-side view of both texts, the other
layout the card names; kept as the designer's choice to make, not decided
here. Offering Accept on a stale proposal and showing the 409 afterwards:
a refusal the page could have foreseen. A review that fetched its texts
only when opened: the inbox could not tell a preference proposal from any
other personal request before that.

## Project memory is chosen on /new with its setup options

**Id:** a8e479be-cb07-49cc-b7bd-b48500903ee1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on project memory and setup cards (docs/api.md §6.1, §6.21, contract #339), 2026-10-25; the card tsk-c8jt63tnztqj (provider read only after creation, the badge policy editable with its snippet in Project settings); hub/src/maity_hub/models.py (`extra="forbid"`: a hub refuses a body field it does not know); the dashboard's implementation, 2026-10-25; the before-launch cleanup (tsk-wgg2t8ngx9xg, tsk-qeh64f8gpvnd), 2026-10-29
**Revisit when:** a second provider arrives, the hub sets something up on a provider change, or the overview gets its badge section (§6.20 names the overview for the snippet)

The create form has **Project memory** (Keep the Why preselected, None)
and the five setup options beneath it in the cards' order (three until
#715 added the CI linter and the published dashboard, 2026-10-30), all
ticked, each sent as `true` or `false`. The dashboard's option has a
**Path** field under it, prefilled with `keep-the-why-dashboard` and
checked as the hub checks it (§6.21: one to five segments, and `..`
nowhere in the value, `a..b` included, as the coordinator settled it on
2026-10-30), its refusal said at the field;
`dashboard_path` is sent only while that option is ticked, and left out
of the request otherwise, never sent as `null`. Project settings show the setup's cards
read only and offer the README badge (`policy.badge`) with its snippet;
the provider itself is changed there since 2026-10-31
(de95eb84-842b-4476-95c6-dcbaf3a98064), until then it was shown read
only with a pointer to a card for an agent. Until 2026-10-30 the form asked
the hub's `/openapi.json` whether `POST /projects` names `memory` and
`setup`, and without them offered neither; since then it always offers
and sends them (e1699490, the alpha rule).

**Reason:** the path is left out with the dashboard unticked because the hub would only
drop it, `null` is `invalid` (§6.21), and a malformed value in a hidden
field would refuse a creation for something the human did not choose. The
form's check is the hub's, not a stricter or looser one of its own: a
refusal only one side makes stops or lets through a creation for no
reason; the hub alone checking would show the error only after sending.
Barring only a segment `..` was rejected: the segment rule already bars
it, and it would let `a..b` through, which the hub refuses.
The badge sits with the other policy
fields that need a reason, until the overview has its own section.

**Rejected alternative:** a provider dropdown in Project settings: it
would invite a change whose consequences the hub does not carry out.
Until 2026-10-30 sending `memory` and `setup` always was rejected
because a creation on an older hub would fail; under the alpha rule no
such hub runs, so they are always sent now.

Until 2026-10-29 the form also sent the `keep_the_why` boolean to a hub
that knew the provider only under that alias (before §6.21). It no
longer does: such a hub is offered no project memory. **Reason:** the
maintainer's rule for the alpha is to delete compatibility layers before
launch, and no hub before §6.21 is running. **Rejected alternative:**
keeping the alias: a third branch in the form for a hub nobody runs.
The hub dropped it from `POST`, `PATCH` and the project view (#606), and
the fixture hub with it: it refuses the field as the hub does.

## The memory provider is changed in Project settings, with a reason

**Id:** de95eb84-842b-4476-95c6-dcbaf3a98064
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-41hpr02cvej8 (the maintainer, 2026-10-31: a project under `none` cannot make Keep the Why required, and the dashboard offered no way to change the provider); docs/api.md §6.1 (a change by `PATCH`, `project:admin`, bumps `rules_version`, makes and cancels no setup card), §6.23
**Revisit when:** a second provider arrives, or the hub sets something up or cancels setup cards on a provider change

In Project settings, a human with `project:admin` changes **Project
memory** (Keep the Why, None) with a reason; the form sends
`{memory: {provider}, reason}` and says that the change reaches the agents
at their next resume, makes no setup card and cancels none, and that
setting Keep the Why up in the repository, or removing it, stays work for
an agent on a card. Others see the provider and its explanation read
only. After a switch to Keep the Why the commitment below offers
`required` and reads it unless someone set it; under None it is
`optional` and locked. The reason is asked although the hub takes the
change without one: it lands in the `rules_changed` event, as a policy
change's reason does.

**Reason:** without the change a project created under None could never
have Keep the Why required (§6.23 refuses `required` there), and the
maintainer could not set it for this project. The panel says plainly
what the change does not do, which was the reason it was read only.

**Rejected alternative:** keeping the provider read only with a pointer
to a card (a8e479be's earlier rule): an agent cannot change the
provider either, only a human with `project:admin` can, so the pointer
led nowhere. Making the setup cards on a switch: the hub does not
(§6.21), and the dashboard does not invent cards the contract leaves out.

## The Keep the Why personal settings are left out under no memory provider, and show no values

**Id:** 2e30b22e-1cf1-4559-a77a-16f8237bb53b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-j8gwrdy9d5c2; docs/api.md §6.23 "The dashboard's part"; a review of the pull request

Project settings offer `policy.keep_the_why_defaults` only while the
memory provider is Keep the Why, and name the repository's
`.keep-the-why` as the origin without showing its values.

**Reason:** without the provider no agent is told about personal
settings at all, so the choice would have no effect. The commitment form
above it stays visible and disabled there because it explains why Keep the
Why cannot be required, which this one has nothing to add to. The values
are not shown because the hub does not read that file.

**Rejected alternative:** a read-only view of the defaults with a link to
edit them, which the card asked for: §6.23 asks only for the origin, and
so it was dropped.

## Memory is a view of its own, and holds the role memory

**Id:** 476c7232-ef6b-431b-8d28-7726d5860a64
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.11, §19; the maintainer's chat seq 6883; tsk-6tqytgmcp17p; supersedes the section on Settings → Mine of #1026

`/<owner>/<slug>/memory` is one tab for team, role and community memory, and the role memory moved there from Settings → Mine within the day it landed, so that there is one place. A slug `memory` is now reserved as every view's name is. Souls stand on the same page, for their owner only, read when opened; delete offers a reason in the row, not a browser dialog, because the reason is shown afterwards.

The tab row's room on a phone, the argument of f9ef2098, was outweighed by one place for one store; a tab was accepted at that price.

**Rejected alternatives:** keeping the role section on Mine beside the view: two places for one store. Three separate views: the reader asks what was written, not in which store.

## Role memory is a part of Mine, not a view

**Id:** f9ef2098-cadd-452c-ac4e-5945baa145d4
**Type:** decision
**Status:** superseded
**Superseded by:** 476c7232-ef6b-431b-8d28-7726d5860a64
**Evidence:** inferred
**Source:** docs/api.md §16.11, §19.2; tsk-hx8cbm2eqg45

The role memory is a section on Settings → Mine, the one page every human member reaches in a project, with a role picker for trust owner and admin. No new address: §16.11 names Settings as one view with two tabs, and a view of its own would be a contract change for a list of a few entries.

**Rejected alternative:** a third Settings tab or a project tab: both need §16.11 changed, and a tab row is already short of room on a phone.
