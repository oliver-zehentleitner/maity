# Overview

## The overview is the second tab, redrawn in place, and its counts failing leaves the rest standing

**Id:** e585b67d-8a1a-4e68-8ea7-814ec4fbc251
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the overview contract (docs/api.md §6.11, PR #189) and its contract owner's rulings, 2026-10-22; the coordinator's card for the view (tsk-hha96xyqcpdd), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the overview gains merges from the change ticker (#180) or releases, or the inbox stops being the landing page

`/<owner>/<slug>/overview` gets the tab right after **Inbox**, while the inbox
stays the landing page. The view is five parts: links, members, board
counts, open requests and the latest reports. Links and members come
from what the header already holds. The counts come from one
`GET …/overview` with the board's window, read again on `task_*`,
`request_*` and `probe_observed` and redrawn in place, with no Reload
offer. A viewer who is neither owner nor admin is in few of those
events' audiences (§8.2), so for them the view also re-reads every 60
seconds and when the tab or its window comes back. A trigger that arrives during a
read causes one more read after it, and a redraw puts the focus back on
the same link. If that call fails, links and members still show, and the place
of the counts says why they are missing.

**Reason:** the inbox is where the human acts. The overview is where
they look first after a while away, so it sits next to the inbox
without replacing it. A summary is not read line by line, so redrawing
it does not pull text away from a reader, which is why the contract
asks for it in place. Links and members do not depend on the new call,
so one missing endpoint should not blank the page.

**Rejected alternative:** the overview as the landing page. The contract
keeps the inbox there, and what waits for an answer matters more than a
summary. The board's "changed, Reload" notice would interrupt nothing
worth protecting here. One error for the whole view: it hides what the
page already has.

## The public swarm page is drawn from the hub's reduced body only, with initials, and opens with or without a session

**Id:** d81c0a1a-0d4c-4176-9a85-a56ef9f5975e
**Type:** decision
**Status:** superseded
**Superseded by:** b3982ae9-18ec-4e1a-b383-c8d68d817a71
**Evidence:** inferred
**Source:** docs/api.md §6.22 (the public body: agents only, no avatar, no card ids or titles, no member_id; served at #/s/<slug>), the card tsk-ejtazwt37dhp; the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub serves pictures to visitors, or the designer reworks the page

`#/s/<slug>` renders `GET /swarm/{slug}` before the page asks for a
session, so a member who follows a shared link sees exactly what the
world sees. Agents carry two-letter initials where the members' tab has
pictures; a card held is a count. Off, closed or unknown is one friendly
"no public swarm here" with a sign-in link, the same for all three.

**Reason:** the public page is what someone links to from outside; if a
signed-in member got the members' page at that address, they could not
check what they publish. The hub already strips what the world may not
see, so the page draws nothing from any other read — no member list, no
avatar path, which a visitor could not load anyway (§6.10). One message
for off, closed and unknown matches the hub's uniform `not_found`, which
must not tell whether a project exists.

**Rejected alternative:** sending a signed-in member at `#/s/<slug>` to
the Swarm tab: it would hide the public view from the people who decide
to show it. Generated avatars on the public page: they come from member
ids, which the public body leaves out by design.

## The overview leads with what needs the reader; its README badge is shown there and changed in Settings

**Id:** 057e7277-3eba-4267-93d2-c6b74a5e2ff1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's handover on the overview (#6484, tsk-qse9t2b3a9n8), 2026-10-27: the five panels had equal weight and the one thing to act on (open requests) sat bottom left; the maintainer's wish for a Contract link in the project facts (tsk-yhbmz7mjng7n, step 1), 2026-10-27; the dashboard's implementation, 2026-10-27
**Revisit when:** the hub serves the contract for reading inside Maity, or the overview gets other editing in place

Waiting for you and Board come first, then Team and Latest reports;
Project and README badge stood under Team (d7ee1073 below) and are the
Overview's Project tab since 2026-10-30 (58c58a28-d6b1-453f-99dc-7f21179b3ee2). A member in a list is a chip
(`M.dom.memberChip`), the shared form the member page header will use
too. The Contract link is `docs/api.md` on the forge at the repository's
default branch, built only for GitHub and GitLab, whose path shapes are
known. The badge panel shows the state, the badge and the snippet to
everyone; an owner or admin is sent to Project settings to change it
(**Change in Project settings**).

**Reason:** a person opening the overview comes to see whether anything
waits for them, so that is the first thing, with its action one click
away. The badge is changed in one place, Project settings, where the
project's other policy lives. Until #618 a badge change also needed a
logged reason, which Settings asked for; that argument fell away when
the badge alone needed none (docs/api.md §6.20, re-checked with the
coordinator on 2026-10-29), and the one place to change it is what
remains.

**Rejected alternative:** the designer's radio pills that change the
badge on the overview: a second place to change one setting, with the
overview the only view that edits in place. A Contract link guessed for
any forge: a wrong path shape would be a dead link that looks right.

## Project and README badge stand under Team, before Latest reports

**Id:** d7ee1073-1752-4134-9e51-878c5c28f2c2
**Type:** decision
**Status:** superseded
**Superseded by:** 58c58a28-d6b1-453f-99dc-7f21179b3ee2
**Evidence:** inferred
**Source:** the maintainer's screenshot and wish on tsk-b67chbx96n29 ("move the two blocks in front of Latest reports"), as the coordinator passed it on, 2026-10-30: on a wide desktop Project and README badge were a row of their own below the whole report list, with empty space under Team; the place under Team is the implementation's choice from the two the coordinator named
**Revisit when:** the maintainer asks for another place, or the overview gets a panel that competes for the space under Team
**See:** views.md — 057e7277-3eba-4267-93d2-c6b74a5e2ff1 — as of 2026-10-30

The second row is Team with Project and README badge under it
(`.overview-stack`), and Latest reports beside them. On a phone, where
the row wraps, the order is Team, Project, README badge, Latest reports.
That phone order follows from the page's own order alone: the smoke test
checks the order of the elements, not how the row wraps, so a CSS
`order` on Latest reports would put it first on a phone without a red
test.

**Reason:** Latest reports is a long list; whatever came after it was
out of sight, while Team left empty space beside it. Under Team the
facts fill that space on a wide screen and still come before the
reports on a narrow one.

**Rejected alternative:** Project and README badge as their own row
before the reports: on a wide screen it leaves the empty space under
Team and pushes the reports, the second thing a reader looks for,
further down. Keeping the three rows and only shortening the report
list: the wish was about the order, not the length.

## The swarm statistics are the Overview's Swarm tab, read on their own; no project tab, no public page, no switch

**Id:** 8a528eb5-8dd6-4fec-996e-79c5b57abb51
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 that the swarm is a statistic (root context/projects.md, bfe4c4a6, card tsk-w89mspg3gwx1); docs/api.md §6.11, §6.22, §16.11 after the contract #697; the card tsk-b8ndat73wttr; how the section reads and redraws is the implementer's, 2026-10-30
**Revisit when:** a public project's page draws the reduced numbers in the dashboard (§16.9), or the Overview gets a refresh of its own for the swarm

The project's Overview carries the **Swarm** section: who is at work
now, what each holds, and the window's counters with the 7/30/90-day
switch, as the old Swarm tab had them (`js/swarm.js`, `M.swarm.section`).
Since 2026-10-30 it is the Overview's own Swarm tab
(`/<owner>/<slug>/overview/swarm`, 58c58a28-d6b1-453f-99dc-7f21179b3ee2), no longer a row under
the counts. The section is built once per visit of that tab and reads
`GET …/swarm` itself, once and on a window change; a card, request or
probe event draws nothing there. There is no Swarm tab in the
project's row of tabs, no `/<owner>/<slug>/swarm` view, no public swarm page or `?as=public`, and
no `swarm_public` switch in Project settings; the fixture hub no longer
serves `/swarm/{owner}/{slug}`.

**Reason:** the maintainer made the swarm a statistic of the project,
not a place of its own. Read with the counts, every card event would
read the swarm again and reset the window the reader chose; the live
part has no event of its own to follow either, so it is as fresh as the
last read, as the tab was.

**Rejected alternative:** keeping `/<owner>/<slug>/swarm` as a redirect
to the Overview: the alpha rule, nothing old is kept for compatibility,
and the address was never shared outside the dashboard. Drawing the
section anew with the Overview's counts: a swarm read per card event,
and the window lost. Keeping the public page until public projects get
their pages: the contract removed its route and its switch.

## The Overview has three tabs, Summary, Swarm and Project; the organisation is a tab of the Team page

**Id:** 58c58a28-d6b1-453f-99dc-7f21179b3ee2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer, 2026-10-30, as the card tsk-n2r6t7jnzm2d passes it on (the Overview too full, split into tabs; the org chart on the Team/Members page as its own tab, not on the Overview; the swarm may stay or become a tab, the implementer's proposal); docs/api.md §16.11 (`organisation` is a project view); the split of the panels into the three tabs is the implementer's
**Supersedes:** d7ee1073-1752-4134-9e51-878c5c28f2c2
**Revisit when:** the GUI round with the maintainer moves a panel, or the Team page gets its Availability tab

2026-11-09: the project tab, the page title and the member page's breadcrumb are named Team (req-77az2zs017fe); its path stays /members. The Team page's own Members tab and its heading keep that name, so the Revisit-when lines on that tab are not triggered by this.
2026-11-10: the path follows the name: the view and its member pages are at /<owner>/<slug>/team (the maintainer's decision, so that the name and the path match; card tsk-yy9d5np8pjmr). `members` stays a reserved word, the maintainer's wish, so no slug or later view takes it; /members is a word that is no view, with no redirect. The Members tab keeps its name.

The Overview (`/<owner>/<slug>/overview`) has the tabs **Summary**,
**Swarm** (`overview/swarm`) and **Project** (`overview/project`), as
links with the shown one marked. Summary is what needs the reader and
the state: Waiting for you and Board, then Team beside Latest reports;
only it reads `GET …/overview` and re-reads it on card, request and
probe events and, for a narrow viewer, on its timer. Swarm is the swarm
section, read on its own. Project holds the facts (repository, state,
policy, contract, Keep the Why) and the README badge, read from what
the header already has. A tab the page does not know shows Summary.
The organisation tree left the Overview: it is the Team page's
**Organisation** tab at `/<owner>/<slug>/organisation`, a project view
the contract already lists, beside **Members** at `team`; both
pages carry the same two links (`M.teamTabs`), and the project's row
of tabs marks Members for either. The tree is drawn again when a member
event arrives.

**Reason:** one page with every panel had grown past what is read at a
glance; what needs the reader belongs on the first screen, and the
facts and the statistics are looked up, not watched. The swarm as a tab
keeps its own read out of every visit to the Overview. The org chart
describes the team, so it belongs with the team's list, as f0ca2279
planned the Team page.

**Rejected alternative:** the swarm kept as a row of Summary: a swarm
read on every Overview visit, and the page still long. The organisation
as a fourth Overview tab: the maintainer placed it with the team. A
`members/organisation` address: `members/<id>` is a member's page, and
a word there would have to be told apart from an id.
