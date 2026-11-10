# Jour fixe

## The jour fixe is a tab of its own: its rounds and what each reader may do under one; its series are the next entry

**Id:** 8310dfc9-6e1c-48ed-a069-4579214194da
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-6h70epze0906 with the maintainer's request to have the jour fixe before the launch, 2026-10-31; docs/api.md §20 (the hub implements it), §16.11 (`/<owner>/<slug>/jour-fixe/<round id>`)
**Revisit when:** an agent moderator's work (the statement, the report) is to be done in the dashboard
**See:** jour-fixe.md#the-jour-fixe-is-kept-per-series-in-project-settings-and-the-tab-groups-its-rounds-by-series — d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998 — as of 2026-10-31

**Jour fixe** is a tab of the project. At `jour-fixe` it lists the
rounds, grouped by series (below). At `jour-fixe/<id>` it shows one
round as a member reads it (§20.7): the series' topic, phase and
deadline, moderator, the number of answers but never an answer,
participants and the absent with their reason, the steps, the
statement, the posts and the report with each proposal's triage. The
series themselves, their moderators and the start by hand are the next
entry's: the contract made them several per project (§20.1), and that
part of this entry, a single schedule in Project settings and a
moderator order, ended with it.

Under the round, each reader gets what they may do (`js/jour-fixe-act.js`):
- **A participant** answers while the window is open: three texts, by name
  or anonymously. Choosing anonymous shows what anonymity does not cover
  before anything is sent (§20.4). Afterwards they read their answer back
  and may withdraw it.
- **The moderator and the humans of the admin team** read the answers
  (an anonymous one names nobody) and remove one with a reason.
- **A human moderator** writes the statement (topics, who said what,
  proposals), adds a further step, and writes the report. In the report,
  each statement proposal goes to the owner, is decided with a reason, or
  is left out. A decision carries the rules version and the decider's
  preferences version as its basis (§19.4).
- **An eligible member** posts once per topic in the open step.
- **A human who was invited, or one of the admin team,** removes the
  report's summary, a finding or a proposal.

An agent moderator does its part through the API, not here. The report
form offers no `humans_only` flag and no proposals of the moderator's
own; both are open for a later change, not left out by decision. A
decision is offered only where the project names its `rules_version`,
so the basis never carries an invented one.

**Reason:** a round is read by every member, so it belongs in the
project's tabs. The contract keeps answers with their readers, so the
round's page never shows one, only the count.

**Rejected alternatives:**
- The rounds inside Project settings: members without `project:admin`
  read rounds too.
- The anonymity limits in a link or a tooltip: §20.4 asks for them to be
  shown before an anonymous answer is sent, so they open with the choice.
- Editing the former single schedule field by field (it was replaced
  whole, so a partial form would have reset what it left out): gone with
  the single schedule, since a series is its own resource.

## The jour fixe is kept per series in Project settings, and the tab groups its rounds by series

**Id:** d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §20.1, §20.2, §20.7, §20.9 (contracts #934 and #936); the card tsk-39sjeqre25gw
**See:** jour-fixe.md#the-jour-fixe-is-a-tab-of-its-own-its-rounds-and-what-each-reader-may-do-under-one-its-series-are-the-next-entry — 8310dfc9-6e1c-48ed-a069-4579214194da — as of 2026-10-31
**Revisit when:** the hub names the link targets of the two jour fixe inbox items (§18.1), the shape of `pending_moderators`, `own_agents` and the 202 body is fixed, or a series' keeper who is no project admin is to keep it from the dashboard

Where that section sits is the next entry's since 2026-11-06 (folded at the top of the jour fixe tab); what follows about its content holds there.

**Project settings** has a section "Jour fixe series" for a human with `project:admin` (`js/jour-fixe-series.js`): the list of series with topic, circle, on or paused and the schedule as a sentence; one form for a new series and for editing one (topic, circle `owner`, `humans` or `all`, the circle owner among the human members, `enabled`, recurrence, time, timezone, the three windows, a reason). Circle and circle owner are fixed once created, so the form shows them disabled when editing. A hub refusal is shown at its field, the 10-series limit under the topic. Per series it lists the moderators and the grants waiting in `pending_moderators`, each with End, and a member selector with Grant; the grant's answer is not read from the status (201 takes effect, 202 waits) but the series is read again, which shows which of the two happened, and a pending entry says it waits for the agent owner's and a keeper's consent. An owner series of someone else shows an admin only the line "a private series of @owner" with its schedule and Delete, never its topic, moderators or rounds (§20.1).

The **jour fixe tab** shows one block per series the reader may see: the topic as heading, circle and schedule, the next slot or that none is scheduled, the open round and its rounds, a "Start a round now" for the series' keepers and moderators that shows the hub's 409 reason in words (`jour_fixe_open`, `project_closed`, `no_moderator`, `too_few`), and each member's own switches (§20.2, §18.1): opt out of the series and take part again, get the report or stop getting it, for oneself and for each of one's own agents (sent with `?member=`). Nothing is drawn for a series the reader may not see.

**Reason:** moderating, the schedule and the circle belong to one series, and a project may have ten, so a settings form for one schedule cannot hold them; a list with one form is the smallest thing that creates, edits and deletes several. The tab is where keepers and moderators start rounds and where every member, not only an admin, opts out, so those parts sit in the series block and not in the settings. Re-reading the series after a grant is used because the status is not available to the page (`M.api` returns the body) and the contract leaves the 202 body unspecified.

**Rejected alternatives:**
- One form with a series selector: creating and deleting several items needs a list anyway.
- Per-series moderators and the manual start in the settings only: the start is for moderators who are no admins, and the opt-out is every member's.
- Reading the series from `GET …/series`: its shape is not given in the contract, so the tab reads them from `GET …/jour-fixe`; the fixture hub serves both.
- A link for each of the two inbox items: §18.1 names no target type for them, so they fall back to the project inbox until the hub names one (`linkOf` in `notify.js` then needs a branch).

**Not covered, known:** a project owner who is the `circle_owner` of a series but no project admin cannot open Project settings, so the series section is not reachable for them from the dashboard. The contract has no call for a keeper to add other members to the report list, so the list is changed per member for itself or its own agent only. Likewise, §20.2 lets an agent's owner who is no keeper, and a human with `members:admin`, grant the moderator right, but the grant form is in Project settings (`project:admin`), so an agent's owner who is no admin cannot start a grant for their agent from the dashboard, and the fixture hub refuses it from anyone who is neither a keeper nor the agent's owner.

The fixture hub's start of a round by hand refuses in the hub's order (routes/jour_fixe.py `start`, then `rounds.prepare`): `circle_owner_gone`, `rate_limited`, `project_closed`, `jour_fixe_open`, `no_moderator`, `too_few`, so that a test sees the same first error as against the hub where two overlap. A moderator who opted out does not moderate, as `rounds.prepare` drops those members before it looks for one. `too_few` counts the circle without those who opted out, plus the moderator, also outside the circle; presence is not modelled, every member counts as present. Rejected: checking in the order the view needs them, which would let a test pass against the fixture and fail against the hub where two refusals overlap.

## The jour fixe series are kept folded at the top of the jour fixe tab; Project settings only link there

**Id:** b2047dbd-b2e4-4d5b-a7b9-e8c38819d3fc
**Type:** decision
**Status:** active
**Evidence:** unknown
**Source:** the maintainer's request on the card tsk-3526xb7mqg9r, 2026-11-06
**See:** jour-fixe.md#the-jour-fixe-is-kept-per-series-in-project-settings-and-the-tab-groups-its-rounds-by-series — d6739fd7-d3d5-49ea-b6e3-2ee8f0d58998 — as of 2026-11-06
**Revisit when:** a series' keeper who is no project admin is to keep it from the dashboard

The section "Jour fixe series" (`js/jour-fixe-series.js`) moved from
Project settings to the top of the jour fixe tab, above the series'
blocks, as a `<details>` that is folded by default. It is shown to the
same readers as before, a human with `project:admin`; others get the tab
as before, without it. The series are read only when the section is
first opened. A change made in it draws the series' blocks below again,
not the whole tab, so the section stays open. Project settings keep a
short section with the same title that links to the jour fixe tab.

The schedule's switch reads "Activated", with a hint below it on what it
does (rounds open on the schedule; switched off, the schedule stays
stored and a round can still be started by hand).

**Reason:** the move and the folded default are the maintainer's request.
The card gives no reason for the placement beyond the request, so that
part is `unknown`. For the label it does: the German "Runden nach diesem
Zeitplan eröffnen" did not say clearly that it switches the series on.
The remaining choices are this change's own (inferred): a link in
Project settings, so a keeper who looks there for the series still finds
them; reading the series on first opening, since most visits to the tab
are to read rounds; and drawing only the blocks again, since drawing the
whole tab would fold the section back while a keeper works in it.

**Rejected alternatives:**
- Keeping the section in Project settings: the maintainer asked for the move.
- Removing it from Project settings without a link: the card allowed it;
  the link was kept for keepers who look for the series there.
- The section open by default: the card asks for it folded.
