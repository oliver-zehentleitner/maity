# Members

## The organisation tree is computed from reports_to and scope ownership, never stored

**Id:** 5fd2c906-3178-4b74-a1da-82a613302536
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's task brief, 2026-10-21
**Revisit when:** an organisation model needs a relation that neither `reports_to` nor scope ownership expresses

The organisation view builds an indented tree in the browser from the
members the API returns: each member sits under the member it reports
to; a member without `reports_to` sits under the owner of the narrowest
scope that contains its own; the rest are roots. Nothing chart-shaped is
fetched or kept. Each agent's node lists its live instances as links to
their Sessions on the member's page, the target an instance has everywhere
else; a dormant one says so beside its link.

The Agents page's Organisation tab (`agents/organisation`, the maintainer,
2026-11-02, tsk-q989pagmk2x9) is the same tree built from one's own agents
in the project alone, under oneself: a boss or an area owner of someone
else's places none of them, and an own agent that reports to someone
else's shows that as a stub with the boss's handle, as text (the
qualified `owner/handle` where another member shares the short one,
`M.dom.handleOf`, docs/api.md §6.3), and nothing more of the other side:
no name, no link to its page, no tooltip. Where the member list gives no
handle, the stub is the neutral sentence "reports to someone who is not
yours", never an id or a name. Its instances are dots in their presence's
colour, the lead ringed. Built from the same member list, so no second tree and no hub field.

**Reason:** set by the brief; the reason is inferred: a stored chart is a
second copy of the memberships and drifts from them the first time a role
changes, while a computed one shows exactly what the policy acts on.

**Rejected alternative:** a stored org chart edited on its own — the
drift above.

## A membership is edited in one form and sent as one PATCH of what changed; a reports-to circle is refused before it is sent

**Id:** ae257555-b3a4-4ba7-add3-1ab051c1f621
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request to set reports_to and areas from the dashboard, relayed by the coordinator, 2026-10-22; contract PR #118 (cycle), 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub offers the edit as separate endpoints, or a membership gains fields that need their own confirmation

Members → Manage holds one form for what docs/api.md §6.2 lets an admin
change: role (owner only for a human), reports to (nobody or another
member), areas (repository paths, the hub's pattern, never `..`),
capabilities (`tag`). The briefing has one editor, on the agent's card,
and is sent as typed. Save sends one `PATCH` with only the fields that
changed; edits not yet saved are kept per row across redraws (Done drops
them), and a 202 (a consent request, when a human's go is needed) is said
as waiting, the draft dropped and the form drawn from the hub's state, so a
second Save files no second request. The line names who is asked and, where
part of the change took effect at once, which part (the entry on consent
lines below). A drafted boss who has left the
project since is dropped and said at the field: a select that silently
fell back to "nobody" would send `reports_to: null` and clear the boss the
member has. A
reports-to that would close a circle is refused before sending, in the
words the hub's `cycle` refusal also gets. Capabilities the page does not
offer are kept as they are.

**Reason:** one form keeps an admin's change atomic (the hub applies it
in one write) and the organisation view follows at once. Refusing a
circle in the page spares a round trip and says why; the hub refuses it
too. Keeping unknown capabilities means an older page never strips what a
newer hub added.

**Rejected alternative:** one control per field with its own Save — a
role and a reports-to change that belong together would land as two
writes, and a failure in between leaves half a change. Sending every
field every time — a stale form would overwrite a change made meanwhile.

## A member is named through one helper, as a link to their row in Members

**Id:** 801bc195-cbbf-497a-82d0-7c40bc7567b1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's rule that agents and humans are always clickable, relayed by the coordinator (tsk-f7w3w35bq0r3), 2026-10-23; the dashboard's implementation, 2026-10-23; the maintainer's report that "Asked by" in the inbox was plain text, relayed by the lead on tsk-3re8qp89hc18, 2026-11-04 (web/js/inbox.js `ref` and `membersOf`, the e2e step `asker_links_step`); the review of PR #1356 that found links to members the project no longer lists, 2026-11-04
**Revisit when:** a member gets a view of their own apart from the Members row, or names appear inside a control that cannot hold a link

`M.dom.memberRef(ctx, who, opts)` is the one way a view names a member:
a link to `/<owner>/<slug>/team/<id>` (Members marks that row and focuses
it), the full name as tooltip, `data-member` for tests. A member the
project does not list (removed, outside) and every member in a view read
from outside the project are plain text. The inbox of all projects
reads the member list of each request's project among the reader's, once
per view, and names who asked, on whose behalf and to whom by it: a link
into the request's project for one that list names, text for one it does
not (a member removed since, a human who asks without a membership, a
project the reader is not in, a list that could not be read), as inside
a project. A name inside a button (an inbox entry's head) stays text,
since a link cannot sit in a button.

**Reason:** the maintainer wants to reach any member's actions from
wherever they appear, and one helper keeps the link, the tooltip and the
plain-text rule the same on every page.

**Rejected alternative:** a link built in each view: the rules for who
is linkable (listed, inside the project) would drift between pages.
Keeping the inbox of all projects plain text, as it was until
2026-11-04, since it read no member list there: the maintainer found the
plain name a dead end. A link built from the request alone, for anyone
it names in one of the reader's projects: the hub keeps an open request
of a member removed since, and names a human who asks without a
membership the same way, and both links opened only "No member with the
id … in this project" (the review of PR #1356, 2026-11-04).

## An invitation's link via the join host is offered only where the hub names one

**Id:** 35607b9c-4a72-4936-bcf8-63a429436ab9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.4 (`via`, "the dashboard's invite form shows 'link via <join host>', on by default, only when a join host is configured"), §1.1, §2.6 (`join_url` of `GET /auth/session`); the card tsk-053hsymxx1p8; the coordinator's ruling against a check of the machine form (the maintainer's alpha rule: no compatibility layer; the dashboard and the hub ship together, the hub's part #681 first), 2026-10-30
**Revisit when:** joins (§3.1) get the same choice in the join panel, or the e2e gets a join host of its own

The invite form reads `join_url` from `GET /auth/session`. Only when it
is set does it show **Link via <join host>**, ticked; it then sends
`via: "join"` or, unticked, `"public"`. Otherwise it sends no `via` and
the hub picks the link (`public`). The list says which link went out,
where a join host is named. The form takes `join_url` from the session the
page has read already (`M.api.session()`); that stays fresh because the
app reads the session again for every page it draws. The browser e2e
has no run with `MAITY_JOIN_URL`: the join URL must be https (§1.1), and
with a join host every join line defaults to `via: join` (§3.1), so the
e2e agent's `maity join` would go to a host that is not there; the join
host is checked after each deploy instead (`join-host.sh verify`).

**Reason:** the contract makes the choice exist only with a join host,
and a link to a host that does not exist would lead nowhere.

**Rejected alternative:** also asking the hub's machine form whether it
takes `via`, so a hub from before the field is not sent one: a
compatibility layer, which the alpha rule leaves out; the dashboard and
the hub ship together, the hub's part first. Always sending `via`,
`"public"` without a join host: the same as sending none, one more
field to keep right.

## An agent's owner sets whom it reports to, on Members and on Agents, without members:admin

**Id:** c848b045-9411-43b3-8763-2fd998270a1d
**Type:** decision
**Status:** superseded
**Superseded by:** e69c571c-3365-433a-b26d-245efff28a7d
**Evidence:** confirmed
**Source:** the maintainer's report (seq 16183) that a member who owns an agent found no field for whom it reports to, and the card tsk-0s3gztb6jba7, 2026-10-30; docs/api.md §2.3 ("A human may always set the reports_to of an agent they own to null or to a member they own …, whatever their trust and role"), §6.2 ("Across owners", "Pending"); the coordinator's ruling on the withdrawal button, 2026-10-30
**Revisit when:** the contract settles whether the owner may start a cross-owner edge, or gives the member view the pending edge (`reports_to_pending`); the hub's owner path (tsk-fw3x5c13vq9g, #759) lands

Without `members:admin`, one's own agent's row on Members has
**Manage**, holding only what its owner sets: **Reports to**, the
owner's preferences switch and the rulebook. **Reports to** offers
nobody, oneself (where a member here) and one's other agents in the
project, without those that would close a circle, and sends only
`reports_to`. The project's Agents shows the same form beside the
rulebook. A boss of another owner is never offered; one set already
stays chosen, marked, so that saving keeps it.

There is no **Withdraw** for an open cross-owner request about the
agent: §6.2 says nothing in the member view shows a pending edge, and a
request names no member, so the page could find it only by its title,
which a wording change would break. It comes with the contract's answer
on cross-owner edges (a field such as `reports_to_pending` for the two
owners).

The page and the fixture hub went ahead of the hub: until its owner
path for §2.3 (tsk-fw3x5c13vq9g, #759) is merged, the hub answers this
`PATCH` from an owner without `members:admin` with 403, so the two are
merged together. Showing the form only with `members:admin` until then
was rejected: the owner would still have no lever, and the page would
have to change again.

**Reason:** §2.3 gives the owner this lever whatever their trust; a
field only an admin sees left the owner none. A cross-owner boss files
consent requests (§6.2) whose start by the owner the contract has not
settled, so it is not offered until it has.

**Rejected alternative:** the whole membership form for the owner: it
would offer trust, role and areas the hub refuses them. Finding the
pending request by its title: fragile and invisible to the reader when
it breaks.

## An agent's credentials, briefing and pause live in its row on Members; an owner opens their own agents as Details

**Id:** 1c00024d-a3a6-49bc-ba2e-704359713aeb
**Type:** decision
**Status:** superseded
**Superseded by:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Evidence:** confirmed
**Source:** the maintainer's wish to fold the Agents page into Members → Manage (tsk-7v2snhk002ak, chat 2026-10-27); the coordinator's cut into two PRs and its tie to the decided Team page's Members tab (context/members.md f0ca2279: humans and agents in one list, actions per row), 2026-10-27
**Revisit when:** the Team page's Members tab lands, or a member page of its own takes the actions (tsk-rtb5vjrvbh34)

Opening an agent's row (members:admin) shows the membership form, the
briefing (edited there), whether it gets your preferences if it is
yours, its credentials with Revoke (read when the row first opens, kept
across redraws), the pause once, and Remove. Without members:admin a
human's own agents open as **Details**: credentials and the preferences
switch, nothing that changes the membership. With the join panel and the
placements moved too, the Agents page and its cards are gone; see the
entry on joining in Members.

**Reason:** one row per member, with what may be done to it, is the
Members tab the Team page decided; nothing a person could see or do on
the Agents page may get lost, an owner without admin rights included.

**Rejected alternative:** the owner's own agents read only, with no row
to open: their credentials and the preferences switch were theirs on the
Agents page. Loading every agent's credentials with the list: a call per
agent on every visit, for rows mostly never opened.

## Members is two tables without levels; only the organisation tree follows trust

**Id:** f4ec0c89-33e8-4f62-b192-371a23b91581
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on tsk-xxewyredc97a, 2026-11-01: the indent was agreed for the organisation chart only, and the two tables of humans and agents were good
**See:** members.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-11-01

Members shows a table of humans and one of agents, each in the hub's order, with no indent and no level by trust; the columns are again each table's own. In the Organisation tree, a member with no parent by `reports_to` or area stands at its trust's level, owners at the top, then admins, members and guests, each a level deeper; a level nobody holds leaves no step. Such a member is not put under one owner's node: with several owners that would draw a line to one of them that the project does not have.

**Rejected alternatives:** one list with levels (#949): a misunderstanding of the wish, which was about the chart only. Two tables each indented by trust: the same indent nobody asked for on the list.

## Members and the organisation tree follow trust: owners at the top, then admins, members and guests

**Id:** 9333bd7a-dbda-4c4f-88d8-fa08124ef06d
**Type:** decision
**Status:** superseded
**Superseded by:** f4ec0c89-33e8-4f62-b192-371a23b91581
**Evidence:** inferred
**Source:** the maintainer's wishes on the card tsk-05meme59sq1x, 2026-10-31, given in three steps: only owners at the top and everyone else indented; the order owners, members, guests; then the levels follow trust, owner, admin, member, guest, each a level deeper, and a level nobody holds leaves no empty step; for both the Organisation tree and the Members list, which becomes one list
**Revisit when:** a project needs a level the trust does not express, or the Team page shows reports_to in Members too
**See:** members.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-10-31
**See:** members.md#a-projects-tabs-members-a-neutral-list-with-chat-agents-ones-own-agents-the-organisation-on-the-team-page — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-10-31

Members is one list instead of a table of humans and one of agents. Its
rows go by trust: owners, then admins, then members, then guests, each a
level deeper (the name cell indented), within a level in the hub's
order. A level nobody holds is left out, so the next moves up. The
columns are both tables' columns; a human's agent-only columns (owner,
paused, Keep the Why) read "—". Only my agents still shows one's own
agents. In the Organisation tree, a member with no parent by
`reports_to` or area stands at its trust's level the same way. Such a
member is not put under one owner's node: with several owners that would
draw a line to one of them that the project does not have. A trust the
dashboard does not know counts as member.

**Reason:** the levels are the maintainer's (confirmed: "the real
hierarchy" has the owners as its root, then by trust). Read from that,
not stated by him: a human member and the owner on one level, as the
tree drew a member without `reports_to`, look like peers.

**Rejected alternative:** keeping two tables in Members and indenting
only within each, which would still put a member human beside the owner.
Hanging members without a parent under the first owner, which claims a
reporting line that is not there.

## A project's tabs: Members a neutral list with Chat, Agents one's own agents, the organisation on the Team page

**Id:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on the card tsk-3ap6mj5y1k2a, 2026-10-29 (Members neutral with a Chat per entry, the admin's Manage kept as it is; an Agents tab before Runners and Why, the component of /agents filtered to the project; the organigram into the Overview, the Organisation tab gone without a redirect); the maintainer's request relayed by the coordinator on the card tsk-ttywzxsaj1ht, 2026-10-31 (Agents right after Members, Jour fixe between Why and Settings); docs/api.md §16.11 (the project views, `agents` among them, `org` no longer)
**Revisit when:** the Team page's Members tab lands, or the hub lets an agent's owner pause or remove it without `members:admin`

2026-11-09: the project tab, the page title and the member page's breadcrumb are named Team (req-77az2zs017fe); its path stays /members. The Team page's own Members tab and its heading keep that name, so the Revisit-when lines on that tab are not triggered by this.
2026-11-10: the path follows the name: the view and its member pages are at /<owner>/<slug>/team (the maintainer's decision, so that the name and the path match; card tsk-yy9d5np8pjmr). `members` stays a reserved word, the maintainer's wish, so no slug or later view takes it; /members is a word that is no view, with no redirect. The Members tab keeps its name.

**Members** lists everyone in the project the same way for every
viewer: trust and role, presence, owner, joined, paused, a link to the
member and a **Chat** per entry (one's own agent: its direct chat;
anyone else: a new group chat with them chosen, `chat/new?with=<id>`).
With `members:admin` each row keeps
**Manage**, with the membership form, briefing, picture, rulebook,
credentials, pause and removal. **Agents** (`/<owner>/<slug>/agents`, for
humans) shows one's own agents in the project, each as its card on
`/agents` (`profileCard`, one component), with what belongs to the
membership under it: the preferences switch, the team's rulebook, the
credentials, and with `members:admin` the pause and the removal (§6.2
gives an owner without it neither). The join panel, the open joins, the
placements and the earlier joins are there; `…/agents/join[?agent=<id>]`
opens the panel, `…/agents/<id>/rulebook` the limit, and a new project
lands on Agents. The parts the Members row and the Agents card share
(rulebook, credentials, picture, pause, removal) are one code,
`M.memberParts`. The organisation tree was a section of the Overview,
redrawn there when a member event arrived; since 2026-10-30 it is the
Team page's Organisation tab (58c58a28-d6b1-453f-99dc-7f21179b3ee2). The join panel and the
placements belong to Agents because both are about one's own agents:
a join makes one, and where they run is managed by their owner or the
runner's; a list everybody reads is no place for either. In the row
Agents stands right after Members, and Jour fixe between Why and
Settings: Inbox, Overview, Board, Members, Agents, Chat, Messages,
Ticker, Why, Memory, Jour fixe, Settings (an agent sees no Agents tab).

**Reason:** Members is where one sees who is in the project and talks
to them; managing one's own agents is a different job, the same one as
on `/agents`, so it gets that page's component in the project. A tab
for one computed tree was a page to go to for what the Overview can show.

**Rejected alternative:** the earlier cut (1c00024d, 621d28a8): one's
own agents opened as **Details** in their rows on Members, the join
panel at the head of the agents' table, the placements under it, and an
Organisation tab. It mixed managing one's agents into the team's list,
and the list looked different to each viewer. A redirect from `…/org`
to the Overview: the alpha rule, no compatibility routes.

## An agent's bridges sit with its other member parts; a connection across owners is said as waiting for two consents

**Id:** 522e04b1-28b8-452a-a246-7f45e433e3c8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 "The bridge" after the contract #927 and the hub's bridges (the connection on the served agent's membership, `201` at once or `202` with the first of two consents, `bridges` and `bridging_for` in the member view, End for either owner, either agent and `members:admin`, cross-owner bridges among a group chat's observers); the coordinator's card tsk-x0krjnw8p78t (connect with a purpose on the agent's member view, owner only; the waiting line; both lists with End; "carries for @handle" in the group chat's header), 2026-11-01; placing it in `M.memberParts` and the waiting line's wording are the implementer's, 2026-11-01
**See:** members.md#a-projects-tabs-members-a-neutral-list-with-chat-agents-ones-own-agents-the-organisation-on-the-team-page — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-11-01
**Revisit when:** the member view carries open bridge requests, the hub's `202` names both consents, or a purpose may be changed from the dashboard (`PATCH …/bridges/{brg}`)

An agent's **Bridges** are one more part of `M.memberParts`, so the
Manage row on Members and the agent's card on Agents show the same:
the agents that lend it their hands (`bridges`) and those it lends its
hands to (`bridging_for`), each with its purpose, marked when another
owner's, and **End** for either agent's owner or `members:admin`; the
End goes to the served agent's membership, whichever side it is shown
on. Only the agent's owner gets **Connect with a bridge** (an agent of
the project that is neither the agent itself, a proxy nor already its
bridge, and the purpose). A `201` re-reads the members and says the
bridge lends its hands. A `202` is said by the part itself as waiting
for the consent of the bridge's owner and of the project: the hub files
both, but its answer names only the first, so the generic consent line
of the other member parts would name one human where two decide. Open
requests are not listed, since the member view carries only connections;
the consents are in the inbox as usual. In a group chat an agent among
the observers is such a bridge, said as "carries for" the participants
its `bridging_for` names; a human observer is said as before.

**Reason:** a bridge is a setting of the agent's membership like its
rulebook or its credentials, managed by the same people in the same
places, so it belongs in the parts both views share. Saying the two
consents keeps the owner from waiting on one human when the project has
to agree as well.

**Rejected alternative:** a page or tab of its own for bridges, apart
from where the agent's other membership settings are. The shared consent
line of `act()`, which names the request's one addressee. Re-reading the
inbox after a `202` to list the open request: the inbox already shows
it, and the part would read a second resource on every redraw. In the
e2e only the section is checked, since `e2e-alpha` has one agent and a
second join would cost a CLI pairing for this alone; connecting, ending,
the waiting line and a refusal are in smoke.

## A member's page is for reading; its Actions menu only leads to Members or Agents

**Id:** dda6f237-ffeb-4b68-ba0a-844c77f269dd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's handover #6484 (the member page header with an Actions menu: Assign a card, Edit briefing, Change role or reports to, Pause, Revoke the session, Remove), 2026-10-27; the coordinator's ruling on the card tsk-rtb5vjrvbh34, 2026-10-30, with the maintainer's decision of #643 (each action in one place) as its reason
**See:** members.md — 54a49af9-4763-4b4c-8624-bf2c51a2bc34 — as of 2026-10-29
**Revisit when:** the maintainer moves the admin's actions out of the Manage row, or a member page of its own takes over what the Agents card does

`/<owner>/<slug>/team/<id>` is a member's page: breadcrumb, header,
and the tabs Activity, Cards, Briefing, Sessions & credentials, all read
only. Its **Actions ▾** holds only links: **Manage on Members**
(`?manage=<id>`, the list with that row open) for an admin, **Manage on
Agents** (the agent's card) for its owner; without either there is no
menu. Every member link leads to this page, not to a marked row.

**Reason:** since #643 each action lives in one place: an admin's on the
Manage row of Members, an owner's on Agents. A third place for the same
forms would let them drift apart and leave the same change reachable
from three screens with three sets of words.

**Rejected alternative:** the Actions menu as the handover drew it, with
the actions themselves (role, pause, briefing, revocation, removal):
it would undo the one-place rule of #643. Taking the Manage row away
from Members in its favour: that reverses the maintainer's own choice
("finde ich super") for the row.

## Every role of §2.3 is offered from one list, by its label, with what the role does under the picker

**Id:** 43c080d3-e47c-45a3-9add-3da834cdf588
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's note that roles were missing (manager, the red team, …) and the card tsk-g62vwd7bqztk, 2026-10-30; the coordinator's brief for its web part (labels and short help texts from §2.3, the picker everywhere), 2026-10-30; docs/api.md §2.3 (the roles' table, the security teams), §3.1 (a member's own agent: not ops, not proxy)
**Revisit when:** §2.3 adds or drops a built-in role, or a project's own roles (§2.3) get a place in the pickers
**See:** members.md — b71cebbf-56d9-4f65-aef9-cbb4ab5131a1 — as of 2026-10-30

`js/trust.js` holds the one list of built-in roles, in the order of the
§2.3 table, each with a label ("Red team") and a few words of what the
member does, taken from that table. Every role picker (a member's form,
an invitation, a join, a member's own agent) fills its options from it
by label, with the role's words as the option's tooltip and, under the
picker, as a hint line the select is described by, following the chosen
role. What a picker offers stays its own rule: proxy only with trust
admin and only from an owner, a member's own agent every role but `ops`
and `proxy`. A security team counts as the role whose scopes it has
(red team as tester, purple team as reviewer) where the dashboard asks
who reviews, tests or prepares a release; the blue team counts as
coder, which no dashboard question asks for. The fixture hub keeps the
same roles in one list of its own. The list is the hub's too (`scopes.ROLES`
and `COUNTS_AS` since #711, the same §2.3): a role added or dropped on one
side is changed on the other in the same contract change. A member's
line elsewhere ("admin · red-team", `M.trust.words`) keeps the hub's
token: it is what the CLI and the hub's answers show, and the label is
for the moment a role is chosen.

**Reason:** the roles had been copied into each picker, and `manager`
and the three security teams were missing from all of them; one list is
one place to add the next. A token like `purple-team` does not say what
the member will do, and a choice of role is made by someone deciding
what an agent is for.

**Rejected alternative:** the tokens as the options' text, as before:
correct for the hub, unclear for the person choosing. The help as the
options' tooltip only: a tooltip is not read on a phone or by every
screen reader. A table of every role beside each form: longer than the
form it explains.

## Trust and role are shown and chosen as the hub keeps them; what only an owner may grant is not offered to others

**Id:** b71cebbf-56d9-4f65-aef9-cbb4ab5131a1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 (trust × role, owner_only, the guest's limits) and the card for the dashboard's part (tsk-tx9qcehevfnk), which replaces the interim mapping at the API boundary, 2026-10-28
**Revisit when:** a project's own roles (§2.3) get a place in the dashboard, or the hub lets a non-owner grant trust admin

The dashboard reads and sends a membership's `trust` and `role` as the
hub has them. Every view asks one helper (`js/trust.js`) who governs
(trust owner or admin, never a proxy, which relays and decides nothing
itself), who is an owner and who is a guest, and names a
member as "trust · role". The member form, the invitation and the join
line each choose trust and role on their own. Trust owner or admin and
the role proxy are offered only to a caller with trust owner, and proxy
only together with trust admin; a proxy whose trust changes becomes a
coder in the same change. An owner's membership is removed only by an
owner, so no one else is offered it. A guest is never offered as an assignee
or as whom someone reports to, and a human guest is offered no new
group chat. The overview groups the team by trust.

**Reason:** trust and role are two separate questions (§2.3): how far
the project trusts a member, and what the member does. A single name
could not say "admin reviewer" or "guest coder", and the interim mapping
lost exactly those. The choices the hub refuses for a non-owner
(`owner_only`) or for a guest would only lead to a refusal, so they are
not offered.

**Rejected alternative:** keeping the mapping between single-role names
and trust and role at the API boundary: it translated every answer and
body and could not show a guest's role or a reviewer with trust admin.
Offering every choice and saying the hub's refusal afterwards: a form
that offers what it will refuse.

## A member's Activity reads the hub's latest 5000 events and says so

**Id:** 4c3f8949-c8df-4c99-bb0c-08dc47205eed
**Type:** workaround
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §8.3 (an event's `seq` counts across the whole hub; a feed is read forward with `after=` only, without a filter by actor) and §8.8 (the listing holds messages only, with no filter by sender); the coordinator's review of #687, 2026-10-30 (the window `after = head − 200` counted the hub's events, not the project's); the rule from the incident of 2026-10-26: no request whose cost grows with history; the card tsk-0m6qx612y5px and lotse's agreement, 2026-11-04 (project message seq 69405): the Messages view moves to §8.8, the Activity keeps the window
**Revisit when:** §8.3 takes `actor=` (`GET /events?actor=`)

The hub cannot be asked for one member's events, nor for a project's
latest events counted in that project. The member page's Activity
therefore pages through the project's feed from the hub's latest 5000
`seq` forward (its own scan in js/member-page.js), keeps the member's
own events that are not redacted, and shows the newest 50; each opening
of the page reads up to 26 pages of 200, a cost bounded by the window,
not by history. Where the window cut something, it says it counts the
hub's latest 5000 events, all projects counted, so a quiet member in a
busy hub reads as cut, not as idle. A cursor that does not move stops
the read with an error. The Messages view no longer shares this scan:
it pages through the message listing (§8.8, 8e483bb1) since 2026-11-04.

**Reason:** what the client can afford to read is bounded by the hub's
numbering, not the project's; a sentence that names the project's events
would promise what the window cannot see. The Activity stays on the
window when the Messages view leaves it: it lists every kind of a
member's events (cards claimed, requests answered, members joined, and
messages), while §8.8 lists messages only and cannot be asked for one
sender, so it would show a fraction of the Activity and still need the
scan for the rest. Settled with lotse on 2026-11-04 (seq 69405).

**Rejected alternative:** reading the whole feed from the first event:
its cost grows with the hub's history, which the 2026-10-26 rule rules
out. A window of 200 for the Activity: in a busy hub it held few or none
of the project's events and said nothing about it. The Activity from
§8.8 alone, filtered to the member in the page: it would drop every
event that is not a message and page through every sender's messages to
find one member's.

## Members filters to one's own agents with Only my agents, kept per viewer in the browser

**Id:** 7b08511c-7f7e-4af2-bd7e-df6f01476e0b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer, 2026-10-30, as the card tsk-n2r6t7jnzm2d passes it on (a filter 'Only my agents' on the members list, the member's `owner` being the signed-in human, remembered per viewer); where it is kept is the implementer's
**Revisit when:** the hub keeps per-viewer view settings, or the GUI round asks for the filter on other lists too

A human viewer of Members gets the checkbox **Only my agents**. On, the
list is the agents whose `owner_id` is the viewer, and the humans'
table is not drawn; with none, it says so. The choice is kept in the
browser's `localStorage` under one key per viewer
(`maity.members.mine.<member id>`), for every project, and a browser
that keeps nothing still filters for the visit. Agents never see the
box: they own no agent. What an owner may change on their own agent's
row without `members:admin` is unchanged (Manage with reports to,
preferences and team, §2.3).

**Reason:** the maintainer wants their own agents at a glance on a list
that holds everyone's. A per-viewer key keeps one person's choice from
another's on a shared browser, and the hub has no field for view
settings.

**Rejected alternative:** one key for every viewer: a second person
signing in on the same browser would inherit the filter. A key per
project: the maintainer asked for it per viewer, and switching projects
would lose it. A setting on the hub: there is no such field, and a
contract change for a list filter is out of proportion.

## An agent is isolated from its Manage row on Members, with a reason and a confirmation; the row and the list show it

**Id:** d2546b1d-4a69-4e89-9b98-d9b894c572ed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-n2r6t7jnzm2d (humans with members:admin get Isolate / Lift isolation with a reason, and the `isolated` badge); docs/api.md §6.2 "Isolation" as of #771; the coordinator's go to build against the contract before the hub's #783, 2026-10-30; where the controls stand and the confirmation are the implementer's; the card tsk-zwxtdfmdscf7 (the maintainer, 2026-10-31: a box in the lift dialog, unticked by default, hides the isolation's events; contract #826, the hub's reason in `context/members.md`)
**Revisit when:** the GUI round moves the member actions into a menu per row (f0ca2279), another owner's agent gets Propose change beside it, or the hub lets a hidden window be shown again

In an agent's **Manage** row, for a human with `members:admin`, after
the pause: **Isolate with a reason** (1–500 characters), sent as
`POST …/members/{id}/isolate` after a confirmation that names what
happens at once; an isolated agent shows who isolated it, when and why,
and **Lift isolation** (`DELETE` on the same path, no confirmation). The
name cell carries an **Isolated** badge with the reason in its title, on
every reader's list, since the member view carries `isolated` for all.
An agent's own caller and a member without `members:admin` get no
control. The fixture hub answers both routes as §6.2 describes.
Lift isolation sits in a small form with one box, **Hide what happened
while it was isolated**, unticked, and a line on what it means; ticked,
the `DELETE` carries `{"hide_isolation_events": true}`, unticked it
carries no body. The choice survives a redraw of the table (another
action, the presence refresh) as a typed reason does: it cannot be made
up for after the lift, the window comes only from the lift itself. A member with hidden windows (`isolation_windows`)
shows them under its name, as event ranges, to every reader of the
list, as `isolated` is shown; a seq is written as the hub gives it, not
formatted as a number.

**Reason:** isolation is the project's lever against a misbehaving
agent, beside the pause and the removal that already live in that row;
it takes effect at once for an agent another human owns, so the
confirmation says so before it is sent. Lifting gives access back and
loses nothing more, so it needs no question; whether the agent may read
the isolation's events again is the one choice it carries, and the box
starts unticked because the hub's default keeps them readable (§6.2).

**Rejected alternative:** a separate Isolate button on the list row:
the row holds Chat and Manage only (54a49af9), every other member action
is in Manage. Isolating without a confirmation like the pause: the pause
is a soft stop the owner may lift, isolation releases claims and closes
placements of someone else's agent.

## Availability and cover hang under the presence as one note

**Id:** a242b4f7-0f84-459e-bb59-84934ed93cd3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.12; #980

On Members, the Agents tab and a member's page, availability and cover
hang under the presence as one note: away until when and why (the hub
already drops a human's reason outside `show_reason_in`), resting when
every instance is dormant, who covers this member and whom it covers.
`available`, `offline` and `paused` get no note: presence and the paused
pill already say them.

**Rejected alternative:** a column of its own on Members: it would be
empty in nearly every row and does not fit the narrow layout.

## A membership's links stand only where they open

**Id:** b805d135-78b3-47b7-b293-1d42fe4fc04c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-svqsdp6qf0f3; reviews of #1020

On a profile, the project and rulebook links stand only where the human is a member, and Join link also needs a project that takes the agent. `member_agents` is not in `GET /me`, so a member can still follow Join link into a project with it `off`; the project's page then says there is no form.

**Rejected alternatives:** always linking, which ends on a 404 or in silence; reading the policy per project on `/agents`, too many reads for one link.

**Known limit:** a click on Join link at the same address does nothing, as `M.route.go` ignores that.

## A consent line names who is asked and calls saved only what the member, read again, already has

**Id:** 71dc43d7-fef5-4123-83de-841dcc06c2bd
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-0dhk4wdt111m (the owner set another owner's agent to `red-team` and the form showed `coder` again; events 64676 and 64711); the lead's decision on the card; docs/api.md §6.2 ("Another owner's agent"); hub/src/maity_hub/foreign_agent.py, cross_owner.py; web/js/members.js `consentWords`; the review of #1312
**Revisit when:** the hub's 202 says which fields it applied and whose consent each request waits for, or a member shows its open consent request

A `PATCH` of another owner's agent answers 202 with one consent request
while part of the change may already have applied: the hub takes a
`reports_to` to a boss of the agent's own owner, or none, at once, and
holds trust, role, areas and capabilities for the owner's go. The 202 names
the asked human as `human:<id>` and says nothing of what applied. So the
members view reads the member again after the call and calls saved only the
fields it now has ("Saved: reports to. The rest is not changed yet: …"), and
names the asked human by name where they are a member here, otherwise as the
agent's owner (its `owner_id`) or, when the answered request is another
human's, as a boss's owner. In a `PATCH` that also changes a held field the
hub files that field consent, which goes to the agent's owner, first and
answers with it; only a `reports_to` to a boss of another owner on its own
is answered with an edge request, the boss's side unless the caller is that
human, then the agent owner's (hub/src/maity_hub/routes/members.py,
cross_owner.py).

**Reason:** the hub's answer is the request alone; without reading the
member again the line either claimed nothing changed while the boss had, or
claimed a save the hub had not made. The raw `human:hum-…` was what the
owner read on 2026-11-03.

**Rejected alternatives:** showing the hub's `to` as it comes (the raw
address); keeping "Not changed yet" for the whole change; assuming that
`reports_to` always applies at once (a boss of another owner waits too).

**Known limit:** where several requests are filed (fields and a cross-owner
edge, or an edge both of whose owners are asked), the line names only the one
the hub answers with.

## The organisation's Paths face draws only edges the members API gives; an event's usual edges are marked as usual

**Id:** 04ce10bd-5160-46e3-bb6d-7c3f760f4167
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-j9ktmj7e4fxq, 2026-11-05: the lead's answer to the request on the card (req-x3hgj0b7xzy3), choosing the members API as the only source and usual edges marked as such; the designer's approved draft for the layout
**See:** members.md#the-organisation-tree-is-computed-from-reports_to-and-scope-ownership-never-stored — 5fd2c906-3178-4b74-a1da-82a613302536 — as of 2026-11-05
**Revisit when:** the hub names an event's recipients itself (a routing read), or a team's lead has more than one role group too wide for the canvas

The Team page's Organisation tab has two faces, Tree and Paths, the choice kept per browser. Paths (`js/paths.js`) draws the team top-down from `reports_to`, humans first, a lead centred over its members, and more than six members of one role under one lead folded into one box that opens in place. The reporting lines are a chip of their own, on by default; four more chips draw where one event goes, from the routing of docs/api.md §8.2 and §8.4: a review result to the reviewer's lead, not listening to the agent's lead, the admins and the owner (never a meat proxy), a request to a human to the agent's owner, and a card assignment from a lead to the member and the member's owner. Every edge is computed from what `GET /members` returns. Where the hub's routing depends on something the members list does not carry (who assigned the card, who wrote the reviewed PR), the edge is drawn as usual, dotted and named "usual" in the legend, or only said in the chip's note. At phone width the drawing gives way to a list of cards, each naming whom the member reports to and what it gets.

**Reason:** a picture of the routing that the hub does not do is worse than none; the members list is what the dashboard already reads, and the usual edges answer the question readers ask (who hears about this) without claiming the hub computed them.

**Rejected alternatives:** a routing table of the dashboard's own, kept beside §8: a second copy that drifts from the hub. Leaving out the edges the members list cannot settle: card assignment, the most asked about, would show nothing. A force layout: it moves on every redraw and hides who reports to whom; the draft's tidy tree keeps the hierarchy readable.
