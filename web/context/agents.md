# Agents

## A join's state comes from its fields and the hub's clock; Revoke stays a minute past expiry

**Id:** b8c3a4f4-1e21-4de1-9a82-7abe86456259
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report of an expired join still listed as open, relayed by the coordinator, 2026-10-22; web PR #107 and its review, 2026-10-22
**Revisit when:** the hub sends a join's state itself, or a join's lifetime becomes much shorter than a minute

Join an agent lists each join with the state its fields give, in the
hub's order: revoked, used, burned (three wrong codes), expired; open
joins first, the others muted and labelled. Expiry is judged by the
hub's clock: this browser's clock corrected by the `Maity-Server-Time`
of the last answer (docs/api.md §1.2), re-judged every 10 s while the
view is open. A join that expired less than a minute ago keeps Revoke,
and a Revoke the hub refuses (`invalid_transition`) is said and the list
re-read.

**Reason:** Revoke is the safety valve for a leaked line. A browser whose
clock runs ahead would hide Revoke while the hub still accepts the line;
the hub's time, and a minute's grace in which the hub decides, keep the
valve where it is needed. The order mirrors the hub's, so the page never
calls "expired" what the hub calls "used".

**Rejected alternative:** the browser's clock alone — wrong by the
client's skew, which on a laptop can be minutes. Hiding Revoke exactly at
`expires_at` — the second the hub and the page disagree is the second a
leaked line is pasted.

## Joining an agent happens in Agents: a panel under the title, open joins as seats in the grid

**Id:** d80f865d-5b59-4ad1-8cc2-c1079d13869c
**Type:** decision
**Status:** superseded
**Superseded by:** 621d28a8-36f5-4ebd-a90a-f7d729d7af34
**Evidence:** confirmed
**Source:** the maintainer's wish that Join an agent be part of Agents, not a page of its own (tsk-rf6qynscm6px), 2026-10-23; the designer's layout for it, 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** joins get a lifecycle of their own beyond open, used, expired, burned and revoked, or the Agents view is split

Join an agent is no longer a tab. Agents' title row has **+ Join an agent**
(owner and admin), which opens an inline panel under it, closed by
default and open at once in a project without agents or at
`#/p/<slug>/agents/join`; the old `#/p/<slug>/join` opens the same. The
form keeps its logic (js/join.js) in two columns; a made join's line
takes the form's place, with Join another and Done. An open join is a
dashed **open seat** at the front of the agents' grid; the rest of the
joins are folded at the view's end as Earlier joins.

**Reason:** joining is how an agent gets into that view, so the action
sits where its result appears; an open join is a member that has not
arrived yet, so it stands among the members, not in a list of its own.
The record of old joins is rarely needed.

**Rejected alternative:** a modal dialog for the form: it hides the grid
the seat appears in, and the panel works the same at 390 px. Open joins in
a section of their own below the cards, the first idea: it kept them
apart from the team they join.

## Agents are shown by owner/handle only where the short handle is shared in the project, and one's own profiles always

**Id:** d21eff03-cd0b-4977-9e9f-85eb7cc5cbed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.3 (the global name, shown inside a project wherever two members share a short handle), §8.6 (long mentions, a human comes first, ambiguous_mention), the card tsk-zx7brc52q9xg, 2026-10-25; the dashboard's implementation, 2026-10-25
**Revisit when:** handles become unique per instance, or the designer wants the long form everywhere

One helper (`M.dom.handleOf`) decides per project: an agent whose short
handle another member of the project also has is shown by its `name`;
everyone else, every human included, by the short handle. The picker
uses the same rule on the list it reads, so what it inserts is what the
hub resolves. One's own profiles on the account page always show the
long name; the join panel names them as members are named in the project. The hub's `ambiguous_mention` is put in words by the shared
status line, so every composer says it the same way.

**Reason:** the short handle is what people read and type in a project;
showing `owner/handle` everywhere would lengthen every line for the
rare case. Deciding by the project's own member list mirrors the hub's
rule exactly, so the dashboard never shows a short handle the hub would
refuse in a mention. A human keeps the short one because the hub resolves
it to the human first.

**Rejected alternative:** the long form for every agent in every view:
noise for the common case. Translating the refusal in each composer:
six places to keep in step instead of one.

## A join for an agent that is already a member asks which instance it makes, replace preselected

**Id:** 48b11115-3f26-4f0b-b3c6-7e50cb6d9b90
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's incident: after a lost first join, a new join for the same agent failed with "the agent is a member: new_instance or replaces" and the dialog had no way to say it (tsk-02251dpwm8kp), 2026-10-25; docs/api.md §3.1, §6.17; the dashboard's implementation, 2026-10-25
**Revisit when:** the hub lets a member's join change the membership, or the designer reworks the join panel

When the chosen agent is a member of the project, the join panel shows a
choice instead of role, areas and briefing (whom it reports to has a field
of its own, e69c571c): **Replace
instance** with the member's active instances (presence, cards held) or
**Start another instance** with the team's count against its limit.
Replace is preselected when there is an active instance. The join then
carries only the agent, the expiry and `replaces` or `new_instance`. A
refusal `instance.required`, or `differs_from_membership` on a field the
form sent (the hub checks the membership's fields first; either way the
list on screen was stale), reads the members again and offers the same
choice; the human creates it again.

**Reason:** the usual way here is the incident's: an instance whose
credential got lost, which a replacement takes over with its cards;
another instance beyond the default limit of one is refused anyway. The
membership's fields must be omitted or equal for a member's join, so
offering them would only invite an `invalid`; they change on the card.
The hub's refusal is the final word, as the list may be older than it.

**Rejected alternative:** creating the join right after the refusal with
a guessed choice: replacing revokes a credential, which the human picks.
Keeping role and areas in the form and sending the membership's values:
the human would see fields that do nothing.

## A first join may name whom it takes over from and the hand-over; a message's hand-over links to Messages

**Id:** 3d623647-4575-492b-9252-e215afa0e87e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §3.1, §5.2, §6.2 (contract #896); the card tsk-tj523m1r2z7y; the hub's part (#900); the dashboard's implementation, 2026-10-31
**Revisit when:** the hub gives a message a page of its own, or offers a search for cards and messages a field could use
**See:** views.md#a-join-for-an-agent-that-is-already-a-member-asks-which-instance-it-makes-replace-preselected — 48b11115-3f26-4f0b-b3c6-7e50cb6d9b90 — as of 2026-10-31

The join panel has two more fields for a first join, hidden like the
membership's fields when the chosen agent is already a member:
**Takes over from**, a choice of the project's agent members other than
the chosen agent (for a member bringing their own agent, only their own
agents, as the hub allows), hidden when there is none to choose; and
**Hand-over**, a text field for a card id or a message's number, sent as
a number when it is all digits. The hub's refusals (`first_join_only`,
`not_an_agent_member`, `not_found`, `not_readable`, a member's limit on
`takes_over`) are said in words at the field. A join and a member that
named them say "Takes over from @handle; the hand-over is in …", the
handle linking to the member and a card to its page. A message has no
page of its own, so "message #seq" links to the project's Messages view.

**Reason:** the contract lets the hub check both values, and its answer
is the final word. A text field takes either kind of hand-over without
the panel first reading every card and message. A link to Messages
still leads the reader to where the message is listed.

**Rejected alternative:** a picker of cards and recent messages: it
would read the whole board and the event window for one optional field,
and a message to all from before that window could not be named. An
unlinked "message #seq": it leaves the reader nowhere to look.

## Placements are a section of Agents; stop goes at once, restart asks once more, consent stays in the inbox

**Id:** 5273b057-4d96-41b8-bd5f-e52f8828450c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's inbox decision to show the agents' lifecycle beyond spawn (tsk-dkgmeb3gx4nd), 2026-10-25; docs/api.md §15.5–§15.7, §15.10; the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the designer answers on the row layout, the hub lets the dashboard know runner ownership in the placement itself, or placements get a page of their own

Where an agent runs is a section of the Agents view, after the grid:
one row per active placement with what is wanted and what the runner
last reported. Stop and Start are one `PATCH` of `desired` each, Stop
without a question; Restart asks once more inline before its `POST`; a
new join is offered only when the placement's credential is revoked
among the credentials the view already reads. Actions show for a human
admin who is the owner (`owner_id`) of the placement's runner — `GET
/runners` also lists runners attached where one is an admin — or the
agent profile's owner. A placement waiting for consent offers only the
link to its inbox request: there a stop would withdraw it and a restart
approve it.

**Reason:** the agents' cards are where people look for an agent, and
the section reuses the credentials the view reads anyway. Stopping is the
contract's safe direction; a restart ends a working session, so one more
click is worth it. Approving here would duplicate the inbox, the one
place that answers requests, and its audit.

**Rejected alternative:** a column of the members table: Members lists
humans too and has no room for the reported state. A modal confirmation
for restart: one more click inline does the same at phone width. Asking
the hub for each credential to decide on `rejoin`: the view has them.

## An agent is started on a runner from Agents' Where they run, on one's own live runners only

**Id:** 7baa75e7-2cf3-4cb5-ae41-93e04cdb71d9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-dsp6htj4c686 (the owner said yes to req-t9ev5zkeeg00, 2026-11-09: his runner was paired and online, and the dashboard had no way to start an agent on it; a "Start on a runner" form on the Agents page, an existing agent or a new profile, docs/api.md §15.6); the choices below about which runners and tools are offered are the implementer's
**Revisit when:** the hub lets an agent propose a placement from the dashboard (`agents:propose`), a runner of someone else can be attached (§15.4, invitations), or the form needs a field the join panel has and this one lacks (the subagents instruction, a take-over)
**See:** views.md#placements-are-a-section-of-agents-stop-goes-at-once-restart-asks-once-more-consent-stays-in-the-inbox — 5273b057-4d96-41b8-bd5f-e52f8828450c — as of 2026-11-09

Where they run, on the project's Agents, has **Start an agent on a runner**
for a human with members:admin. It offers the runners attached here
(`GET …/runners`) that the human owns, whose credential is live and which
offer the project's repository: one of the runner's advertised
`repositories` matches the repository's URL without `https://`, with the
hub's rule (`check_repository` in `hub/src/maity_hub/placements.py`,
Python's `fnmatch.fnmatchcase`; `fnmatch` in `web/js/placements.js` is its
port, a `[…]` set read as Python 3.12's `fnmatch.translate` reads it, so a
reversed range such as `[z-a]` matches nothing, `[!z-a]` any one character,
and neither throws and hides the runner's other patterns; the name is read by
Unicode character, as Python reads it, so `?` takes a character beyond U+FFFF
whole (an advertised pattern is printable ASCII, `Name` in
`hub/src/maity_hub/routes/runner.py`; the port reads any pattern the same
way); and a `*` is matched by going back only to the last `*`,
not by one RegExp over the pattern, so many stars against a long name take
time in proportion to the two lengths, not seconds). With none, the section says so and links the project's Runners; with
attached runners of which none offers the repository, it says that and
names the repository; a project without a repository offers no form and
says a runner needs one. The agent is one
of the human's own agents here without an active placement, or a new
profile with the join panel's fields (trust, role, reports to, areas,
briefing). Where, tool, mode and model come from what the chosen runner
last advertised: reachable targets, installed tools for that target, the
tool's modes with its default chosen, its models or the runner's default.
Without a tool, Start is disabled. The call is one `POST …/placements`. A
refusal shows the hub's message, code and named fields, and the new
placement is listed by reading the list again. The route asks for no
second factor, so the call is not wrapped in `M.stepUp.run`.

**Reason:** the placements are already shown and steered here, so the
form sits beside them. Offering only what the hub accepts keeps the
choices few: someone else's runner is `forbidden`, a revoked one
`runner_revoked`, an agent placed already `placement_exists`, a tool
that is not advertised `harness_not_offered`, and a runner that does not
offer the project's repository, or a project without one,
`repository_not_offered` (the last added by tsk-wn6qp27090qy, after a
re-check of the merged form found such runners offered).

**Rejected alternative:** the form on the instance-level Runners page:
there the project would be one more choice, and the placements are not
shown there. Free text for the tool and the model: the runner advertises
the lists, and a typo would only be refused by the hub (a tool it does not
know as `invalid`, a model the runner does not offer as
`harness_not_offered`, `_check_spec` in `hub/src/maity_hub/routes/placements.py`).
Listing every attached runner and letting the hub refuse: a choice that
can only fail. Listing a runner that does not offer the repository as
unavailable instead of leaving it out: the other runners the hub would
refuse are left out too, and with none left the section says why.

## The Agents page reads credentials only for its own agents that are placed

**Id:** a71aebc3-1d25-4e28-90ce-f96f8c716c02
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the performance measurement on tsk-a5pxwgkgr73e (step 1, 2026-11-08: 27 credential lists at once, queuing from 95 to 568 ms); the plan on tsk-d61rvjm6gteh (PR C), approved by the coordinator the same day
**Revisit when:** the placements list carries whether its credential was revoked, or the member list carries the credentials

A project's Agents page read the credentials of every agent of one's own
in it, at once, before the "Where they run" section could draw. That
section needs them only to know whether a placement's credential was
revoked, which decides whether **Restart with a new join** is offered. It
now reads the placements first and asks for the credentials of one's own
agents that have a placement, once each; a placement that appears later
asks for its agent then. It listens for placement events before its first
read, and reads the list again once it stands if one came meanwhile.

**Reason:** on the measured project those reads were the page's slowest
part, and most of them served nothing: few agents have a placement.

**Rejected alternatives:**
- The credentials read when a row is expanded: the rejoin choice stands in
  the placement row as it is drawn, so the read would only move.
- The revoked state in the placements or member list: one read less, but a
  contract change, which this card's boundary excludes.

## An agent is named with the instance that wrote or did it, as <handle>#<id>

**Id:** 0b6d2a5f-32ba-4979-8c18-1567498ecbac
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish relayed by the coordinator (tsk-6sxbvsf87219), 2026-10-27: when a handle has several instances it must always be visible which one wrote; docs/api.md §6.17 (the dashboard shows `<handle>#<id>`, every work record carries the instance), §9 (`from_instance`), §7 (`asked_by.instance`), §8.1 (`actor.instance`); the dashboard's implementation, 2026-10-27; the maintainer, 2026-10-31 (tsk-bczgjkfpw1wg): `@handle#id` offered by the @ picker and shown as two links everywhere
**Revisit when:** the contract gives an instance a name of its own or a view of its own, or the hub names harness and model on a chat message

`M.dom.memberRef` takes `opts.instance` (an id, or a record with
`instance`, `harness`, `model`). With one, an agent reads
`<handle>#<id>` (`owner/handle#id` where two agents share the handle,
`@…` where the view names handles; the name, where a reference read
across projects carries no handle), the `#id` muted, a link of its own
beside the handle's and not in it, with
"Instance <id> · <harness> · <model>" as its tooltip where the record
says them (an event's `actor` does, a chat message does not). Chats
(direct, group, global), the project messages, the ticker, the inbox's
asker, the overview's reports and a card's notes and history pass what
their record carries; without an instance, or for a human, the name stays
as before. An id that is not an instance id is not shown. In a chat two
instances of one agent are two senders: their messages are never grouped
under one name. The handle leads to the member's page, the `#id` to
the same page's Sessions with that instance's line marked and focused
(`…/team/<id>/sessions/<instance>`), where no link is possible (a
member the project does not list, a view from outside) both stay text.
A stored mention `@handle#id` in a text reads the same: two links, the
member and its instance. The @ picker offers, after each agent, its
instances that are not revoked as `@handle#id`, a dormant one marked,
in the slots the members leave free, so a short `@` shows as many
members as before; typing `#` after a full handle narrows to that
agent's instances. An address naming an instance the member does not
list says so on Sessions instead of marking nothing. Until
2026-10-31 the `#id` led nowhere (the designer's pass on #429: it
names, it leads nowhere else); the maintainer asked for it to lead to
the instance.

**Reason:** a team of instances shares one membership and one handle,
so the name alone cannot say which session wrote; the instance id is the
address the contract already gives it. Keeping it in the one helper keeps
the form the same on every page.

**Rejected alternative:** the handle and the `#id` as one link: the two
lead to different places, the member and its instance, and one link
could only reach one of them. The `#id` leading to an instance view of
its own: the contract has none, the member page's Sessions already lists
the instances. The display name with the id after it: the
contract names an instance by handle, and that is what a reader types to
reach it (`@handle#id`). Showing the instance only on hover: the
maintainer wants it seen without looking for it.

## An agent card's admin actions sit in one Actions menu; the pause form opens from it

**Id:** 0d1a03cd-81e9-4895-af2d-ef8dc54806a6
**Type:** decision
**Status:** superseded
**Superseded by:** 1c00024d-a3a6-49bc-ba2e-704359713aeb
**Evidence:** confirmed
**Source:** the designer's pass part 3 on #366/#369 (tsk-w2xnkrwf147m), 2026-10-27: every agent card carried an open Pause form with its hint, which made each card about twice as long
**Revisit when:** the member page header gets its own Actions menu (the designer's overview handover), so both can share one list

An admin sees **Actions ▾** at the end of an agent card's header
(`M.menuButton`) with **Pause…** and **Edit briefing** (or **Write a
briefing**). The pause form stays in the card, folded; **Pause…** opens
it and focuses the reason, **Cancel** folds it again. A paused agent
keeps its one **Clear pause** button in the card. The briefing's text
and its own edit button stay, since they are content, not a control.
Revoking stays beside each credential in the card's list.

**Reason:** one control in the header keeps the cards short and
scannable; the actions are rare, the facts are what is read.

**Rejected alternative:** Revoke… in the menu, as the designer sketched
it: revoking is per credential, and an agent may hold several, so the
menu would need a second choice the credential list already makes. A
dialog for the pause: the folded form keeps its hint and status in
place and needs no focus trap.

## A dormant instance is said with its address wherever the instance is shown, and put to rest where an agent is managed

**Id:** b4065586-3275-4bfe-a3a0-c5b45d720d61
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-p6edzbw9gwjp, 2026-10-31; docs/api.md §6.17 ("A dormant instance", contract #817), §6.12 (`source: dormant`), §6.2 ("Another owner's agent"); the maintainer's ruling that each action has one place (#643)
**See:** https://github.com/oliver-zehentleitner/maity — 9d2cc07a-0158-4042-ad71-eb9801ceaf77 — as of 2026-10-31
**Revisit when:** the hub lets an agent put a sibling to rest, or a dormant instance gets a reason or an end of its own

A dormant instance reads "dormant — ask @<handle>#<id> directly" in
every place that shows the instance:
- the presence cell on Members;
- the member's Sessions tab;
- the organisation tree;
- the chat's instance picker.

When every instance is at rest, the member's row also says that only an
instance address reaches it (`availability` `limited`, `source:
dormant`). Putting an instance to rest and waking it is a list of the
instances, one button each, in the agent's Manage row on Members and on
its owner's card on Agents. It is offered to the profile's owner and to
a human with `members:admin`. An admin's change to another owner's agent
comes back as that owner's consent request, said as "not changed yet".
The team's lead instance gets no button, because the hub refuses it.

**Reason:** the instance is kept so that someone can still ask it, and
that only works if the address that wakes it is in view wherever
someone looks for the agent. The setting goes where the pause and the
rulebook already are, one place per action (#643). The member page
stays for reading.

**Rejected alternatives:**
- A "dormant" pill without the address: the reader would still have
  to work out how to reach the instance.
- The buttons on the member page: it only leads to Members and Agents
  (dda6f237).
- Offering the lead and showing the hub's refusal: a button that
  always fails teaches nothing. The hint says to choose another lead
  first.

## Whom an agent reports to is chosen where it joins, a boss of another owner offered and marked

**Id:** e69c571c-3365-433a-b26d-245efff28a7d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request (req-a5xxyvq74ft7, seq 86060): on Agents, letting agents join, Reports to should be settable there, not only under Management afterwards; card tsk-nbadjbr9zpg7 and the lead's go with its two points (seq 86087), 2026-11-07; docs/api.md §3.1, §2.3 ("to any other member, which is a cross-owner edge and takes effect only with the boss's side's consent"), §6.2 ("Own consent")
**Revisit when:** the contract gives the member view the pending edge (`reports_to_pending`), or a join that names `reports_to` for an agent already a member

The join panel offers **Reports to** in every case:

- **A first join, by an admin:** every member who is not a guest. One's own agents and oneself are plain; anyone else is marked "waits for consent", and the hub files that consent at the exchange (§3.1).
- **A member's own agent:** oneself (the default) and one's own managers in the project, the only bosses §3.1 lets a member's join name.
- **An agent already here:** a field of its own with the current boss. A change is the owner's own `PATCH …/members/{id}` (§2.3), sent before the join, so where it applies at once (200) the join page and the first resume show the new boss. Where it waits for the boss's side's consent (202, §6.2), the join page keeps the boss it was issued with, since the hub copies the boss into the join when it is created; the resume after the consent shows the new one.

If that `PATCH` is refused, no join is sent. If it is taken and the join then fails, the panel says both: the join's refusal, and the new boss, or the consent it waits for. A boss already asked for is not asked again in the same panel. The owner's **Reports to** on Members and Agents offers a boss of another owner too, marked the same way, its 202 said as the consent it waits for.

**Reason:** the maintainer wants to place agents, other owners' among them, at the moment they join, and §2.3 lets the owner start a cross-owner edge whatever their trust. The earlier rule (c848b045) held them back only until the contract settled that, which it now has.

**Rejected alternative:** a default boss on the agent profile, carried into every project: a boss is always a member of one project, and it would need a contract change (the lead, seq 86087). Sending `reports_to` in an instance's join: the hub refuses a membership field there (`differs_from_membership`). Undoing the `PATCH` when the join fails: the change was asked for on its own terms, and an undo could itself fail.

## Agents are added in Members: Add at the head of the agents' table, open joins as seats under it

**Id:** 621d28a8-36f5-4ebd-a90a-f7d729d7af34
**Type:** decision
**Status:** superseded
**Superseded by:** 54a49af9-4763-4b4c-8624-bf2c51a2bc34
**Evidence:** confirmed
**Source:** the maintainer's wish to fold the Agents page into Members (tsk-7v2snhk002ak, chat 2026-10-27); the coordinator's cut, whose second PR moves joining and the placements and removes the Agents page, 2026-10-27; the decided Team page's Members tab (context/members.md f0ca2279)
**Revisit when:** the Team page's Members tab lands, or joins get a lifecycle beyond open, used, expired, burned and revoked
**See:** views.md#joining-an-agent-happens-in-agents-a-panel-under-the-title-open-joins-as-seats-in-the-grid — d80f865d-5b59-4ad1-8cc2-c1079d13869c — as of 2026-10-27

The agents' heading on Members has **+ Add an agent** (owner and admin),
which opens the join panel under it: closed by default, open at once in a
project without agents or at `/<owner>/<slug>/team/join`. The panel is read beside the
list, never before it, so the rows and a member asked for by the URL do
not wait for the joins. Open joins stand as seats under the agents'
table, the placements after it, the earlier joins at the end. A count
line says how many agents, online and open joins there are.
There is no Agents tab; the old `…/agents` and `…/join` addresses are
gone since 2026-10-29 with the other old addresses (§16.11).

**Reason:** an agent is a member; adding one where the members are, and
seeing its seat next to them, keeps one place for the team, as the Team
page decided.

**Rejected alternative:** keeping Agents as a tab beside Members: two
views of the same people, with the actions split between them. Seats
inside the agents' table as rows: a seat is no member yet, and the table
is read by the hub's member list.

## A member adds their own agents from Agents while the policy's member_agents is not off

**Id:** 5cb62418-20f0-465f-b01e-be12e665a07e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §3.1 "Bringing your own agent" and §6.1 (`member_agents`, `member_agents_max`); the card tsk-zd2ch05rk7s1, 2026-10-27; the review of PR #472, 2026-10-27
**Revisit when:** §3.1 changes what counts

A human member without `members:admin` sees **+ Add my agent** at the
head of Agents (the agents' table on Members before 54a49af9) when the project's `member_agents`
is not `off`. The panel offers only what §3.1 lets a member
set (trust member or guest; every role of §2.3 but ops and proxy;
no reports to, no areas) and lists only the member's own joins. A line
says how many agents of theirs the project allows. The count is the
member's distinct agents that are active members or have an open join,
as the hub counts. At the limit the button stays while the member has an
agent in the project: the panel then makes another instance or a
replacement of one of them and refuses a new agent before sending.
Project settings turns the feature on or off and sets the limit.

Until 2026-10-30 the button also needed the field to be present at all,
for a hub that predated it and refused a member's join with 403; the
hub always sends it, so that check went with the alpha rule (e1699490).

**Reason:** an instance
or replacement counts nothing in §3.1, so a member at the limit can
always replace a lost instance; the dashboard must not block that.

**Rejected alternative:** the button off at the limit: it blocked the replacement §3.1
keeps open. Counting every open join: an instance's join counted as a
new agent.

## The team rulebook is on the agent's card and in its row, for its owner only

**Id:** 49804786-8704-4db6-a473-e348a12a77c5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.18 (only the human who owns the agent profile sets `team`); the card tsk-xzbk67raztm0, 2026-10-27; the review of PR #473, 2026-10-27
**Revisit when:** §6.18 lets an admin set a team's rulebook, or the Team page gives teams a place of their own

On the project's Agents, the card of one's own agent holds its **Team
rulebook**, and so does its Manage row on Members (since 54a49af9; the row
alone before); nobody else sees it, an admin included. The limit
shows the active instances beside it and says that lowering it stops
none. The lead is chosen among the active instances; one revoked since
stays chosen, marked revoked. Only the fields that changed are sent. A
join refused with `instance_quota` links to the card, focused at the
limit (`/<owner>/<slug>/agents/<id>/rulebook`), and does not edit the limit
in the join panel.

**Reason:** the contract gives the rulebook to the profile's owner
alone, so a form an admin could see would only fail. Sending only what
changed keeps a save of one field from overwriting another set
elsewhere, a revoked lead included.

**Rejected alternative:** editing the limit in the join panel where the
refusal appears: the panel's user may not be the owner, and the rulebook
would have two places. Alternatives to the row's placement: unknown.

## One's agents have a page of their own in the gear menu; adding one to a project is that project's join panel

**Id:** 1031c11b-7642-4ed9-87ce-de504b2044fc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on the card tsk-hn82893h9sdh, 2026-10-29 (agents belong to their owner and span projects; "add" means the join flow; the account keeps no agents section, one place); the maintainer's card tsk-05meme59sq1x, 2026-10-31 ("Join an agent" at the top, a list like Members with Manage, the instances inside); docs/api.md §6.3, §3.1, §6.17, §16.11 (`agents` a reserved first segment)
**Revisit when:** the hub can make a join for a profile without a project view (a join across projects), or the Team page's Members tab takes the profiles over

`/agents`, in the gear menu beside Runners, lists every agent profile of
the human (`GET /agents`): its picture, its memberships with trust, role
and the instances against the team's limit, its name, git identity and
handle, and its deletion; a new profile at the end. **Add to a project**
leads to that project's Agents with the join panel open and the
profile chosen (`/<owner>/<slug>/agents/join?agent=<id>`, since
54a49af9; Members before it): the one join
component, where the project's rules (who may bring agents, the
member's limit, the team's) are known. The profile asked for
(`?agent=<id>`) is kept across a failed first read of the joins, so
**Try again** opens the panel with it chosen, as the first open would
have. The handle is offered on every profile (§6.24); until 2026-10-30
only where the hub's machine form named it. `/agents/<id>` marks one profile.
The account keeps the human's own picture and points to this page; an
agent's picture stays settable on its card on a project's Agents and in
its Manage row on Members as well.

Since 2026-10-31 the page has **Join an agent**: a project chosen
(`?project=<owner>/<slug>`, which also opens the panel at once) and that
project's join panel, the same component mounted with the project's
context; since 2026-11-01 it stays closed until asked for (1ac94340).
The profiles below are a list like Members (picture, name and
global handle, projects, active instances, presence). **Manage** opens
under a row what the card held, and per membership the instances with
their credentials and revocation, the part Members' Manage uses, read in
that project's context when the row opens. A row stays open across a
redraw; a profile just made, or the one in `/agents/<id>`, opens its row.
A project's Agents is the same list limited to that project: one's own
agents there as rows (trust and role here, presence, active instances
here), Manage opening the card with what belongs to the membership here,
the agent in `agents/<id>` (or its rulebook) open from the start.

**Reason:** an agent is the owner's across projects, so its settings
need one place that is not a project; and the join panel already knows
each project's rules, which a second join flow on this page would have
to repeat.

**Rejected alternative:** a join form of its own on `/agents`: it would
repeat the project's join rules (§3.1's member limits, the team's
instance limit) apart from the panel and drift from it. Keeping the
agents in no project on the account: two places for the same profile.

## An agent profile is deleted where it is managed, confirmed by its handle, its projects named first

**Id:** 7929359f-6af1-415e-b6e6-a55dd40ca27c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-g1yz7rhaptqk (profiles deletable, with a confirmation by typing the handle and what happens), 2026-10-28; docs/api.md §6.3 (`profile_in_use`, `?cascade=true`, the tombstone)
**Revisit when:** the hub offers an undo or a grace period for a deleted profile, or deletion moves to a page of one's agents outside any project

The owner deletes a profile in its row on Members, beside its picture,
and on the account for an agent in no project of the owner's. The page
first names every project the profile is a member of and what deleting
it ends there (credentials, claims, placements), then enables the button
only once the handle is typed. A profile that is still a member
somewhere goes out with `?cascade=true`; one in no project, without.

**Reason:** a deletion cannot be undone, and in a project it ends a
working membership. Typing the handle makes it a deliberate act for this
very profile, and the named projects say what it costs before, not after.
In a Members row the profile is always a member, so the cascade is the
only deletion that can succeed there.

**Rejected alternative:** a plain `DELETE` first and a second
confirmation on `profile_in_use`: two dialogs for what the page can say
at once. A browser `confirm()`: it names neither the projects nor the
handle, and is clicked away too easily.

## The join panel reads all of a human's profiles and offers only those a project is allowed for

**Id:** de22411f-43b5-4a4e-b21f-eb1b03b61fdb
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.3; the card tsk-4sm441es9nwe

The join panel asks `GET /agents` and `GET /agents?allowed_in=` and offers the second list. A handle is taken among all of a human's profiles, whichever projects they may join, so the handle check keeps reading the first.

**Rejected alternative:** only `?allowed_in=` as the contract's sentence reads: the check would then call the handle of a profile not offered free, and the hub would refuse it after the form was filled in.

**Add to a project** on Your agents compares the list in the page, with a project's full name and its aliases: the page does not know the owner's old handles, so a project allowed under one is missing there and stays offered in that project's own join panel. An `?allowed_in=` read per project was rejected: one request per project for a rare case, on a page that lists them all.

## Add and Join are two buttons, the same on a project's Agents and on /agents, each opening its form

**Id:** 1ac94340-cc4e-4d87-9ec0-c26fbdf57e96
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer on the card tsk-mzaf9w83emn6, 2026-11-01; the split of the two words proposed on the card and accepted by the coordinator
**Revisit when:** a member's limit needs its own wording on the button, or profiles and joins merge into one form
**See:** views.md#ones-agents-have-a-page-of-their-own-in-the-gear-menu-adding-one-to-a-project-is-that-projects-join-panel — 1031c11b-7642-4ed9-87ce-de504b2044fc — as of 2026-11-01

Both pages have **+ Add an agent** and **Join an agent** at their head, and
a click opens the matching form, one at a time. Add makes a new profile. Join
is the join panel, for this project on a project's Agents, with a project to
choose on `/agents`. The section that stood open on `/agents` and the form
under its list are gone. This narrows the earlier use of "add" for the join
flow (1031c11b): on these two buttons add means a profile. A profile made on
a project's Agents goes straight on to the join panel, chosen there, since
it is in no project yet and would not show in that project's list.

The join panel still opens at once in three cases: `/<owner>/<slug>/agents/join`,
`/agents?project=`, and a project without an agent of one's own. A member
without `members:admin` sees the same **Join an agent** instead of **+ Add my
agent**; the limit beside it is unchanged.

Members' **Join an agent** leads to the project's Agents with the panel open,
no longer to `/agents`, and **All projects** has an **Agents** tab to `/agents`
(tsk-8sdgr8fbrn5v), which keeps its tabs on that page.

**Reason:** the maintainer wants the two pages as alike as possible, with the
forms folded until asked for. Add already opened the join panel on the
project's page, so a separate Join there needed Add to mean something else.

**Rejected alternatives:**
- Two buttons that both open the join panel on the project's page: the same
  action twice.
- Leaving the join section open on `/agents`: the maintainer asked for the form
  to open on the click.

## Join an agent asks for the second factor in its form, and names the project and the missing right

**Id:** 2e60e51f-5e0e-4bd0-bc46-365b3c050d13
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's reports on tsk-trb99kkhv1rk (an owner could not create a join and saw only "you lack the rights"; the maintainer saw "this call needs your second factor first" with the second factor set to mail for everyone), 2026-11-05; hub/src/maity_hub/routes/joins.py (`create_join` calls `require_step_up`), docs/api.md §2.8.4; web/js/step-up.js
**Revisit when:** the hub stops treating join creation as a sensitive call, or the dashboard gets one step-up place for every view

Creating a join goes through `M.stepUp.run`, the same as every other
sensitive call in the dashboard: on `step_up_required` the form asks for
the code (by app, or the mailed code under the mail factor) and sends the
join again; Cancel ends without a refusal. A bare `forbidden` with
`scope: members:admin` (no admin rights, and members may not bring
agents) is said in words that name the right. The panel names the project
the join is for, by name and full name.

**Reason:** the hub has always asked for the second factor on
`POST …/joins`, but the join form showed it as a refusal: in English
the hub's own sentence, translated as the generic "you do not have the
rights for this", so an owner who had done nothing wrong could not add an
agent at all. With several projects open the target project was only the
tab's.

**Rejected:** a hub change (the hub's rule is right; a sole owner may not
make themselves admin either, the maintainer confirmed); a generic words
entry for `step_up_required` in js/errors.js alone, which would say the
cause but still leave no way to give the code.

## An agent's motif is chosen beside its picture, named with the hub's English label

**Id:** d5f1e318-5368-4516-9d10-06a2194aaafd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-q155psrk6tzz, step 3 (the dashboard's part of the hub's motifs, 1c51a4c6); docs/api.md §6.10, "An agent's motif" (the dashboard shows its catalogue's `avatar.motif.<name>` where it has one)
**Revisit when:** the catalog gets the motifs' names in other languages, or the set grows past what one list can show
**See:** views.md#ones-agents-have-a-page-of-their-own-in-the-gear-menu-adding-one-to-a-project-is-that-projects-join-panel — 1031c11b-7642-4ed9-87ce-de504b2044fc — as of 2026-11-07

The owner chooses an agent's motif in the same picture editor as the upload, on the agent's card on
Agents and in its Manage row on Members, with `PATCH /agents/{id}` (`avatar_motif`, `null` to clear
it). It is one list of `GET /avatars/motifs`, its themes as groups headed by the catalog's
`avatar.motif.theme.<theme>`, plus a preview of the chosen motif from its public address with the
hub's `alt`. A motif is named with the hub's own `label`. The catalog holds no
`avatar.motif.<name>` yet, so the names stay English in every language, as the contract allows.

**Reason:** the catalog's keys must be literals in the code (`make check` reads them there), so
naming 36 motifs would mean a table of 36 keys in the view, kept in step with the hub's set by
hand. The hub's label is always there, current with the set it serves, and the theme headings are
two fixed words.

**Rejected alternatives:**
- A grid of all motifs as pictures, chosen by a click: every opened card would load 36 images at
  once, and the choice would need its own keyboard handling, which a `<select>` already has.
- Catalog keys for every motif now: a table that falls out of step with each new motif in the set.
