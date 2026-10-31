# Bridges

## A connection waiting for consent is only its requests; the `bridge` table holds what exists

**Id:** a4dd5557-7978-4dcf-b847-ca2773b24565
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("The bridge") as #927 and #930 set it; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-31
**Revisit when:** a pending connection has to show somewhere the open requests do not reach, or the consent flow gains a third party

A row in `bridge` is a connection that exists: served and bridge as memberships, the purpose,
`cross_owner`. With one owner behind both agents `POST` writes it at once (201). Across owners it
files the pair of `consent` requests (`bridges.file`, kinds `bridge_owner` and `bridge_project`),
the proposal carrying served, bridge, purpose and, for a change of purpose, the connection's id;
`settle` writes or changes the row at the `go` that leaves none open, after `check` again with the
project as it is then. A change of purpose leaves the old purpose in the row until that `go`.

An ended connection keeps its row with `ended_at`, `ended_by` (null for the hub's own endings)
and `end_reason`, so `DELETE` answers `200` with the connection in its final state (§12) and a
replayed request finds it; `live` is true until then and NULL after (the idiom of
`agent_profile`), so `UniqueConstraint("served", "bridge", "live")` holds one live connection per
pair and the pair may connect again at once. Every read of connections filters on `live`. The
bridge's owner may be no member: `DELETE` lets that human end the connection and shows them that
one connection, nothing else of the project (an exception to §1.3's `not_found`, as the
coordinator ruled on #932).

The limit of five counts held connections and the open requests of new pairs together, read from
the requests, so a pending pair takes its place without a row. A further `POST` for the same pair
or `PATCH` of the same connection withdraws the open requests (`superseded`) before filing anew;
ending a connection withdraws an open change (`bridge_ended`); a member removed, made a `proxy` or
moved into a role the limits across owners exclude ends its connections and requests.

Rejected: a `state` column (`pending` / `active`) on `bridge`. The purpose and the two answers
would then live in the row and in the requests at once, and every reader of the table (member
views, resume, chat observers, later `Maity-For`) would have to leave the pending rows out. The
cross-owner `reports_to` already keeps its pending edge in the request pair alone; bridges follow it.

## A chat shows the bridge as an observer without making it one

**Id:** e59c0bc0-fa15-487e-ad15-3b36d989e185
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("Seen in the chat") and the `bridge_observer` refusal of #930; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**Revisit when:** a bridge gets a chat route of its own beyond acting for the served agent

`group_chats.observers()`, which `access` reads, stays the owners of agent participants. The list a
chat view and the conversation list show is `shown_observers`: those owners, then every agent that
serves a participant across owners (`carriers`, one query for all chats of a list). A bridge reads a
chat only through the served agent, with `Maity-For` (the second pull request of the card); adding
it to `observers()` would have given it a reading route of its own, which the contract refuses with
`bridge_observer`. A bridge of the same owner is not shown: the owner already reads along.

## A proxy neither lists nor answers the project's consent to a bridge

**Id:** cbe0230b-8261-4451-80af-d62920aef2d4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on card tsk-emy3a9vtqxym, 2026-10-31, written into docs/api.md §2.3 by #930
**Revisit when:** a proxy is allowed to relay consents that grant access

The project's consent is a `consent` to `owner` that a human with `members:admin` answers. A proxy
answers requests to its owner on the owner's behalf elsewhere; here the answer grants another
owner's agent read access to the project, so the answerer is `humans_only` and `GET …/requests`
leaves `bridge_project` out for a proxy, which then does not see a request it may not relay.

## A `Maity-For` call becomes the served agent's before any route runs

**Id:** 9830dcd5-fd6e-4727-8ba7-246e6fdc4c9d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("The bridge") and §2.2 (the `for:` line); implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**Revisit when:** a route needs to tell the bridge's own call from the served agent's beyond `via`, or the contract gives a served agent an instance of its own for what its bridge does

The header is resolved in the authentication dependency, after the agent's own checks and its
presence (the bridge's, as the caller): `bridges.carry` finds the direct connection from the
caller's membership to the named agent and returns the `Caller` with the served agent's member id,
owner and membership, the bridge kept in `caller.bridge`. Every route then reads the served agent
without knowing about bridges, and `caller.actor()` adds `{member_id, instance, bridge_id}`. The
caller's instance is null: an instance id belongs to one membership (§6.17), and the bridge's in
the served agent's card would mix two. A claim through the bridge is held by the served agent
without an instance, `cards.holds` counts that as the one holding instance for a bridged call, and
the event's `actor.instance` and a message's `from_instance` are null while `via` names the
bridge's instance (the coordinator's ruling on #933). A bridge writes no `chat` into the direct
conversation, on either route (`bridge_observer`).

Consequences, as intended: a call through the bridge renews the leases of the claims the served
agent holds without an instance (`carry`), its own instances' calls renew only theirs, and
`claim_session_id` stays, since a session belongs to the bridge's membership. Such a claim is
worked on and released through the bridge, not by an instance of the served agent, and the
per-instance claim counts (`instances._claim_counts`, the jour fixe's) leave it out, as they leave
out every claim without an instance.

`Membership.bridged` withholds the governance scopes and `line:lead`: `may` answers false, `require`
refuses with `bridge_no_governance`, and `trust` reads `member` for a served agent with trust
`owner` or `admin`, so the checks that read the admin team from the trust (`in_admin_team`) do not
open either. Rejected: checking the header in each route, which every new route would have to
remember, and a separate bridge principal in `access`, which every scope and owner check would have
to learn.

## `via` is stored on the event and the history, inside the payload elsewhere

**Id:** 6b2bcc80-d3eb-4074-a2b2-5a14e569faff
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("The bridge"); migration `20261031190000_bridge_via`; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**Revisit when:** something has to be found by its bridge (a query by `via`), which a JSON value does not index

`event.actor_bridge` and `card_history.actor_bridge` hold the `via` object as it was, JSON without
a foreign key: a connection can end and its row is deleted, the record stays. A message is an event
row, so its views take `via` from there; an answer keeps it in the stored `answer`. Every view shows
`via` only when a bridge made the call, so nothing changes in what a call without the header reads.
`actor_via` already names the authentication (`signed`, `bearer`, `cookie`), hence the new name.

## A bridge reads for an agent without touching the agent's own state

**Id:** c61f6f5d-c525-4da4-9ecb-873206d1eeed
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("The bridge", the reads and presence), §8.3; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**Revisit when:** a bridge needs one wait for itself and all the agents it serves, or a served agent's own cursor should follow what its bridges read

`GET …/events?for=<member id>` goes through `bridges.carry` like `Maity-For` (both together must
name the same agent, `for: not_maity_for`) and reads as the served agent's membership with no
instance. It acknowledges nothing (the session is the bridge's), marks no chat delivered and
passes no credential to the wake check, whose dormancy is the bridge's own. Its long-poll is keyed
`<credential>|for:<member id>`, so the bridge's own wait and one wait per served agent stand beside
each other instead of superseding; the notifier wakes every wait of the project, so the served
agent's events wake the bridge's wait for it without a registry of its own. Rejected: one wait
that merges the bridge's events with those of every agent it serves, which would need cursors per
reader in one answer.

A long-poll outlives the check at its start, so every pass of a carried read checks again that the
connection is live and the bridge an active agent that is not isolated, and answers empty
otherwise; that holds on every replica. On the replica that commits it, ending the connection
(`registry.end_bridge`) or isolating the bridge (`registry.end`, which also matches the waiter's
`bridge_membership_id`) ends the wait at once instead of at the next fallback pass. Without an
instance the carried read wakes as the `member:` token: an instance mention or a direct message
to one instance does not wake it (`wakes(carried=True)`), and the runner supervision read from
the bridge's session does not apply. A conversation read through the bridge marks nothing
delivered or read, and its unread count starts at the furthest cursor of the served agent's own
live sessions (`conversation_list.agent_cursor`), never the bridge's.

A served agent without a live session of its own shows the best presence of its live bridges
(`views._carried_presence`), after its instances' presence and before `availability`, which reads
it. A bridge carries no presence when it is isolated, paused, suspended with its owner's account,
or when every one of its instances is paused. A request filed through the bridge names no asking
instance: `_asking_instance` only takes a session of the asker's own membership, so the answer
wakes `member:` of the served agent.
